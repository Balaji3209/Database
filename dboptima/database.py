"""SQLite persistence layer (schema creation, data load, human decision audit)."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DB_PATH, SCHEMA_PATH, get_logger

log = get_logger("database")

EVIDENCE_TABLES = ["applications", "database_instances", "dependencies", "feature_usage", "license_entitlements",
                   "workload_metrics", "recovery_requirements", "cost_records"]


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(db_path: Path = DB_PATH) -> None:
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def _replace(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.execute(f"DELETE FROM {table}")
    df[[c for c in cols if c in df.columns]].to_sql(table, conn, if_exists="append", index=False)


def load_evidence(frames: dict[str, pd.DataFrame], db_path: Path = DB_PATH) -> None:
    init_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in EVIDENCE_TABLES:
            _replace(conn, t, frames[t])
        conn.commit()
    log.info("Loaded evidence tables into %s", db_path)


def save_recommendations(recs: pd.DataFrame, evidence: pd.DataFrame, db_path: Path = DB_PATH) -> None:
    init_schema(db_path)
    recs = recs.copy()
    recs["generated_at"] = datetime.now().isoformat(timespec="seconds")
    with closing(connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        _replace(conn, "recommendation_evidence", evidence)
        _replace(conn, "recommendations", recs)
        conn.commit()


def record_decision(recommendation_id: str, instance_id: str, decision: str, decided_action: str,
                    decided_by: str, role: str, comment: str, db_path: Path = DB_PATH) -> None:
    if not decided_by.strip():
        raise ValueError("A named human decision-maker is required")
    init_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.execute("INSERT INTO decision_audit (recommendation_id, instance_id, decision, decided_action, decided_by, role, "
                     "comment, decided_at) VALUES (?,?,?,?,?,?,?,?)",
                     (recommendation_id, instance_id, decision, decided_action, decided_by.strip(), role, comment,
                      datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    log.info("Human decision recorded: %s %s by %s (%s)", recommendation_id, decision, decided_by, role)


def decision_log(db_path: Path = DB_PATH) -> pd.DataFrame:
    init_schema(db_path)
    with closing(connect(db_path)) as conn:
        return pd.read_sql("SELECT * FROM decision_audit ORDER BY audit_id DESC", conn)


def latest_decisions(db_path: Path = DB_PATH) -> pd.DataFrame:
    log_df = decision_log(db_path)
    if log_df.empty:
        return log_df
    return log_df.sort_values("audit_id").drop_duplicates("recommendation_id", keep="last")
