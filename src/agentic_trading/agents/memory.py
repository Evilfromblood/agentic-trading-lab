"""3-layer memory architecture: ephemeral WorkingState, append-only DecisionLog, and read-only HumanLessonsStore."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        self._cycle_runs: list[dict[str, Any]] = []
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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cycle_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL UNIQUE,
                        timestamp TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        watchlist_json TEXT NOT NULL,
                        feed_source TEXT NOT NULL,
                        llm_backend TEXT NOT NULL,
                        ollama_model TEXT NOT NULL,
                        shortlist_json TEXT NOT NULL,
                        dropped_json TEXT NOT NULL,
                        approved_orders_json TEXT NOT NULL,
                        rejected_proposals_json TEXT NOT NULL,
                        chat_trace_json TEXT NOT NULL,
                        report_markdown TEXT NOT NULL,
                        reconciled INTEGER NOT NULL,
                        auto_buy INTEGER DEFAULT 1,
                        trade_plans_json TEXT DEFAULT '[]',
                        candle_series_json TEXT DEFAULT '{}'
                    )
                    """
                )
                for col, col_def in [
                    ("auto_buy", "INTEGER DEFAULT 1"),
                    ("trade_plans_json", "TEXT DEFAULT '[]'"),
                    ("candle_series_json", "TEXT DEFAULT '{}'"),
                ]:
                    try:
                        conn.execute(f"ALTER TABLE cycle_runs ADD COLUMN {col} {col_def}")
                    except sqlite3.OperationalError:
                        pass
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

    def save_cycle_run(self, data: Mapping[str, Any]) -> None:
        record = dict(data)
        self._cycle_runs.append(record)
        if self._db_path:
            ts = (
                data["timestamp"]
                if isinstance(data["timestamp"], str)
                else data["timestamp"].isoformat()
            )
            reconciled_val = 1 if data.get("reconciled", True) else 0
            auto_buy_val = 1 if data.get("auto_buy", True) else 0
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO cycle_runs
                        (run_id, timestamp, currency, watchlist_json, feed_source, llm_backend, ollama_model, shortlist_json, dropped_json, approved_orders_json, rejected_proposals_json, chat_trace_json, report_markdown, reconciled, auto_buy, trade_plans_json, candle_series_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            data["run_id"],
                            ts,
                            data["currency"],
                            json.dumps(data["watchlist"], sort_keys=True),
                            data["feed_source"],
                            data["llm_backend"],
                            data["ollama_model"],
                            json.dumps(data["shortlist"], sort_keys=True),
                            json.dumps(data["dropped"], sort_keys=True),
                            json.dumps(data["approved_orders"], sort_keys=True),
                            json.dumps(data["rejected_proposals"], sort_keys=True),
                            json.dumps(data["chat_trace"], sort_keys=True),
                            data["report_markdown"],
                            reconciled_val,
                            auto_buy_val,
                            json.dumps(data.get("trade_plans", []), sort_keys=True),
                            json.dumps(data.get("candle_series", {}), sort_keys=True),
                        ),
                    )
            finally:
                conn.close()

    def list_cycle_runs(self, limit: int = 25) -> tuple[dict[str, Any], ...]:
        if self._db_path and self._db_path.exists():
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        SELECT run_id, timestamp, currency, watchlist_json, feed_source, llm_backend, ollama_model, approved_orders_json, rejected_proposals_json, reconciled, auto_buy
                        FROM cycle_runs ORDER BY id DESC LIMIT ?
                        """,
                        (limit,),
                    )
                    summaries: list[dict[str, Any]] = []
                    for row in cursor.fetchall():
                        (
                            run_id,
                            ts,
                            curr,
                            wl_json,
                            feed_src,
                            llm_be,
                            o_mod,
                            ord_json,
                            rej_json,
                            rec,
                            auto_buy_val,
                        ) = row
                        approved_orders = json.loads(ord_json)
                        rejected_proposals = json.loads(rej_json)
                        summaries.append(
                            {
                                "run_id": run_id,
                                "timestamp": ts,
                                "currency": curr,
                                "watchlist": json.loads(wl_json),
                                "feed_source": feed_src,
                                "llm_backend": llm_be,
                                "ollama_model": o_mod,
                                "approved_count": len(approved_orders),
                                "rejected_count": len(rejected_proposals),
                                "reconciled": bool(rec),
                                "auto_buy": bool(auto_buy_val) if auto_buy_val is not None else True,
                            }
                        )
                    return tuple(summaries)
            finally:
                conn.close()

        summaries_mem: list[dict[str, Any]] = []
        for c in self._cycle_runs[-limit:][::-1]:
            ts = (
                c["timestamp"]
                if isinstance(c["timestamp"], str)
                else c["timestamp"].isoformat()
            )
            summaries_mem.append(
                {
                    "run_id": c["run_id"],
                    "timestamp": ts,
                    "currency": c["currency"],
                    "watchlist": list(c["watchlist"]),
                    "feed_source": c["feed_source"],
                    "llm_backend": c["llm_backend"],
                    "ollama_model": c["ollama_model"],
                    "approved_count": len(c["approved_orders"]),
                    "rejected_count": len(c["rejected_proposals"]),
                    "reconciled": bool(c.get("reconciled", True)),
                    "auto_buy": bool(c.get("auto_buy", True)),
                }
            )
        return tuple(summaries_mem)

    def get_cycle_run(self, run_id: str) -> dict[str, Any] | None:
        if self._db_path and self._db_path.exists():
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        SELECT run_id, timestamp, currency, watchlist_json, feed_source, llm_backend, ollama_model, shortlist_json, dropped_json, approved_orders_json, rejected_proposals_json, chat_trace_json, report_markdown, reconciled, auto_buy, trade_plans_json, candle_series_json
                        FROM cycle_runs WHERE run_id = ?
                        """,
                        (run_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "run_id": row[0],
                        "timestamp": row[1],
                        "currency": row[2],
                        "watchlist": json.loads(row[3]),
                        "feed_source": row[4],
                        "llm_backend": row[5],
                        "ollama_model": row[6],
                        "shortlist": json.loads(row[7]),
                        "dropped": json.loads(row[8]),
                        "approved_orders": json.loads(row[9]),
                        "rejected_proposals": json.loads(row[10]),
                        "chat_trace": json.loads(row[11]),
                        "report_markdown": row[12],
                        "reconciled": bool(row[13]),
                        "auto_buy": bool(row[14]) if len(row) > 14 and row[14] is not None else True,
                        "trade_plans": json.loads(row[15]) if len(row) > 15 and row[15] else [],
                        "candle_series": json.loads(row[16]) if len(row) > 16 and row[16] else {},
                    }
            finally:
                conn.close()

        for c in reversed(self._cycle_runs):
            if c["run_id"] == run_id:
                item = dict(c)
                if not isinstance(item["timestamp"], str):
                    item["timestamp"] = item["timestamp"].isoformat()
                item.setdefault("auto_buy", True)
                item.setdefault("trade_plans", [])
                item.setdefault("candle_series", {})
                return item
        return None


