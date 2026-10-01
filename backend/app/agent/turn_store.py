"""Durable turn journal and optimistic atomic session commits."""
import json
from app.db.sqlite import connect
from app.models.game import Session, GameState, Message, now

class TurnConflict(RuntimeError):
    pass

class TurnStore:
    def __init__(self, states):
        self.states = states
        with connect(states.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS keeper_turns (turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, message TEXT NOT NULL, baseline TEXT NOT NULL, status TEXT NOT NULL, payload TEXT, completed_session TEXT)")

    def begin(self, session_id, turn_id, message):
        with connect(self.states.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT session_id,message,baseline,status,payload,completed_session FROM keeper_turns WHERE turn_id=?',(turn_id,)).fetchone()
            if row:
                if row[0] != session_id or row[1] != message:
                    raise TurnConflict('Turn ID was reused for another action')
                return dict(baseline=row[2],status=row[3],payload=json.loads(row[4]) if row[4] else None,completed_session=row[5])
            if db.execute("SELECT 1 FROM keeper_turns WHERE session_id=? AND status IN ('pending','resolved')",(session_id,)).fetchone():
                raise TurnConflict('Another turn needs completion before a new action')
            row = db.execute('SELECT document FROM sessions WHERE session_id=?',(session_id,)).fetchone()
            if row is None: raise KeyError(session_id)
            db.execute("INSERT INTO keeper_turns VALUES (?,?,?,?,'pending',NULL,NULL)",(turn_id,session_id,message,row[0]))
            return dict(baseline=row[0],status='new',payload=None,completed_session=None)

    def record_resolution(self, turn_id, payload):
        with connect(self.states.path) as db:
            changed = db.execute("UPDATE keeper_turns SET status='resolved',payload=? WHERE turn_id=? AND status='pending'",(json.dumps(payload),turn_id)).rowcount
            if changed != 1: raise TurnConflict('Resolution already recorded')

    def fail(self, turn_id):
        with connect(self.states.path) as db:
            db.execute("UPDATE keeper_turns SET status='failed' WHERE turn_id=? AND status='pending'",(turn_id,))

    def complete(self, turn_id, narration):
        with connect(self.states.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT session_id,message,baseline,status,payload FROM keeper_turns WHERE turn_id=?',(turn_id,)).fetchone()
            if row is None or row[3] != 'resolved': raise TurnConflict('Turn is not ready to commit')
            current = db.execute('SELECT document FROM sessions WHERE session_id=?',(row[0],)).fetchone()
            if current is None or current[0] != row[2]: raise TurnConflict('Session changed; recorded resolution needs reconciliation')
            payload = json.loads(row[4])
            session = Session.model_validate_json(row[2])
            session.state = GameState.model_validate(payload['state'])
            session.messages.extend([Message(role='player',content=row[1]),Message(role='keeper',content=narration)])
            session.updated_at = now()
            session.event_log.append({'type':'keeper_turn_completed','turn_id':turn_id,'mechanics':payload['mechanics'],'outcome':payload.get('outcome','completed'),'timestamp':session.updated_at})
            document = session.model_dump_json()
            db.execute('UPDATE sessions SET document=? WHERE session_id=?',(document,row[0]))
            db.execute("UPDATE keeper_turns SET status='completed',completed_session=? WHERE turn_id=?",(document,turn_id))
            return session
