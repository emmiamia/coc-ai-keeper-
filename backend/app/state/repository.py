from uuid import uuid4
from app.db.sqlite import connect
from app.models.game import Session, Message, GameState, now

class GameStateRepository:
    def __init__(self, path):
        self.path = path
        with connect(path):
            pass

    def create(self, scenario_id, starting_state: GameState | None = None):
        session = Session(session_id=str(uuid4()), scenario_id=scenario_id,
                          state=starting_state.model_copy(deep=True) if starting_state is not None else GameState())
        with connect(self.path) as db:
            db.execute('INSERT INTO sessions VALUES (?, ?)', (session.session_id, session.model_dump_json()))
        return session

    def get(self, session_id):
        with connect(self.path) as db:
            row = db.execute('SELECT document FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return Session.model_validate_json(row[0])

    def append_turn(self, session_id, player, keeper):
        # Read and write in one transaction; concurrent turns cannot overwrite each other.
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            session = Session.model_validate_json(row[0])
            session.messages.extend([Message(role='player', content=player), Message(role='keeper', content=keeper)])
            session.updated_at = now()
            session.event_log.append({'type': 'placeholder_turn_completed', 'timestamp': session.updated_at})
            db.execute('UPDATE sessions SET document=? WHERE session_id=?', (session.model_dump_json(), session_id))
        return session

    def update_state(self, session_id, transition):
        """Trusted internal transition; never an unrestricted player HTTP update."""
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            session = Session.model_validate_json(row[0])
            state = session.state.model_copy(deep=True)
            transition(state)
            session.state = GameState.model_validate(state.model_dump())
            session.updated_at = now()
            session.event_log.append({'type': 'state_transition', 'timestamp': session.updated_at})
            db.execute('UPDATE sessions SET document=? WHERE session_id=?', (session.model_dump_json(), session_id))
        return session

    def record_clue_discovery(self, session_id, clue_id, scenarios):
        # Call only after explicit discovery resolution. This method neither
        # rolls checks nor infers discovery from text/location membership.
        scenario_id = self.get(session_id).scenario_id
        scenarios.get_clue(scenario_id, clue_id)
        def discover(state):
            if clue_id not in state.discovered_clues:
                state.discovered_clues.append(clue_id)
        return self.update_state(session_id, discover)
