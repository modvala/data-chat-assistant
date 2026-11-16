"""The `ReportStore` port on SQLite: Saved Reports and the Customer IDs that they mention (HLD 11)."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dca.core.ports import ReportFilter, SavedReport

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
