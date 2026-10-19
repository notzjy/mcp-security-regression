from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .catalog import canonical, digest
from .models import Target


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("GUARDBENCH_DB", "data/guardbench.sqlite3")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS objects(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,role TEXT NOT NULL,tool TEXT NOT NULL,campaign_id TEXT,payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, kind: str, value: dict, immutable: bool = False) -> dict:
        with self.connect() as db:
            old = db.execute("SELECT payload FROM objects WHERE kind=? AND id=?", (kind, value["id"])).fetchone()
            if old and immutable:
                if json.loads(old[0]) != value:
                    raise ValueError(f"Immutable {kind} cannot be overwritten")
                return value
            db.execute("INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (kind, value["id"], canonical(value), now()))
        return value

    def get(self, kind: str, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM objects WHERE kind=? AND id=?", (kind, identity)).fetchone()
        if row is None:
            raise KeyError(f"Unknown {kind}: {identity}")
        value = json.loads(row[0])
        if kind == "suite":
            content = {k: value[k] for k in ("schema_version", "oracle_version", "cases")}
            if digest(content) != value["hash"]:
                raise ValueError("Suite integrity check failed")
        return value

    def list(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM objects WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def target(self, identity: str) -> Target:
        return Target.model_validate(self.get("target", identity))

    def audit(self, role: str, tool: str, campaign_id: str | None, payload: dict):
        # Arguments may include test data, but never Authorization values.
        with self.connect() as db:
            db.execute("INSERT INTO audit(created_at,role,tool,campaign_id,payload) VALUES(?,?,?,?,?)", (now(), role, tool, campaign_id, canonical(payload)))

    def audits(self, campaign_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if campaign_id:
                rows = db.execute("SELECT * FROM audit WHERE campaign_id=? ORDER BY seq", (campaign_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 500").fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
