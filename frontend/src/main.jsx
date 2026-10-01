import React, {useState, useRef, useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {createSessionClient, submitPlayerAction, requestFeedback, requestStatus} from './sessionClient.js';

function App() {
  const [game, setGame] = useState(null);
  const [id, setId] = useState(localStorage.getItem('coc-session') || '');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const client = useRef(createSessionClient());
  async function request(path, body, playerAction = false) {
    if (client.current.pending) return false;
    setBusy(true); setFeedback(null);
    try {
      const session = playerAction
        ? await submitPlayerAction(client.current, localStorage, game.session_id, body.message)
        : await client.current.request(path, body);
      setGame(session); setId(session.session_id);
      localStorage.setItem('coc-session', session.session_id);
      return true;
    } catch(e) { setFeedback(requestFeedback(e)); return false; }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const savedId = localStorage.getItem('coc-session');
    if (savedId) request(`/api/game/${encodeURIComponent(savedId)}`);
  }, []);
  async function send(e) {
    e.preventDefault();
    if (!game || client.current.pending || !message.trim()) return;
    try {
      if (await request(`/api/game/${game.session_id}/action`, {message}, true)) setMessage('');
    } catch (e) { setFeedback(requestFeedback(e)); }
  }
  return <><header><h1>CoC AI Keeper</h1><p>Paper Chase prototype · Real Keeper · Limited actions</p>
    <button disabled={busy} onClick={()=>request('/api/game/new', {})}>New Game</button>
    <input aria-label="Session ID" value={id} onChange={e=>setId(e.target.value)} placeholder="Session ID" />
    <button disabled={busy || !id.trim()} onClick={()=>request(`/api/game/${encodeURIComponent(id.trim())}`)}>Continue Game</button>
  </header>{feedback && <p role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>}<div className="layout"><main>
    <section aria-label="Conversation" aria-live="polite">{!game && <p>Start Paper Chase or continue using a saved session ID.</p>}
    {game?.messages.map((m,i)=><article key={i}><strong>{m.role === 'keeper' ? 'Keeper' : 'You'}</strong><p>{m.content}</p></article>)}</section>
    <form onSubmit={send}><label htmlFor="action">Your action</label><textarea id="action" value={message} maxLength={10000} onChange={e=>setMessage(e.target.value)} disabled={!game || busy}/>
    <button disabled={!game || busy || !message.trim()}>Send</button></form>
  </main><aside><h2>Investigator</h2><p>HP: {game?.state.hp ?? '—'}</p><p>SAN: {game?.state.san ?? '—'}</p>
    <p>Location: {game?.state.location_name ?? game?.state.current_location ?? 'Not set'}</p><h3>Discovered clues</h3>
    <ul>{game?.state.discovered_clues.map(c=><li key={c}>{c}</li>)}</ul>{!game?.state.discovered_clues.length && <p>None</p>}
    <p role="status">{requestStatus({busy, feedback, game})}</p>
    {game && <><small>Session: {game.session_id}</small><p><small>Last saved: {game.updated_at}</small></p></>}
  </aside></div></>;
}
createRoot(document.getElementById('root')).render(<App/>);
