import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

function App() {
  const [game, setGame] = useState(null);
  const [id, setId] = useState(localStorage.getItem('coc-session') || '');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function request(path, body) {
    setBusy(true); setError('');
    try {
      const response = await fetch(path, body === undefined ? {} : {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
      });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const session = await response.json();
      setGame(session); setId(session.session_id);
      localStorage.setItem('coc-session', session.session_id);
      return true;
    } catch(e) { setError(e.message); return false; }
    finally { setBusy(false); }
  }
  async function send(e) {
    e.preventDefault();
    if (await request(`/api/game/${game.session_id}/action`, {message})) setMessage('');
  }
  return <><header><h1>CoC AI Keeper</h1><p>Local skeleton · Placeholder Keeper · No scenario loaded</p>
    <button disabled={busy} onClick={()=>request('/api/game/new', {})}>New Game</button>
    <input aria-label="Session ID" value={id} onChange={e=>setId(e.target.value)} placeholder="Session ID" />
    <button disabled={busy || !id.trim()} onClick={()=>request(`/api/game/${encodeURIComponent(id.trim())}`)}>Continue Game</button>
  </header>{error && <p role="alert">{error}</p>}<div className="layout"><main>
    <section aria-label="Conversation" aria-live="polite">{!game && <p>Start a placeholder game or continue using a saved session ID.</p>}
    {game?.messages.map((m,i)=><article key={i}><strong>{m.role === 'keeper' ? 'Keeper' : 'You'}</strong><p>{m.content}</p></article>)}</section>
    <form onSubmit={send}><label htmlFor="action">Your action</label><textarea id="action" value={message} maxLength={10000} onChange={e=>setMessage(e.target.value)} disabled={!game || busy}/>
    <button disabled={!game || busy || !message.trim()}>Send</button></form>
  </main><aside><h2>Investigator</h2><p>HP: {game?.state.hp ?? '—'}</p><p>SAN: {game?.state.san ?? '—'}</p>
    <p>Location: {game?.state.current_location ?? 'Not set'}</p><h3>Discovered clues</h3>
    <ul>{game?.state.discovered_clues.map(c=><li key={c}>{c}</li>)}</ul>{!game?.state.discovered_clues.length && <p>None</p>}
    <p role="status">{busy ? 'Saving / loading…' : error ? 'Request failed — last saved session shown' : game ? 'Saved · ' + game.status : 'No session'}</p>
    {game && <><small>Session: {game.session_id}</small><p><small>Last saved: {game.updated_at}</small></p></>}
  </aside></div></>;
}
createRoot(document.getElementById('root')).render(<App/>);
