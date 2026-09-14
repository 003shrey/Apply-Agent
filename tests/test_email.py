"""Manual CLI test for cold-email generation and approval gating."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from email_gen import generate_cold_email
from emailer import GmailConfigurationError, review_and_send


def main() -> None:
    resume_path = PROJECT_ROOT / "data" / "resume.json"
    job_description_path = PROJECT_ROOT / "data" / "job_description.txt"

    with resume_path.open("r", encoding="utf-8") as file:
        resume_json = json.load(file)

    jd_text = job_description_path.read_text(encoding="utf-8")

    draft = generate_cold_email(jd_text, resume_json)

    print("\nGenerated draft:")
    print(f"Subject: {draft['subject']}")
    print("\nBody:")
    print(draft["body"])

    recipient = input("\nRecruiter email address: ").strip()
    if not recipient:
        print("No recipient entered. Skipping review.")
        return

    try:
        result = review_and_send(
            to_address=recipient,
            subject=draft["subject"],
            body=draft["body"],
            jd_text=jd_text,
            resume_json=resume_json,
        )
        print(f"\nResult: {result}")
    except GmailConfigurationError as exc:
        print(f"\nApproval gate completed, but Gmail is not configured: {exc}")
    except FileNotFoundError as exc:
        print(f"\nApproval gate completed, but a Gmail file is missing: {exc}")
    except Exception as exc:
        print(f"\nApproval gate completed, but Gmail failed: {exc}")


if __name__ == "__main__":
    main()