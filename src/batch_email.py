"""Batch cold-email parsing, preparation, and review."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

try:
    from .db import add_contact, log_application
    from .email_gen import (
        _parse_email_response,
        _strip_markdown_fences,
        generate_cold_email,
    )
    from .emailer import review_and_send, send_email
    from .llm_client import call_llm
except ImportError:
    from db import add_contact, log_application
    from email_gen import (
        _parse_email_response,
        _strip_markdown_fences,
        generate_cold_email,
    )
    from emailer import review_and_send, send_email
    from llm_client import call_llm


_EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


def _normalise_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    email = value.strip().strip("<>").strip()
    if not _EMAIL_RE.fullmatch(email):
        return None

    return email


def _extract_json_array(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        parsed = response
    else:
        text = response if isinstance(response, str) else str(response)
        text = _strip_markdown_fences(text).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end <= start:
                raise ValueError(
                    "LLM response did not contain a valid JSON array."
                ) from exc

            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as nested_exc:
                raise ValueError(
                    "LLM response contained an invalid JSON array."
                ) from nested_exc

    if not isinstance(parsed, list):
        raise ValueError("Batch parser expected a JSON array.")

    validated: list[dict[str, Any]] = []
    skipped = 0

    for item in parsed:
        if not isinstance(item, dict):
            skipped += 1
            continue

        company = item.get("company")
        recruiter_email = _normalise_email(item.get("recruiter_email"))

        if not isinstance(company, str) or not company.strip() or not recruiter_email:
            skipped += 1
            continue

        role = item.get("role", "")
        jd_text = item.get("jd_text", "")
        recruiter_name = item.get("recruiter_name")

        validated.append(
            {
                "company": company.strip(),
                "role": role.strip() if isinstance(role, str) else "",
                "jd_text": jd_text.strip() if isinstance(jd_text, str) else "",
                "recruiter_name": (
                    recruiter_name.strip()
                    if isinstance(recruiter_name, str) and recruiter_name.strip()
                    else None
                ),
                "recruiter_email": recruiter_email,
            }
        )

    if skipped:
        print(
            f"Warning: skipped {skipped} entr"
            f"{'y' if skipped == 1 else 'ies'} without a valid recruiter email "
            "or company."
        )

    if not validated:
        raise ValueError(
            "No valid batch entries were found. Each entry requires a company "
            "and valid recruiter_email."
        )

    return validated


def parse_batch_input(raw_text: str) -> list[dict]:
    """Parse pasted free text into validated batch email entries."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Batch input is empty.")

    system_prompt = """You extract structured job-application cold-email recipients from free-form text.
Return ONLY a JSON array. Do not include markdown fences, commentary, or any
text outside the JSON array.

Each array item must have exactly these fields:
- company: string
- role: string, or "" if absent
- jd_text: string, or "" if no job-description text is present
- recruiter_name: string or null if absent
- recruiter_email: string

Include an item only when a valid recruiter email address can be identified.
Do not invent or infer email addresses. Preserve the available company, role,
and job-description information."""

    user_prompt = f"""Extract entries from the text below.

Input:
{raw_text}
"""

    response = call_llm(system_prompt, user_prompt)
    return _extract_json_array(response)


def prepare_batch(
    entries: list[dict[str, Any]],
    resume_json: dict,
    resume_version: str,
) -> list[dict]:
    """Generate drafts and create Draft tracker records for every entry."""
    prepared: list[dict] = []

    for entry in entries:
        draft = generate_cold_email(
            entry.get("jd_text", ""),
            resume_json,
            entry.get("recruiter_name"),
        )

        application_id = log_application(
            company=entry["company"],
            role=entry.get("role", ""),
            jd_text=entry.get("jd_text", ""),
            resume_version=resume_version,
        )

        prepared.append(
            {
                **entry,
                "subject": draft["subject"],
                "body": draft["body"],
                "application_id": application_id,
            }
        )

    return prepared


