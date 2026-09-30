import sqlite3
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        db.commit()
        with db:
            yield db
    finally:
        db.close()
