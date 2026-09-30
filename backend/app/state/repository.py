from uuid import uuid4
from app.db.sqlite import connect
from app.models.game import Session, Message, now

class GameStateRepository:
    def __init__(self, path):
        self.path = path
        with connect(path):
            pass

    def create(self, scenario_id):
        session = Session(session_id=str(uuid4()), scenario_id=scenario_id)
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
