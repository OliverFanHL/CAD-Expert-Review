"""Transactional storage across local processes and serverless instances."""
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .io import object_hash


class Store:
    def __init__(self, database_url=None, sqlite_path=None):
        self.database_url = database_url
        self.sqlite_path = Path(sqlite_path) if sqlite_path else None
        if not database_url:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS expert_reviews (reviewer_key TEXT PRIMARY KEY, state TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        if self.database_url:
            import psycopg
            with psycopg.connect(self.database_url, connect_timeout=10) as db:
                yield db
        else:
            with closing(sqlite3.connect(self.sqlite_path, timeout=30)) as db:
                with db:
                    yield db

    def load(self, reviewer):
        marker = '%s' if self.database_url else '?'
        with self.connection() as db:
            row = db.execute(f'SELECT state FROM expert_reviews WHERE reviewer_key = {marker}', (object_hash(reviewer),)).fetchone()
        return json.loads(row[0]) if row else None

    def progress_rows(self):
        """Read-only: (reviewer_key, binding, judgment keys) for every stored reviewer.

        Only keys are returned, never decisions or notes. PostgreSQL extracts them
        server side so full review states are not transferred for progress polling.
        """
        with self.connection() as db:
            if self.database_url:
                rows = db.execute(
                    "SELECT reviewer_key, (state::json->'binding')::text, "
                    "COALESCE((SELECT json_agg(k) FROM json_object_keys("
                    "COALESCE(state::json->'judgments', '{}'::json)) AS k), '[]'::json)::text "
                    'FROM expert_reviews').fetchall()
                return [(key, json.loads(binding), json.loads(keys)) for key, binding, keys in rows]
            rows = db.execute('SELECT reviewer_key, state FROM expert_reviews').fetchall()
        result = []
        for key, text in rows:
            state = json.loads(text)
            result.append((key, state.get('binding'), list(state.get('judgments') or {})))
        return result

    def dump(self):
        """Read-only snapshot of every stored row, exactly as serialized."""
        with self.connection() as db:
            return db.execute('SELECT reviewer_key, state FROM expert_reviews ORDER BY reviewer_key').fetchall()

    def update(self, reviewer, change):
        key = object_hash(reviewer)
        marker = '%s' if self.database_url else '?'
        with self.connection() as db:
            if self.database_url:
                # Includes first-save races; locks are shared across all function instances.
                lock = int.from_bytes(bytes.fromhex(key[:16]), 'big', signed=True)
                db.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
            else:
                db.execute('BEGIN IMMEDIATE')
            row = db.execute(f'SELECT state FROM expert_reviews WHERE reviewer_key = {marker}', (key,)).fetchone()
            state = change(json.loads(row[0]) if row else None)
            serialized = json.dumps(state, allow_nan=False)
            db.execute(f'INSERT INTO expert_reviews (reviewer_key, state) VALUES ({marker}, {marker}) '
                       'ON CONFLICT (reviewer_key) DO UPDATE SET state = excluded.state', (key, serialized))
            return state
