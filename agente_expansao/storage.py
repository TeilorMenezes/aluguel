"""Persistência exclusiva do Agente de Expansão."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Repository:
    def __init__(self, path: str | Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL UNIQUE,
                    name TEXT,
                    state TEXT,
                    region TEXT,
                    city TEXT,
                    official_url TEXT NOT NULL,
                    rental_url TEXT,
                    discovery_score REAL DEFAULT 0,
                    confidence REAL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pendente',
                    platform TEXT,
                    selectors_json TEXT NOT NULL DEFAULT '{}',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL,
                    platform TEXT,
                    selectors_json TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER,
                    level TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );
                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    branch TEXT,
                    pull_request_url TEXT,
                    candidate_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def log(
        self,
        action: str,
        message: str,
        *,
        candidate_id: int | None = None,
        level: str = "info",
        details: dict | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO events
                   (candidate_id, level, action, message, details_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    level,
                    action,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                    _agora(),
                ),
            )

    def upsert_candidate(self, item: dict[str, Any]) -> int:
        now = _agora()
        domain = item["domain"].lower().removeprefix("www.")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO candidates (
                    domain, name, state, region, city, official_url, rental_url,
                    discovery_score, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    name=COALESCE(NULLIF(excluded.name, ''), candidates.name),
                    state=COALESCE(NULLIF(excluded.state, ''), candidates.state),
                    region=COALESCE(NULLIF(excluded.region, ''), candidates.region),
                    city=COALESCE(NULLIF(excluded.city, ''), candidates.city),
                    official_url=excluded.official_url,
                    rental_url=COALESCE(NULLIF(excluded.rental_url, ''), candidates.rental_url),
                    discovery_score=MAX(excluded.discovery_score, candidates.discovery_score),
                    updated_at=excluded.updated_at
                """,
                (
                    domain,
                    item.get("name", ""),
                    item.get("state", ""),
                    item.get("region", ""),
                    item.get("city", ""),
                    item["official_url"],
                    item.get("rental_url", ""),
                    float(item.get("discovery_score", 0)),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM candidates WHERE domain = ?", (domain,)
            ).fetchone()
        candidate_id = int(row["id"])
        self.log("descoberta", f"Candidato registrado: {domain}", candidate_id=candidate_id)
        return candidate_id

    def get_candidate(self, candidate_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        return self._candidate(row) if row else None

    def list_candidates(self, statuses: Iterable[str] | None = None) -> list[dict]:
        query = "SELECT * FROM candidates"
        params: list[Any] = []
        if statuses:
            statuses = list(statuses)
            query += f" WHERE status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._candidate(row) for row in rows]

    @staticmethod
    def _candidate(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["selectors"] = json.loads(item.pop("selectors_json") or "{}")
        item["validation"] = json.loads(item.pop("validation_json") or "{}")
        return item

    def save_inspection(self, candidate_id: int, result: dict, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE candidates SET
                    rental_url=COALESCE(NULLIF(?, ''), rental_url),
                    confidence=?, status=?, platform=?,
                    selectors_json=?, validation_json=?, last_error=?, updated_at=?
                WHERE id=?
                """,
                (
                    result.get("url", ""),
                    float(result.get("confidence", 0)),
                    status,
                    result.get("platform", "desconhecida"),
                    json.dumps(result.get("selectors", {}), ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    result.get("error"),
                    _agora(),
                    candidate_id,
                ),
            )
        level = "error" if result.get("error") else "info"
        self.log(
            "inspecao",
            result.get("error") or f"Inspeção concluída com confiança {result.get('confidence', 0):.0%}.",
            candidate_id=candidate_id,
            level=level,
            details=result,
        )

    def set_status(self, candidate_id: int, status: str, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE candidates SET status=?, updated_at=? WHERE id=?",
                (status, _agora(), candidate_id),
            )
        self.log("revisao", message, candidate_id=candidate_id)

    def save_correction(
        self, candidate_id: int, platform: str, selectors: dict, note: str = ""
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO corrections
                   (candidate_id, platform, selectors_json, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    platform,
                    json.dumps(selectors, ensure_ascii=False),
                    note,
                    _agora(),
                ),
            )
        self.log(
            "aprendizado",
            f"Correção salva para a plataforma {platform or 'desconhecida'}.",
            candidate_id=candidate_id,
            details={"selectors": selectors, "note": note},
        )

    def latest_correction(self, platform: str) -> dict | None:
        if not platform:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """SELECT selectors_json FROM corrections
                   WHERE platform=? ORDER BY id DESC LIMIT 1""",
                (platform,),
            ).fetchone()
        return json.loads(row["selectors_json"]) if row else None

    def list_events(self, limit: int = 250) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT events.*, candidates.domain
                   FROM events LEFT JOIN candidates ON candidates.id=events.candidate_id
                   ORDER BY events.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_publication(
        self, candidate_ids: list[int], status: str, message: str,
        branch: str = "", pull_request_url: str = ""
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO publications
                   (branch, pull_request_url, candidate_ids_json, status, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    branch,
                    pull_request_url,
                    json.dumps(candidate_ids),
                    status,
                    message,
                    _agora(),
                ),
            )
