"""SQLite-backed application tracker."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {
    "Draft",
    "Applied",
    "Interview",
    "Rejected",
    "Offer",
    "Ready for review",
}

DEFAULT_DB_PATH = "data/tracker.db"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled."""
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the application tracker tables if they do not exist."""
    connection = _connect(db_path)

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                jd_url TEXT,
                resume_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft'
                    CHECK (
                        status IN (
                            'Draft',
                            'Applied',
                            'Interview',
                            'Rejected',
                            'Offer',
                            'Ready for review'
                        )
                    ),
                applied_at TIMESTAMP,
                follow_up_date DATE
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                recruiter_name TEXT,
                recruiter_email TEXT,
                email_sent_at TIMESTAMP,
                FOREIGN KEY (application_id)
                    REFERENCES applications (id)
                    ON DELETE CASCADE
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def log_application(
    company: str,
    role: str,
    jd_text: str,
    resume_version: str,
    jd_url: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Log a new application attempt and return its database ID."""
    init_db(db_path)
    connection = _connect(db_path)

    try:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                company,
                role,
                jd_text,
                jd_url,
                resume_version,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'Draft')
            """,
            (company, role, jd_text, jd_url, resume_version),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def update_status(
    application_id: int,
    new_status: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """Update an application's status after validating the new value."""
    if new_status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ValueError(
            f"Invalid status {new_status!r}. "
            f"Expected one of: {allowed}"
        )

    init_db(db_path)
    connection = _connect(db_path)

    try:
        cursor = connection.execute(
            """
            UPDATE applications
            SET status = ?,
                applied_at = CASE
                    WHEN ? = 'Applied' AND applied_at IS NULL
                    THEN CURRENT_TIMESTAMP
                    ELSE applied_at
                END
            WHERE id = ?
            """,
            (new_status, new_status, application_id),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                f"No application exists with id {application_id}."
            )

        connection.commit()
    finally:
        connection.close()


def list_applications(
    status_filter: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Return all applications, optionally filtered by status."""
    if status_filter is not None and status_filter not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ValueError(
            f"Invalid status filter {status_filter!r}. "
            f"Expected one of: {allowed}"
        )

    init_db(db_path)
    connection = _connect(db_path)

    try:
        if status_filter is None:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    company,
                    role,
                    jd_text,
                    jd_url,
                    resume_version,
                    status,
                    applied_at,
                    follow_up_date
                FROM applications
                ORDER BY id
                """
            )
        else:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    company,
                    role,
                    jd_text,
                    jd_url,
                    resume_version,
                    status,
                    applied_at,
                    follow_up_date
                FROM applications
                WHERE status = ?
                ORDER BY id
                """,
                (status_filter,),
            )

        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def add_contact(
    application_id: int,
    recruiter_name: str | None = None,
    recruiter_email: str | None = None,
    email_sent_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Log a recruiter contact against an existing application."""
    init_db(db_path)
    connection = _connect(db_path)

    try:
        application = connection.execute(
            "SELECT id FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

        if application is None:
            raise ValueError(
                f"No application exists with id {application_id}."
            )

        cursor = connection.execute(
            """
            INSERT INTO contacts (
                application_id,
                recruiter_name,
                recruiter_email,
                email_sent_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (application_id, recruiter_name, recruiter_email, email_sent_at),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()