class HumanLessonsStore:
    """Store for human-curated trading heuristics and lessons with SQLite persistence."""

    def __init__(
        self,
        lessons: tuple[str, ...] = (),
        db_path: Path | str | None = None,
    ) -> None:
        self._memory_lessons: list[str] = [str(x).strip() for x in lessons if str(x).strip()]
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
                    CREATE TABLE IF NOT EXISTS lessons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lesson TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
        finally:
            conn.close()

    @classmethod
    def from_file(cls, path: Path | str, db_path: Path | str | None = None) -> HumanLessonsStore:
        p = Path(path)
        if not p.exists():
            return cls((), db_path=db_path)
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return cls((), db_path=db_path)
        if content.startswith("["):
            try:
                items = json.loads(content)
                if isinstance(items, list):
                    return cls(tuple(str(x) for x in items), db_path=db_path)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return cls(tuple(lines), db_path=db_path)

    def add_lesson(self, lesson: str) -> str:
        clean = " ".join(lesson.strip().split())
        clean = "".join(ch for ch in clean if ord(ch) >= 32 or ch in "\n\t")
        if not clean:
            raise ValueError("lesson cannot be empty")
        if len(clean) > 240:
            raise ValueError("lesson exceeds 240 characters")
        if self._db_path:
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO lessons (lesson, created_at) VALUES (?, ?)",
                        (clean, datetime.now(timezone.utc).isoformat()),
                    )
            finally:
                conn.close()
        else:
            self._memory_lessons.append(clean)
        return clean

    def load_lessons(self) -> tuple[str, ...]:
        if self._db_path:
            conn = sqlite3.connect(self._db_path)
            try:
                with conn:
                    cursor = conn.execute("SELECT lesson FROM lessons ORDER BY id ASC")
                    db_items = [row[0] for row in cursor.fetchall()]
                    combined = list(self._memory_lessons) + db_items
                    return tuple(dict.fromkeys(combined))
            finally:
                conn.close()
        return tuple(self._memory_lessons)
