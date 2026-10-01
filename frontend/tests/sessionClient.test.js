import test from 'node:test';
import assert from 'node:assert/strict';
import {createSessionClient, getPendingTurn, submitPlayerAction} from '../src/sessionClient.js';

test('synchronous lock prevents a second pending request', async () => {
  let resolve;
  let calls = 0;
  const client = createSessionClient(() => { calls++; return new Promise(r => { resolve = r; }); });
  const first = client.request('/api/game/id/action', {message:'look', turn_id:'stable'});
  assert.equal(client.pending, true);
  await assert.rejects(client.request('/api/game/id/action', {}), /already being processed/);
  assert.equal(calls, 1);
  resolve({ok:true, json:async()=>({session_id:'id'})});
  assert.equal((await first).session_id, 'id');
  assert.equal(client.pending, false);
});

test('controlled errors render their message and release the lock', async () => {
  const client = createSessionClient(async()=>({ok:false,status:409,json:async()=>({detail:{message:'Turn needs review',status:'error'}})}));
  await assert.rejects(client.request('/action', {}), /Turn needs review/);
  assert.equal(client.pending, false);
});

test('network failure and reload retain the same turn ID', () => {
  const values = new Map();
  const storage = {getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  const first = getPendingTurn(storage,'id','I search.',()=> 'first-id');
  const retry = getPendingTurn(storage,'id','I search.',()=> 'different-id');
  assert.deepEqual(first,retry);
  assert.equal(getPendingTurn(storage,'id','I look.',()=> 'new-id').turn_id, 'new-id');
});

test('HTTP action body includes stable ID and free-form message', async () => {
  let captured;
  const client = createSessionClient(async(path,options)=>{captured={path,options};return {ok:true,json:async()=>({session_id:'id'})};});
  await client.request('/api/game/id/action',{message:"I search the study.",turn_id:'stable-id'});
  assert.deepEqual(JSON.parse(captured.options.body),{message:'I search the study.',turn_id:'stable-id'});
});


function memoryStorage() {
  const values = new Map();
  return {getItem:k=>values.get(k), setItem:(k,v)=>values.set(k,v), removeItem:k=>values.delete(k)};
}

test('completed A retires ID A; new B has ID B; uncertain B retry keeps ID B', async () => {
  const storage = memoryStorage();
  const sent = [];
  let attempt = 0;
  const client = createSessionClient(async(path,options) => {
    sent.push(JSON.parse(options.body));
    attempt++;
    if (attempt === 2) throw new Error('Connection interrupted');
    return {ok:true,json:async()=>({session_id:'id'})};
  });
  await submitPlayerAction(client,storage,'id',"I search Douglas's study.",()=> 'id-A');
  assert.equal(storage.getItem('coc-pending-id'),undefined);
  await assert.rejects(submitPlayerAction(client,storage,'id','I think I know the thief.',()=> 'id-B'),/Connection interrupted/);
  await submitPlayerAction(client,storage,'id','I think I know the thief.',()=> 'must-not-be-used');
  assert.deepEqual(sent.map(t=>t.turn_id),['id-A','id-B','id-B']);
  assert.notEqual(sent[0].turn_id,sent[1].turn_id);
});

test('a new intentional submission after completion gets a new ID even with identical text', async () => {
  const storage = memoryStorage();
  const ids = [];
  const client = createSessionClient(async(path,options)=> {
    ids.push(JSON.parse(options.body).turn_id);
    return {ok:true,json:async()=>({session_id:'id'})};
  });
  await submitPlayerAction(client,storage,'id','I look around.',()=> 'first');
  await submitPlayerAction(client,storage,'id','I look around.',()=> 'second');
  assert.deepEqual(ids,['first','second']);
});

test('an in-flight submission retains identity and rejects a concurrent new action', async () => {
  const storage = memoryStorage();
  let resolve;
  const client = createSessionClient(()=>new Promise(r=>{resolve=r;}));
  const pending = submitPlayerAction(client,storage,'id','action A',()=> 'id-A');
  await assert.rejects(submitPlayerAction(client,storage,'id','action B',()=> 'id-B'),/already being processed/);
  assert.equal(JSON.parse(storage.getItem('coc-pending-id')).turn_id,'id-A');
  assert.equal(getPendingTurn(storage,'id','action A',()=> 'new').turn_id,'id-A');
  resolve({ok:true,json:async()=>({session_id:'id'})});
  await pending;
});

test('terminal clarification retires its rejected ID rather than retrying a failed receipt', async () => {
  const storage = memoryStorage();
  const ids = [];
  const client = createSessionClient(async(path,options)=> {
    const turn = JSON.parse(options.body); ids.push(turn.turn_id);
    return {ok:false,status:400,json:async()=>({detail:{message:'Please clarify',status:'clarification',turn_id:turn.turn_id}})};
  });
  await assert.rejects(submitPlayerAction(client,storage,'id','guess',()=> 'rejected-B'),/Please clarify/);
  assert.equal(storage.getItem('coc-pending-id'),undefined);
  await assert.rejects(submitPlayerAction(client,storage,'id','guess',()=> 'new-submission'),/Please clarify/);
  assert.deepEqual(ids,['rejected-B','new-submission']);
});

test('409 errors preserve IDs and cannot silently create a replacement execution', async () => {
  const storage = memoryStorage();
  const ids = [];
  const client = createSessionClient(async(path,options)=> {
    const turn=JSON.parse(options.body); ids.push(turn.turn_id);
    return {ok:false,status:409,json:async()=>({detail:{message:'Needs review',status:'error',turn_id:turn.turn_id}})};
  });
  await assert.rejects(submitPlayerAction(client,storage,'id','guess',()=> 'id-B'));
  await assert.rejects(submitPlayerAction(client,storage,'id','guess',()=> 'replacement'));
  assert.deepEqual(ids,['id-B','id-B']);
});

// These helpers are used directly by React's feedback/status presentation.
const {requestFeedback, requestStatus, SessionRequestError} = await import('../src/sessionClient.js');

test('saved gameplay clarification is a conversation, not request failure', async () => {
  const storage = memoryStorage();
  const session = {session_id:'id', status:'active', turn_outcome:'clarification',
    messages:[{role:'player',content:'Inspect the marker.'},{role:'keeper',content:'You have not identified the marker yet.'}]};
  const client = createSessionClient(async()=>({ok:true,status:200,json:async()=>session}));
  const saved = await submitPlayerAction(client,storage,'id','Inspect the marker.',()=> 'clarify-id');
  assert.deepEqual(saved.messages,session.messages);
  assert.equal(requestStatus({busy:false,feedback:null,game:saved}),'Saved · Keeper clarification');
  assert.doesNotMatch(requestStatus({game:saved}),/Request failed/);
  assert.equal(storage.getItem('coc-pending-id'),undefined);
});

test('legacy gameplay clarification has non-error presentation', () => {
  const feedback=requestFeedback(new SessionRequestError('Please clarify the target.',400,{status:'clarification'}));
  assert.equal(feedback.kind,'gameplay');
  assert.equal(feedback.outcome,'clarification');
  assert.doesNotMatch(requestStatus({feedback}),/Request failed/);
});

test('unsupported gameplay remains distinct and does not imply a server crash', () => {
  const feedback=requestFeedback(new SessionRequestError('Combat is unsupported.',400,{status:'unsupported'}));
  assert.equal(feedback.kind,'gameplay');
  assert.equal(feedback.outcome,'unsupported');
  assert.match(requestStatus({feedback}),/Unsupported action/);
  assert.doesNotMatch(requestStatus({feedback}),/Request failed|clarification/);
});

test('actual backend failure shows request failure and retains retry identity', async () => {
  const storage=memoryStorage();
  const client=createSessionClient(async()=>({ok:false,status:409,json:async()=>({detail:{message:'Turn needs review',status:'error',turn_id:'failed-id'}})}));
  let feedback;
  try { await submitPlayerAction(client,storage,'id','Search.',()=> 'failed-id'); }
  catch(error) { feedback=requestFeedback(error); }
  assert.equal(feedback.kind,'error');
  assert.equal(requestStatus({feedback}),'Request failed — last saved session shown');
  assert.equal(JSON.parse(storage.getItem('coc-pending-id')).turn_id,'failed-id');
});

test('network and 503 failures retain technical failure presentation', () => {
  for (const error of [new Error('Connection interrupted'),new SessionRequestError('Provider unavailable',503,{status:'clarification'})]) {
    const feedback=requestFeedback(error);
    assert.equal(feedback.kind,'error');
    assert.match(requestStatus({feedback}),/Request failed/);
  }
});

test('new action after a saved clarification gets a fresh turn ID', async () => {
  const storage=memoryStorage();
  const ids=[];
  const client=createSessionClient(async(path,options)=> {
    ids.push(JSON.parse(options.body).turn_id);
    return {ok:true,status:200,json:async()=>({session_id:'id',status:'active',turn_outcome:ids.length===1?'clarification':'completed'})};
  });
  await submitPlayerAction(client,storage,'id','Inspect marker.',()=> 'clarify-id');
  await submitPlayerAction(client,storage,'id','Look around.',()=> 'observe-id');
  assert.deepEqual(ids,['clarify-id','observe-id']);
});
