import React, {useState, useRef, useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {DossierView} from './DossierView.jsx';
import {createSessionClient, submitPlayerAction, requestFeedback} from './sessionClient.js';

function App() {
  const [game, setGame] = useState(null);
  const [id, setId] = useState(localStorage.getItem('coc-session') || '');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const client = useRef(createSessionClient());
  const transcript = useRef(null);
  useEffect(() => {
    if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [game?.messages.length, busy]);
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
  return <DossierView game={game} id={id} message={message} busy={busy} feedback={feedback}
    onIdChange={setId} onMessageChange={setMessage} transcriptRef={transcript}
    onNewGame={()=>request('/api/game/new', {})}
    onContinue={e=>{ e.preventDefault(); if (id.trim()) request(`/api/game/${encodeURIComponent(id.trim())}`); }}
    onSend={send}/>;
}
createRoot(document.getElementById('root')).render(<App/>);
