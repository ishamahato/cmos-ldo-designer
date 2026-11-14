"""SQLite experiment metadata store (experiments/experiments.db)."""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from circuits.design_params import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "experiments" / "experiments.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    kind TEXT NOT NULL,          -- baseline | sweep | optimizer | pvt | montecarlo | dashboard
    tag TEXT,
    design_json TEXT NOT NULL,
    conditions_json TEXT,
    metrics_json TEXT,
    status TEXT NOT NULL,        -- ok | failed
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_kind ON experiments(kind);
"""


def _clean(obj: Any) -> Any:
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar
        return _clean(obj.item())
    return obj


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    return con


def log_experiment(kind: str, design: dict, metrics: dict | None, conditions: dict | None = None,
                   status: str = "ok", message: str = "", tag: str = "", path: Path = DB_PATH) -> int:
    with connect(path) as con:
        cur = con.execute(
            "INSERT INTO experiments(created, kind, tag, design_json, conditions_json, metrics_json, status, message)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), kind, tag, json.dumps(_clean(design)), json.dumps(_clean(conditions or {})),
             json.dumps(_clean(metrics or {})), status, message[:2000]))
        return int(cur.lastrowid)


def load_experiments(kind: str | None = None, path: Path = DB_PATH):
    import pandas as pd
    with connect(path) as con:
        q = "SELECT * FROM experiments" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return pd.read_sql_query(q, con, params=(kind,) if kind else ())
