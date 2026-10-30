"""Regression coverage for the amendment-history schema repair."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


PREVIOUS_HEAD = "e8c3a1f75d24"


def test_amendment_created_at_is_added_and_backfilled(tmp_path):
    database = tmp_path / "amendment-created-at.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(operation: str, target: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", operation, target],
            cwd=backend,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    migrate("upgrade", PREVIOUS_HEAD)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_cost_amendments)")}
        assert "created_at" not in columns
        connection.execute(
            "INSERT INTO daily_cost_amendments "
            "(id, organization_id, entry_id, well_id, afe_id, amendment_number, cost_date, "
            "days_after_cost_date, reason, reopened_by, reopened_at) "
            "VALUES ('amendment', 'org', 'entry', 'well', 'afe', 1, '2026-10-01', "
            "29, 'Correction', 'Owner', '2026-10-30 12:34:56')"
        )

    migrate("upgrade", "head")
    with sqlite3.connect(database) as connection:
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(daily_cost_amendments)")}
        assert columns["created_at"][3] == 1  # NOT NULL
        assert connection.execute(
            "SELECT created_at = reopened_at FROM daily_cost_amendments WHERE id = 'amendment'"
        ).fetchone() == (1,)

    migrate("downgrade", PREVIOUS_HEAD)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_cost_amendments)")}
        assert "created_at" not in columns
        assert connection.execute(
            "SELECT reopened_at FROM daily_cost_amendments WHERE id = 'amendment'"
        ).fetchone() == ("2026-10-30 12:34:56",)
