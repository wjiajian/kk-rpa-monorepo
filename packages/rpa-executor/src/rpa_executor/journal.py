import json
from hashlib import sha256
import hmac
import sqlite3
from time import time


class Journal:
    """Requests and outgoing events are committed before sending or executing."""
    def __init__(self, path, credential_key=""):
        self.credential_key = credential_key.encode()
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, body TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS events(run_id TEXT, seq INTEGER, body TEXT, PRIMARY KEY(run_id,seq));
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, body TEXT);
        """)

    def state(self):
        row = self.db.execute("SELECT body FROM state WHERE key='active'").fetchone()
        return json.loads(row[0]) if row else {}

    def save_state(self, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES('active',?)", (json.dumps(value),))

    def accept(self, command):
        if "credentials" in command.get("params", {}):
            if not self.credential_key:
                raise ValueError("robot connection credential is required")
            # Keep duplicate/conflict detection without persisting business secrets.
            # The HMAC key remains in the robot's DPAPI-protected connection config.
            fingerprint = hmac.new(self.credential_key,
                json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), sha256).hexdigest()
            command = {**command, "params": {key: value for key, value in command["params"].items() if key != "credentials"},
                       "credential_fingerprint": fingerprint}
        encoded = json.dumps(command, sort_keys=True, separators=(",", ":"))
        old = self.db.execute("SELECT body,status FROM requests WHERE id=?", (command["request_id"],)).fetchone()
        if old:
            if old[0] != encoded:
                raise ValueError("request_id has different parameters")
            return False
        with self.db:
            self.db.execute("INSERT INTO requests VALUES(?,?,?)", (command["request_id"], encoded, "accepted"))
        return True

    def append(self, message):
        run = message["console_run_id"]
        with self.db:
            seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run,)).fetchone()[0]
            message = {"at": time(), **message, "seq": seq}
            self.db.execute("INSERT INTO events VALUES(?,?,?)", (run, seq, json.dumps(message)))
            if message["type"] == "result":
                self.db.execute("UPDATE requests SET status=? WHERE id=?", (message["status"], message["request_id"]))
        return message

    def events(self, run, after=0):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run, after))]

    def requests(self):
        return dict(self.db.execute("SELECT id,status FROM requests"))

    def interrupted(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM requests WHERE status IN ('accepted','running')")]
