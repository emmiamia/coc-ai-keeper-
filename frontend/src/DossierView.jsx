import React from 'react';
import {clueLabels, displayStatus, savedTime} from './presentation.js';

function Mark({type, className = ''}) {
  const shapes = {
    keeper: <><circle cx="24" cy="24" r="18"/><path d="M10 24q14-18 28 0-14 18-28 0Z"/><circle cx="24" cy="24" r="5"/><path d="M24 3v5m0 32v5M3 24h5m32 0h5M9 9l4 4m22 22 4 4M9 39l4-4m22-22 4-4"/></>,
    player: <><path d="M13 21l4-11h14l4 11M8 23h32M17 25v7l-7 11h28l-7-11v-7"/></>,
    location: <><path d="M24 43S10 27 10 18a14 14 0 0 1 28 0c0 9-14 25-14 25Z"/><circle cx="24" cy="18" r="5"/></>,
    book: <><path d="M24 11v31M5 7q11-2 19 4 8-6 19-4v31q-11-2-19 4-8-6-19-4Z"/></>,
    notes: <><path d="M11 5h26v38H11Z"/><path d="M17 14h14m-14 8h14m-14 8h10"/></>
  };
  return <svg viewBox="0 0 48 48" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" focusable="false">{shapes[type]}</svg>;
}

export function DossierView({game, id, message, busy, feedback, onIdChange, onMessageChange, onNewGame, onContinue, onSend, transcriptRef}) {
  const clues = clueLabels(game?.state);
  const briefing = game?.messages?.[0]?.role === 'keeper' ? game.messages[0].content : null;
  const scenario = !game || game.scenario_id === 'paper_chase' ? 'Paper Chase' : 'Saved investigation';
  const statusKind = feedback?.kind === 'error' ? 'error' : feedback?.kind === 'gameplay' || game?.turn_outcome === 'clarification' ? 'gameplay' : busy ? 'busy' : game ? 'saved' : 'idle';
  return <div className="case-cover">
    <header className="case-header">
      <div className="product"><h1>CoC AI Keeper</h1><span className="edition">Paper Chase Prototype</span></div>
      <nav className="case-controls" aria-label="Game controls">
        <button className="new-game" disabled={busy} onClick={onNewGame}>New Game</button>
        <details className="resume"><summary>Continue Game</summary>
          <form className="resume-sheet" onSubmit={onContinue}>
            <label htmlFor="session-reference">Session reference</label>
            <input id="session-reference" aria-label="Session ID" value={id} onChange={e=>onIdChange(e.target.value)} placeholder="Paste a saved session ID" disabled={busy}/>
            <button disabled={busy || !id.trim()}>Open case</button>
          </form>
        </details>
      </nav>
      <div className="case-status"><span className="scenario-title">{scenario}</span>
        <span role="status" className={`save-status ${statusKind}`}><i aria-hidden="true"/>{displayStatus({busy, feedback, game})}</span>
      </div>
    </header>
    {feedback && <div className={`feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</div>}
    <div className="case-layout">
      <main className="transcript-sheet" ref={transcriptRef} tabIndex="0" aria-label="Session transcript">
        <section aria-label="Conversation" aria-live="polite" aria-busy={busy}>
          <h2 className="visually-hidden">Session record</h2>
          {!game && <div className="empty-case">
            <span className="archive-label">An investigation awaits</span><Mark type="keeper" className="empty-seal"/>
            <h2>Open the case file.</h2><p>Begin Paper Chase, or return to a saved investigation.<br/>Your story will be recorded here.</p>
            <span className="empty-rule" aria-hidden="true"/>
          </div>}
          {game?.messages.map((m,i)=><article className={`transcript-turn ${m.role === 'keeper' ? 'keeper-turn' : 'player-turn'}`} key={i}>
            <span className="role-seal"><Mark type={m.role === 'keeper' ? 'keeper' : 'player'}/></span>
            <div className="turn-copy"><h3 className="role-label">{m.role === 'keeper' ? 'Keeper' : 'You'}</h3><p>{m.content}</p></div>
          </article>)}
          {busy && game && <p className="working-note">The Keeper is considering your action…</p>}
        </section>
      </main>
      <aside className="dossier-sheet" aria-label="Investigator dossier" tabIndex="0">
        <span className="paper-clip" aria-hidden="true"/>
        <h2>Investigator</h2>
        <dl className="vitals">
          <div className="vital hp"><dt><abbr title="Hit points">HP</abbr></dt><dd>{game?.state.hp ?? '—'}<span className="vital-rule" aria-hidden="true"/></dd></div>
          <div className="vital san"><dt><abbr title="Sanity">SAN</abbr></dt><dd>{game?.state.san ?? '—'}<span className="vital-rule" aria-hidden="true"/></dd></div>
        </dl>
        <section className="dossier-section"><h3><Mark type="location"/>Location</h3><p className="location-name">{game?.state.location_name || (game ? 'Not recorded' : 'No case open')}</p></section>
        <section className="dossier-section"><h3><Mark type="book"/>Discovered clues</h3>
          {clues.length ? <ul className="clue-list">{clues.map((label,i)=><li key={i}>{label}</li>)}</ul> : <p className="empty-note">None</p>}
        </section>
        {game?.state.push_available && <p className="mechanical-note">Pending push · opportunity recorded</p>}
        {briefing && <section className="dossier-section case-notes"><h3><Mark type="notes"/>Case notes</h3>
          <details><summary>Opening briefing</summary><p>{briefing}</p></details>
        </section>}
        {game && <details className="session-metadata"><summary>Session reference</summary><p className="session-id">{game.session_id}</p><p>Last saved: {savedTime(game.updated_at)}</p></details>}
      </aside>
    </div>
    <form className="action-composer" onSubmit={onSend} aria-label="Player action">
      <label htmlFor="action" className="visually-hidden">Your action</label>
      <textarea id="action" value={message} placeholder="What do you do?" maxLength={10000} onChange={e=>onMessageChange(e.target.value)} disabled={!game || busy}/>
      <button className="send-action" disabled={!game || busy || !message.trim()}>{busy ? 'Waiting…' : 'Send'}</button>
    </form>
  </div>;
}
