export class SessionRequestError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.turnStatus = detail?.status;
    this.turnId = detail?.turn_id;
  }
}

export function createSessionClient(fetcher = fetch) {
  let pending = false;
  return {
    get pending() { return pending; },
    async request(path, body) {
      if (pending) throw new Error('A request is already being processed.');
      pending = true;
      try {
        const response = await fetcher(path, body === undefined ? {} : {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
        });
        let payload;
        try { payload = await response.json(); }
        catch { throw new Error(`Request failed (${response.status}); retry will reuse the same turn ID.`); }
        if (!response.ok) {
          const detail = payload.detail;
          const message = typeof detail === 'string' ? detail : detail?.message;
          throw new SessionRequestError(typeof message === 'string' ? message : `Request failed (${response.status}).`, response.status, detail);
        }
        return payload;
      } finally { pending = false; }
    }
  };
}

export function getPendingTurn(storage, sessionId, message, makeId = () => crypto.randomUUID()) {
  const key = `coc-pending-${sessionId}`;
  let previous;
  try { previous = JSON.parse(storage.getItem(key)); } catch { previous = null; }
  if (previous?.message === message && typeof previous.turn_id === 'string') return previous;
  const turn = {message, turn_id: makeId()};
  storage.setItem(key, JSON.stringify(turn));
  return turn;
}


export function retirePendingTurn(storage, sessionId, turnId) {
  const key = `coc-pending-${sessionId}`;
  let pending;
  try { pending = JSON.parse(storage.getItem(key)); } catch { return; }
  if (pending?.turn_id === turnId) storage.removeItem(key);
}

export async function submitPlayerAction(client, storage, sessionId, message, makeId) {
  // Check before changing stored submission identity. A pending request owns it.
  if (client.pending) throw new Error('A request is already being processed.');
  const turn = getPendingTurn(storage, sessionId, message, makeId);
  try {
    const session = await client.request(`/api/game/${encodeURIComponent(sessionId)}/action`, turn);
    retirePendingTurn(storage, sessionId, turn.turn_id);
    return session;
  } catch (error) {
    // These explicit rejections are terminal and occur before mechanics.
    // Transport errors and 409/5xx retain identity: execution may be uncertain.
    if (error instanceof SessionRequestError && error.status === 400 &&
        ['clarification', 'unsupported'].includes(error.turnStatus) &&
        error.turnId === turn.turn_id) {
      retirePendingTurn(storage, sessionId, turn.turn_id);
    }
    throw error;
  }
}


export function requestFeedback(error) {
  if (error instanceof SessionRequestError && error.status === 400 &&
      ['clarification', 'unsupported'].includes(error.turnStatus)) {
    return {kind: 'gameplay', outcome: error.turnStatus, message: error.message};
  }
  return {kind: 'error', message: error.message};
}

export function requestStatus({busy, feedback, game}) {
  if (busy) return 'Keeper processing / loading…';
  if (feedback?.kind === 'error') return 'Request failed — last saved session shown';
  if (feedback?.kind === 'gameplay') {
    return feedback.outcome === 'unsupported' ? 'Unsupported action — last saved session shown' : 'Keeper clarification — last saved session shown';
  }
  if (game?.turn_outcome === 'clarification') return 'Saved · Keeper clarification';
  return game ? 'Saved · ' + game.status : 'No session';
}
