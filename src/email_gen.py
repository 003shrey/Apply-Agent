# src/email_gen.py
"""Generate tailored cold-email drafts using the configured LLM provider."""

import json
import re
from typing import Any, Dict, Optional

try:
    from .llm_client import call_llm
except ImportError:
    from llm_client import call_llm


def _strip_markdown_fences(value: str) -> str:
    """Remove optional Markdown code fences around an LLM response."""
    value = value.strip()

    match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    return value


def _parse_email_response(response: Any) -> Dict[str, str]:
    """Parse and validate the structured LLM response."""
    if isinstance(response, dict):
        payload = response
    else:
        response_text = _strip_markdown_fences(str(response))

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "LLM returned invalid JSON for the cold email."
            ) from exc

    if not isinstance(payload, dict):
        raise ValueError("Cold email response must be a JSON object.")

    subject = payload.get("subject")
    body = payload.get("body")

    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Cold email response is missing a valid subject.")

    if not isinstance(body, str) or not body.strip():
        raise ValueError("Cold email response is missing a valid body.")

    return {
        "subject": subject.strip(),
        "body": body.strip(),
    }


def generate_cold_email(
    jd_text: str,
    resume_json: Dict[str, Any],
    recruiter_name: Optional[str] = None,
) -> Dict[str, str]:
    """Generate a concise, tailored cold-email draft."""
    recipient_name = recruiter_name.strip() if recruiter_name else "Hiring Team"

    system_prompt = """You write natural, concise, professional cold emails for a specific job opening.

Return only valid JSON with exactly two string fields:
{
  "subject": "...",
  "body": "..."
}

Do not use Markdown fences or include commentary outside the JSON.

The email must sound like a person making a focused pitch for this particular role, not like a resume rewritten as prose. Open with what specifically drew the candidate to the role, using one concrete responsibility, technology, or requirement explicitly present in the job description. Then use only the one or two most relevant resume details as supporting evidence. Do not enumerate projects, tools, or qualifications. Do not invent experience, achievements, company facts, or qualifications."""

    user_prompt = f"""Write a short cold email addressed to {recipient_name} for the job described below.

Requirements:
- Write exactly 3 or 4 sentences in the body.
- Begin with what specifically drew the candidate to this role.
- Reference one real detail from the job description itself, such as a responsibility, technology, or requirement.
- Weave in only the 1 or 2 resume points most relevant to that job-description detail.
- Make the message read as one coherent, natural pitch.
- Do not use resume-summary or enumeration patterns such as "I built X using Y and Z. I also have experience with..." 
- Do not list unrelated projects, technologies, or qualifications.
- Keep the tone professional, direct, and natural.
- Do not invent experience, qualifications, company facts, or achievements.
- Do not include a greeting addressed to an unknown individual beyond "{recipient_name}".
- Do not include a sign-off with a fabricated name.
- Return only JSON with "subject" and "body".

Job description:
{jd_text}

Resume JSON:
{json.dumps(resume_json, ensure_ascii=False, indent=2)}
"""

    response = call_llm(system_prompt, user_prompt)
    return _parse_email_response(response)


def generate_email_revision(
    subject: str,
    body: str,
    instruction: str,
    jd_text: str,
    resume_json: Dict[str, Any],
) -> Dict[str, str]:
    """Revise an email draft according to a user instruction."""
    if not instruction or not instruction.strip():
        raise ValueError("Revision instruction is required.")

    system_prompt = """You revise professional cold-email drafts for a specific job opening.

Return only valid JSON with exactly two string fields:
{
  "subject": "...",
  "body": "..."
}

Do not use Markdown fences or include commentary outside the JSON.

Preserve factual accuracy. Do not invent experience, qualifications, achievements, company facts, or job-description details. Keep the result natural and specific to the role. Unless the user's instruction requires otherwise, keep the body to 3 or 4 sentences and avoid resume-like lists."""

    user_prompt = f"""Revise the current cold-email draft according to the instruction below.

User instruction:
{instruction.strip()}

Current subject:
{subject}

Current body:
{body}

Job description:
{jd_text}

Resume JSON:
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

Return only JSON with "subject" and "body"."""

    response = call_llm(system_prompt, user_prompt)
    return _parse_email_response(response)


