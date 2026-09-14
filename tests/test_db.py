"""CLI smoke test for the application tracker database."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow this script to run directly from the project root:
# python tests/test_db.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import (  # noqa: E402
    add_contact,
    init_db,
    list_applications,
    log_application,
    update_status,
)


def print_applications(applications: list[dict]) -> None:
    """Print applications in a readable table."""
    columns = [
        ("ID", "id"),
        ("Company", "company"),
        ("Role", "role"),
        ("Status", "status"),
        ("Resume", "resume_version"),
        ("JD URL", "jd_url"),
        ("Applied At", "applied_at"),
        ("Follow-Up", "follow_up_date"),
    ]

    rows = []
    for application in applications:
        rows.append(
            [
                str(application.get(key) or "")
                for _, key in columns
            ]
        )

    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, (header, _) in enumerate(columns)
    ]

    header = " | ".join(
        name.ljust(widths[index])
        for index, (name, _) in enumerate(columns)
    )
    separator = "-+-".join("-" * width for width in widths)

    print(header)
    print(separator)

    for row in rows:
        print(
            " | ".join(
                value.ljust(widths[index])
                for index, value in enumerate(row)
            )
        )


def main() -> None:
    """Run the database smoke test against a temporary SQLite file."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_path = Path(temporary_directory) / "tracker_test.db"

        init_db(db_path)

        first_id = log_application(
            company="Acme Technologies",
            role="Backend Python Engineer",
            jd_text="Build Python services and APIs.",
            resume_version="tailored_resume_acme_v1.docx",
            jd_url="https://example.com/jobs/acme-backend",
            db_path=db_path,
        )

        second_id = log_application(
            company="Northstar Labs",
            role="Software Engineer",
            jd_text="Develop reliable web applications.",
            resume_version="tailored_resume_northstar_v1.docx",
            db_path=db_path,
        )

        third_id = log_application(
            company="Summit Analytics",
            role="Data Platform Engineer",
            jd_text="Maintain data pipelines and platform tooling.",
            resume_version="tailored_resume_summit_v1.docx",
            db_path=db_path,
        )

        update_status(first_id, "Ready for review", db_path=db_path)

        contact_id = add_contact(
            application_id=first_id,
            recruiter_name="Jordan Lee",
            recruiter_email="jordan.lee@example.com",
            db_path=db_path,
        )

        applications = list_applications(db_path=db_path)

        print(f"Created applications: {first_id}, {second_id}, {third_id}")
        print(f"Created recruiter contact: {contact_id}")
        print()
        print_applications(applications)


if __name__ == "__main__":
    main()