import sqlite3
import os
import datetime
from datetime import timezone
from typing import List, Tuple
from constants import *
STATE_DB_PATH = os.environ.get("SCAN_STATE_DB", "/app/state.db")


def is_allowed_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if not ext:
        return False
    return ext in ALLOWED_EXT

def list_files(folder: str) -> List[str]:
    out: List[str] = []
    for base, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(base, f)
            if is_allowed_file(p):
                out.append(p)
    return out

def ensure_state_db(db_path: str = STATE_DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ingested_paths (
          index_name TEXT NOT NULL,
          relpath TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          PRIMARY KEY(index_name, relpath)
        )
        """)
        conn.commit()
    finally:
        conn.close()

def select_new_files(index_name: str, folder: str, db_path: str = STATE_DB_PATH) -> List[str]:
    ensure_state_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        files = list_files(folder)
        if not files:
            return []

        candidates: List[Dict[str, Any]] = []
        relpaths: List[str] = []
        for ap in files:
            candidates.append({"relpath": ap})
            relpaths.append(ap)

        existing = set()
        CHUNK = 800
        for i in range(0, len(relpaths), CHUNK):
            batch = relpaths[i:i+CHUNK]
            q_marks = ",".join(["?"] * len(batch))
            rows = conn.execute(
                f"SELECT relpath FROM ingested_paths WHERE index_name=? AND relpath IN ({q_marks})",
                [index_name, *batch],
            ).fetchall()
            for (rp,) in rows:
                existing.add(rp)

        return [c["relpath"] for c in candidates if c["relpath"] not in existing]
    finally:
        conn.close()


def mark_ingested(index_name: str, recs: List[str], db_path: str = STATE_DB_PATH) -> None:
    print("mark ingested with: ", recs)
    if not recs:
        return
    ensure_state_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """
            INSERT OR IGNORE INTO ingested_paths(index_name, relpath, ingested_at)
            VALUES (?, ?, ?)
            """,
            [(index_name, r, now) for r in recs],
        )
        conn.commit()
    finally:
        conn.close()