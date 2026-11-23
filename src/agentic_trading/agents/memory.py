"""3-layer memory architecture: ephemeral WorkingState, append-only DecisionLog, and read-only HumanLessonsStore."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_trading.agents.envelope import canonicalize


@dataclass
class WorkingState:
    """Ephemeral scratchpad owned exclusively by TradingDeskOrchestrator for one cycle."""

    run_id: str
    as_of: datetime
    watchlist: list[str] = field(default_factory=list)
    analyst_envelopes: dict[tuple[str, str], Any] = field(default_factory=dict)
    shortlist: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)
    proposals: list[Any] = field(default_factory=list)
    decisions: list[Any] = field(default_factory=list)
    orders: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionRecord:
    """Immutable audit record sealing all agent evaluations, decisions, and orders."""

    run_id: str
    timestamp: datetime
    ticker: str
    inputs_hash: str
    analyst_envelopes: Mapping[str, Any]
    shortlist_rank: int | None
    strategist_proposal: Mapping[str, Any] | None
    risk_decision: Mapping[str, Any] | None
    paper_order: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be a timezone-aware datetime")


class DecisionLog:
    """Append-only audit log with optional SQLite persistence."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._records: list[DecisionRecord] = []
        self._db_path = Path(db_path) if db_path else None
        if self._db_path:
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decision_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        inputs_hash TEXT NOT NULL,
                        shortlist_rank INTEGER,
                        record_json TEXT NOT NULL
                    )
                    """
                )
        finally:
            conn.close()

    def append(self, record: DecisionRecord) -> None:
        if not isinstance(record, DecisionRecord):
            raise TypeError("record must be a DecisionRecord instance")
        self._records.append(record)
        if self._db_path:
            serialized = json.dumps(
                {
                    "run_id": record.run_id,
                    "timestamp": record.timestamp.isoformat(),
                    "ticker": record.ticker,
                    "inputs_hash": record.inputs_hash,
                    "analyst_envelopes": canonicalize(record.analyst_envelopes),
                    "shortlist_rank": record.shortlist_rank,
                    "strategist_proposal": canonicalize(record.strategist_proposal),
                    "risk_decision": canonicalize(record.risk_decision),
                    "paper_order": canonicalize(record.paper_order),
                },
                sort_keys=True,
            )
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO decision_records
                        (run_id, timestamp, ticker, inputs_hash, shortlist_rank, record_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.run_id,
                            record.timestamp.isoformat(),
                            record.ticker,
                            record.inputs_hash,
                            record.shortlist_rank,
                            serialized,
                        ),
                    )
            finally:
                conn.close()

    def get_records(self, run_id: str | None = None) -> tuple[DecisionRecord, ...]:
        if self._db_path and self._db_path.exists():
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    if run_id is None:
                        cursor = conn.execute("SELECT record_json FROM decision_records ORDER BY id ASC")
                    else:
                        cursor = conn.execute(
                            "SELECT record_json FROM decision_records WHERE run_id = ? ORDER BY id ASC",
                            (run_id,),
                        )
                    results: list[DecisionRecord] = []
                    for (raw_json,) in cursor.fetchall():
                        data = json.loads(raw_json)
                        results.append(
                            DecisionRecord(
                                run_id=data["run_id"],
                                timestamp=datetime.fromisoformat(data["timestamp"]),
                                ticker=data["ticker"],
                                inputs_hash=data["inputs_hash"],
                                analyst_envelopes=data["analyst_envelopes"],
                                shortlist_rank=data["shortlist_rank"],
                                strategist_proposal=data["strategist_proposal"],
                                risk_decision=data["risk_decision"],
                                paper_order=data["paper_order"],
                            )
                        )
                    return tuple(results)
            finally:
                conn.close()
        if run_id is None:
            return tuple(self._records)
        return tuple(r for r in self._records if r.run_id == run_id)


class HumanLessonsStore:
    """Read-only store for human-curated trading heuristics and lessons."""

    def __init__(self, lessons: tuple[str, ...] = ()) -> None:
        self._lessons = tuple(str(x).strip() for x in lessons if str(x).strip())

    @classmethod
    def from_file(cls, path: Path | str) -> HumanLessonsStore:
        p = Path(path)
        if not p.exists():
            return cls(())
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return cls(())
        if content.startswith("["):
            try:
                items = json.loads(content)
                if isinstance(items, list):
                    return cls(tuple(str(x) for x in items))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return cls(tuple(lines))

    def load_lessons(self) -> tuple[str, ...]:
        return self._lessons
