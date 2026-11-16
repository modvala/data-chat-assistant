"""The `ReportStore` port on SQLite: Saved Reports and the Customer IDs that they mention (HLD 11)."""

import json
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

from dca.core.ports import AuditEntry, DeleteBatch, ReportFilter, SavedReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    created_session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    sql TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    delete_batch_id TEXT
);
CREATE TABLE IF NOT EXISTS report_customers (
    report_id TEXT NOT NULL REFERENCES reports (report_id),
    customer_id TEXT NOT NULL,
    PRIMARY KEY (report_id, customer_id)
);
CREATE INDEX IF NOT EXISTS reports_owner ON reports (owner_id);
CREATE TABLE IF NOT EXISTS delete_batches (
    batch_id TEXT PRIMARY KEY,
    executive_id TEXT NOT NULL,
    report_ids TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    undo_until TEXT NOT NULL,
    restored INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id TEXT PRIMARY KEY,
    executive_id TEXT NOT NULL,
    action TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    report_ids TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


class SQLiteReportStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, report: SavedReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO reports (report_id, owner_id, created_session_id, title, body, sql, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report.report_id,
                    report.owner_id,
                    report.created_session_id,
                    report.title,
                    report.body,
                    json.dumps(report.sql),
                    report.created_at.isoformat(),
                ),
            )
            connection.executemany(
                "INSERT INTO report_customers (report_id, customer_id) VALUES (?, ?)",
                [(report.report_id, customer_id) for customer_id in sorted(set(report.customer_ids))],
            )

    def find(self, owner_id: str, report_filter: ReportFilter | None = None) -> list[SavedReport]:
        """The Saved Reports of one owner that are not deleted, oldest first. The owner filter is always on."""
        query = "SELECT * FROM reports WHERE owner_id = ? AND deleted_at IS NULL"
        params: list[str] = [owner_id]
        if report_filter and report_filter.created_session_id:
            query += " AND created_session_id = ?"
            params.append(report_filter.created_session_id)
        if report_filter and report_filter.customer_ids:
            marks = ", ".join("?" for _ in report_filter.customer_ids)
            query += f" AND report_id IN (SELECT report_id FROM report_customers WHERE customer_id IN ({marks}))"
            params.extend(report_filter.customer_ids)
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY created_at, report_id", params).fetchall()
            customers = {
                row["report_id"]: [
                    c["customer_id"]
                    for c in connection.execute(
                        "SELECT customer_id FROM report_customers WHERE report_id = ? ORDER BY customer_id",
                        (row["report_id"],),
                    )
                ]
                for row in rows
            }
        return [
            SavedReport(
                report_id=row["report_id"],
                owner_id=row["owner_id"],
                created_session_id=row["created_session_id"],
                title=row["title"],
                body=row["body"],
                sql=json.loads(row["sql"]),
                customer_ids=customers[row["report_id"]],
                created_at=datetime.fromisoformat(row["created_at"]),
                deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
                delete_batch_id=row["delete_batch_id"],
            )
            for row in rows
        ]

    def soft_delete(self, ids: Sequence[str], actor: str, undo_until: datetime, at: datetime) -> DeleteBatch:
        """Marks the own reports of `actor` as deleted, as one delete batch. Nothing is removed."""
        batch_id = uuid.uuid4().hex[:12]
        marks = ", ".join("?" for _ in ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE reports SET deleted_at = ?, delete_batch_id = ? "
                f"WHERE owner_id = ? AND deleted_at IS NULL AND report_id IN ({marks})",
                [at.isoformat(), batch_id, actor, *ids],
            )
            if cursor.rowcount != len(ids):
                connection.rollback()
                raise ValueError("The delete set changed or holds reports of another owner.")
            connection.execute(
                "INSERT INTO delete_batches (batch_id, executive_id, report_ids, deleted_at, undo_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (batch_id, actor, json.dumps(sorted(ids)), at.isoformat(), undo_until.isoformat()),
            )
        return DeleteBatch(batch_id, actor, tuple(sorted(ids)), at, undo_until)

    def last_batch(self, actor: str) -> DeleteBatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM delete_batches WHERE executive_id = ? ORDER BY deleted_at DESC LIMIT 1", (actor,)
            ).fetchone()
        if row is None:
            return None
        return DeleteBatch(
            batch_id=row["batch_id"],
            executive_id=row["executive_id"],
            report_ids=tuple(json.loads(row["report_ids"])),
            deleted_at=datetime.fromisoformat(row["deleted_at"]),
            undo_until=datetime.fromisoformat(row["undo_until"]),
            restored=bool(row["restored"]),
        )

    def audit(self, entry: AuditEntry) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_log (entry_id, executive_id, action, batch_id, report_ids, trace_id, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.entry_id or uuid.uuid4().hex[:12],
                    entry.executive_id,
                    entry.action,
                    entry.batch_id,
                    json.dumps(list(entry.report_ids)),
                    entry.trace_id,
                    entry.at.isoformat(),
                ),
            )

    def audit_entries(self, actor: str) -> Iterator[AuditEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log WHERE executive_id = ? ORDER BY at, entry_id", (actor,)
            ).fetchall()
        for row in rows:
            yield AuditEntry(
                executive_id=row["executive_id"],
                action=row["action"],
                batch_id=row["batch_id"],
                report_ids=tuple(json.loads(row["report_ids"])),
                trace_id=row["trace_id"],
                at=datetime.fromisoformat(row["at"]),
                entry_id=row["entry_id"],
            )