def _print_summary(prepared_batch: list[dict[str, Any]]) -> None:
    print("\nPrepared drafts:")
    for index, entry in enumerate(prepared_batch, start=1):
        print(
            f"{index}. {entry['company']} | {entry.get('role', '')} | "
            f"{entry['recruiter_email']} | {entry['subject']}"
        )


def _print_full_drafts(prepared_batch: list[dict[str, Any]]) -> None:
    print("\nFull drafts:")
    for index, entry in enumerate(prepared_batch, start=1):
        print(f"\n{'=' * 72}")
        print(f"Draft {index}")
        print(f"To: {entry['recruiter_email']}")
        print(f"Subject: {entry['subject']}")
        print(f"\n{entry['body']}")
    print(f"\n{'=' * 72}")


def _print_results(results: list[dict[str, str]]) -> None:
    print("\nBatch results:")
    print(f"{'#':<4} {'Company':<24} {'Role':<24} {'Email':<32} Result")
    print("-" * 100)
    for index, result in enumerate(results, start=1):
        print(
            f"{index:<4} {result['company'][:23]:<24} "
            f"{result['role'][:23]:<24} "
            f"{result['recruiter_email'][:31]:<32} {result['result']}"
        )


def run_batch_review(
    prepared_batch: list[dict],
    resume_json: dict,
) -> list[dict]:
    """Review and optionally send a prepared batch."""
    if not prepared_batch:
        print("No prepared drafts.")
        return []

    _print_summary(prepared_batch)
    choice = input(
        "\n(a) approve all and send, (r) review one by one, "
        "(q) quit without sending any: "
    ).strip().lower()

    if choice == "q":
        results = [
            {
                "company": entry["company"],
                "role": entry.get("role", ""),
                "recruiter_email": entry["recruiter_email"],
                "result": "skipped",
            }
            for entry in prepared_batch
        ]
        print(f"\n0 sent; {len(results)} skipped.")
        _print_results(results)
        return results

    if choice == "r":
        results = []
        for entry in prepared_batch:
            try:
                result = review_and_send(
                    to_address=entry["recruiter_email"],
                    subject=entry["subject"],
                    body=entry["body"],
                    jd_text=entry.get("jd_text", ""),
                    resume_json=resume_json,
                    application_id=entry["application_id"],
                )
            except Exception as exc:
                result = f"failed: {exc}"

            results.append(
                {
                    "company": entry["company"],
                    "role": entry.get("role", ""),
                    "recruiter_email": entry["recruiter_email"],
                    "result": result,
                }
            )

        _print_results(results)
        return results

    if choice != "a":
        raise ValueError("Invalid choice. Expected 'a', 'r', or 'q'.")

    _print_full_drafts(prepared_batch)
    confirmation = input(
        f"Send all {len(prepared_batch)} emails as shown above? (y/n) "
    ).strip().lower()

    if confirmation != "y":
        results = [
            {
                "company": entry["company"],
                "role": entry.get("role", ""),
                "recruiter_email": entry["recruiter_email"],
                "result": "skipped",
            }
            for entry in prepared_batch
        ]
        print(f"\n0 sent; {len(results)} skipped.")
        _print_results(results)
        return results

    results = []
    for entry in prepared_batch:
        try:
            send_email(
                entry["recruiter_email"],
                entry["subject"],
                entry["body"],
            )
            add_contact(
                application_id=entry["application_id"],
                recruiter_name=entry.get("recruiter_name"),
                recruiter_email=entry["recruiter_email"],
                email_sent_at=datetime.now(timezone.utc).isoformat(),
            )
            result = "sent"
        except Exception as exc:
            result = f"failed: {exc}"
            print(
                f"Batch send failed for {entry['company']} "
                f"({entry['recruiter_email']}): {exc}"
            )

        results.append(
            {
                "company": entry["company"],
                "role": entry.get("role", ""),
                "recruiter_email": entry["recruiter_email"],
                "result": result,
            }
        )

    _print_results(results)
    return results