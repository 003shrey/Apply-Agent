# src/emailer.py
"""Gmail sending and explicit draft-review flow."""

from datetime import datetime, timezone
import base64
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

try:
    from .db import add_contact
    from .email_gen import generate_email_revision
except ImportError:
    from db import add_contact
    from email_gen import generate_email_revision


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"


class GmailConfigurationError(RuntimeError):
    """Raised when Gmail OAuth files or configuration are unavailable."""


def _get_gmail_credentials() -> Credentials:
    if not CREDENTIALS_PATH.exists() and not TOKEN_PATH.exists():
        raise GmailConfigurationError(
            "Gmail is not configured: credentials.json and token.json are missing."
        )
    credentials = None
    if TOKEN_PATH.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        if not CREDENTIALS_PATH.exists():
            raise GmailConfigurationError(
                "credentials.json is required to authorize Gmail."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        credentials = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def send_email(to_address: str, subject: str, body: str) -> dict:
    if not to_address or not to_address.strip():
        raise ValueError("to_address is required.")
    credentials = _get_gmail_credentials()
    service = build("gmail", "v1", credentials=credentials)
    message = EmailMessage()
    message["To"] = to_address.strip()
    message["Subject"] = subject.strip()
    message.set_content(body)
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return (
        service.users().messages()
        .send(userId="me", body={"raw": encoded_message})
        .execute()
    )


def _prompt_for_edit(subject: str, body: str) -> tuple[str, str]:
    print("\nEnter the edited subject. Leave blank to keep the current subject.")
    edited_subject = input("Subject: ").strip() or subject
    print(
        "\nEnter the edited body. Finish by entering a line containing only "
    )
    first_line = input("Body: ")
    if not first_line.strip():
        return edited_subject, body
    lines = [first_line]
    while True:
        line = input()
        if line == ".END":
            break
        lines.append(line)
    edited_body = "\n".join(lines).strip()
    return edited_subject, edited_body or body


def review_and_send(
    to_address: str,
    subject: str,
    body: str,
    jd_text: str,
    resume_json: Dict[str, Any],
    application_id: Optional[int] = None,
) -> str:
    current_subject = subject
    current_body = body

    while True:
        print("\n" + "=" * 72)
        print("EMAIL DRAFT")
        print("=" * 72)
        print(f"To: {to_address}")
        print(f"Subject: {current_subject}")
        print("\nBody:")
        print(current_body)
        print("=" * 72)

        choice = input(
            "(y) send as-is, (e) edit manually, (r) rewrite with instructions, "
            "(n) skip: "
        ).strip().lower()

        if choice == "n":
            return "skipped"

        if choice == "y":
            send_email(to_address, current_subject, current_body)
            if application_id is not None:
                add_contact(
                    application_id=application_id,
                    email_sent_at=datetime.now(timezone.utc).isoformat(),
                )
            return "sent"

        if choice == "e":
            edited_subject, edited_body = _prompt_for_edit(
                current_subject,
                current_body,
            )
            print("\nEdited draft:")
            print(f"To: {to_address}")
            print(f"Subject: {edited_subject}")
            print("\nBody:")
            print(edited_body)
            confirmation = input("Send this edited draft? (y/n): ").strip().lower()
            if confirmation != "y":
                return "skipped"
            send_email(to_address, edited_subject, edited_body)
            if application_id is not None:
                add_contact(
                    application_id=application_id,
                    email_sent_at=datetime.now(timezone.utc).isoformat(),
                )
            return "edited_and_sent"

        if choice == "r":
            instruction = input("What would you like changed? ").strip()
            if not instruction:
                print("Rewrite skipped: an instruction is required.")
                continue

            revised = generate_email_revision(
                subject=current_subject,
                body=current_body,
                instruction=instruction,
                jd_text=jd_text,
                resume_json=resume_json,
            )
            current_subject = revised["subject"]
            current_body = revised["body"]
            continue

        print("Invalid choice. Draft skipped.")
        return "skipped"