import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {transformSync} from 'esbuild';
import {clueLabels, displayStatus, savedTime} from '../src/presentation.js';
import * as presentation from '../src/presentation.js';

const require=createRequire(import.meta.url);
const module={exports:{}};
const code=transformSync(readFileSync(new URL('../src/DossierView.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'cjs'}).code;
runInNewContext(code,{module,exports:module.exports,require:name=>name==='./presentation.js'?presentation:require(name)});
const {DossierView}=module.exports;
const base={game:null,id:'',message:'',busy:false,feedback:null,onIdChange(){},onMessageChange(){},onNewGame(){},onContinue(){},onSend(){}};
const game={session_id:'hidden-until-disclosed',scenario_id:'paper_chase',status:'active',updated_at:'2026-09-30T12:00:00Z',
  state:{hp:10,san:50,location_name:'Cemetery',discovered_clues:['clue_missing_books'],clue_names:{clue_missing_books:'Missing Books',undiscovered:'PRIVATE CLUE NAME'}},
  messages:[{role:'keeper',content:'An already-visible opening briefing.'},{role:'player',content:'I look around.'}]};
const html=props=>renderToStaticMarkup(React.createElement(DossierView,{...base,...props}));
function find(tree,predicate) {
  if (!tree || typeof tree!=='object') return null;
  if (predicate(tree)) return tree;
  for(const child of React.Children.toArray(tree.props?.children)) {const found=find(child,predicate);if(found)return found;}
  return null;
}

test('new case and continue controls retain their actual handlers',()=>{
  let created=0,continued=0;
  const view=DossierView({...base,id:'saved-id',onNewGame:()=>created++,onContinue:()=>continued++});
  find(view,e=>e.type==='button'&&e.props.className==='new-game').props.onClick();
  find(view,e=>e.type==='form'&&e.props.className==='resume-sheet').props.onSubmit();
  assert.equal(created,1);assert.equal(continued,1);
  assert.match(html({}),/Open the case file/);
  assert.match(html({}),/Continue Game/);
});

test('action input and submission remain multiline and preserve handlers',()=>{
  let value='',submissions=0;
  const view=DossierView({...base,game,message:'I look.',onMessageChange:v=>value=v,onSend:()=>submissions++});
  const input=find(view,e=>e.type==='textarea');
  input.props.onChange({target:{value:'First line\nSecond line'}});
  find(view,e=>e.type==='form'&&e.props.className==='action-composer').props.onSubmit();
  assert.equal(value,'First line\nSecond line');assert.equal(submissions,1);
  assert.equal(input.props.onKeyDown,undefined); // Enter remains a newline, not a submission.
  assert.equal(input.props.disabled,false);
});

test('loading disables controls and announces processing',()=>{
  const view=DossierView({...base,game,message:'Act',busy:true});
  assert.equal(find(view,e=>e.type==='textarea').props.disabled,true);
  assert.equal(find(view,e=>e.type==='button'&&e.props.className==='send-action').props.disabled,true);
  assert.equal(find(view,e=>e.type==='button'&&e.props.className==='new-game').props.disabled,true);
  assert.match(html({game,busy:true}),/Keeper working/);
});

test('discovered labels render without rendering identifiers or hidden map entries',()=>{
  const rendered=html({game});
  assert.match(rendered,/Missing Books/);
  assert.doesNotMatch(rendered,/clue_missing_books|PRIVATE CLUE NAME|undiscovered/);
  assert.deepEqual(clueLabels(game.state),['Missing Books']);
});

test('missing label uses neutral fallback rather than parsing an internal ID',()=>{
  const state={discovered_clues:['clue_SECRET_IDENTITY'],clue_names:{}};
  assert.deepEqual(clueLabels(state),['Discovered evidence']);
  assert.doesNotMatch(html({game:{...game,state}}),/SECRET_IDENTITY/);
});

test('case notes use only the existing player-visible opening briefing',()=>{
  assert.match(html({game}),/An already-visible opening briefing/);
  assert.doesNotMatch(html({game:{...game,keeper_truth:'PRIVATE TRUTH',state:{...game.state,npc_state:{secret:'PRIVATE NPC'}}}}),/PRIVATE TRUTH|PRIVATE NPC/);
});

test('clarification remains an ordinary Keeper transcript message',()=>{
  const clarified={...game,turn_outcome:'clarification',messages:[...game.messages,{role:'keeper',content:'You have not identified the marker yet.'}]};
  const rendered=html({game:clarified});
  assert.match(rendered,/You have not identified the marker yet/);
  assert.match(rendered,/Keeper clarification · Saved/);
  assert.doesNotMatch(rendered,/Request failed|role="alert"/);
});

test('unsupported action and technical failure remain distinct',()=>{
  const unsupported=html({game,feedback:{kind:'gameplay',outcome:'unsupported',message:'Combat is unsupported.'}});
  assert.match(unsupported,/Unsupported action/);assert.doesNotMatch(unsupported,/Request failed|role="alert"/);
  const failed=html({game,feedback:{kind:'error',message:'Connection interrupted.'}});
  assert.match(failed,/Request failed — last saved session shown/);assert.match(failed,/role="alert"/);
});

test('stored session renders the exact reloaded conversation and real vitals without invented maxima',()=>{
  const rendered=html({game});
  assert.match(rendered,/I look around/);assert.match(rendered,/Cemetery/);
  assert.match(rendered,/<dd>10/);assert.match(rendered,/<dd>50/);
  assert.doesNotMatch(rendered,/10 \/ 10|50 \/ 50/);
  assert.doesNotMatch(rendered,/2026-09-30T/);
  assert.match(rendered,/<details class="session-metadata">/);
});

test('mechanics note uses the actual pending-push boolean without invented rolls',()=>{
  assert.doesNotMatch(html({game}),/Pending push/);
  assert.match(html({game:{...game,state:{...game.state,push_available:true}}}),/Pending push · opportunity recorded/);
  assert.doesNotMatch(html({game}),/72 \/ 40|CHARM CHECK/);
});

test('status and safe time formatting handle the empty case',()=>{
  assert.equal(displayStatus({}), 'No case open');
  assert.equal(savedTime(null),'Not recorded');assert.equal(savedTime('invalid'),'Not recorded');
});
