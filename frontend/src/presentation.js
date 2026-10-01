import {requestStatus} from './sessionClient.js';

export function clueLabels(state) {
  return (state?.discovered_clues ?? []).map(id => {
    const label = state?.clue_names?.[id];
    // No guesses from IDs, no whole-map rendering, no hidden clue enumeration.
    return typeof label === 'string' && label.trim() ? label : 'Discovered evidence';
  });
}

export function displayStatus({busy, feedback, game}) {
  const status = requestStatus({busy, feedback, game});
  if (busy) return 'Keeper working…';
  if (feedback) return status;
  if (game?.turn_outcome === 'clarification') return 'Keeper clarification · Saved';
  return game ? (game.status === 'completed' ? 'Case completed · Saved' : 'Saved') : 'No case open';
}

export function savedTime(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return 'Not recorded';
  return new Intl.DateTimeFormat(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}).format(new Date(value));
}
