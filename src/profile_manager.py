"""Profile setup: build, review, save, and load the resume.json profile
used by tailoring, cold email, and the form-fill agent.

Nothing is ever written to disk except through save_profile(), and
save_profile() should only ever be called after review_profile() has
returned True. No function in this file saves automatically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from llm_client import call_llm


REQUIRED_FOR_FORM_FILL = [
    ("name", lambda p: bool(str(p.get("name", "")).strip())),
    ("contact.email", lambda p: bool(str(p.get("contact", {}).get("email", "")).strip())),
    ("contact.phone", lambda p: bool(str(p.get("contact", {}).get("phone", "")).strip())),
]

EMPTY_PROFILE: dict[str, Any] = {
    "name": "",
    "summary": "",
    "contact": {
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "location": "",
    },
    "skills": [],
    "experience": [],
    "projects": [],
    "education": [],
}


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_text_from_file(file_path: str) -> str:
    """Extract raw text from a .pdf, .docx, or .txt resume file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No file found at: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    if suffix == ".txt":
        return path.read_text(encoding="utf-8")

    raise ValueError(
        f"Unsupported file type '{suffix}'. Use .pdf, .docx, or .txt."
    )


def build_profile_from_file(file_path: str) -> dict:
    """Extract resume text from a file and convert it into the profile schema.

    Only pulls information actually present in the file. Never invents,
    infers, or guesses a field it can't find.
    """
    raw_text = _extract_text_from_file(file_path)

    if not raw_text.strip():
        raise ValueError(
            f"No extractable text found in {file_path}. "
            "The file may be a scanned image without a text layer."
        )

    system_prompt = """
You convert raw resume text into a structured JSON object.
Return ONLY one valid JSON object. Do not use Markdown, code fences,
explanations, commentary, or additional keys.

The JSON object must contain exactly these keys:
{
  "name": "",
  "summary": "",
  "contact": {
    "email": "",
    "phone": "",
    "linkedin": "",
    "github": "",
    "location": ""
  },
  "skills": [],
  "experience": [
    {"title": "", "company": "", "location": "", "start_date": "",
     "end_date": "", "bullets": []}
  ],
  "projects": [
    {"name": "", "description": "", "technologies": [], "bullets": []}
  ],
  "education": [
    {"degree": "", "institute": "", "location": "", "year": ""}
  ]
}

CRITICAL RULES:
- Extract ONLY information that literally appears in the input text.
- Do NOT invent, infer, guess, or embellish any field.
- If a field is not present in the text, use an empty string "" for
  string fields or an empty list [] for list fields. Do NOT fabricate
  a plausible-looking value.
- Do not invent email addresses, phone numbers, dates, employers,
  degrees, or any other detail not literally present in the text.
- contact.linkedin and contact.github should only be filled if an
  actual URL or handle for that specific platform appears in the text.
""".strip()

    user_prompt = f"RESUME TEXT:\n{raw_text}"

    raw_response = call_llm(system_prompt, user_prompt)
    cleaned_response = _strip_markdown_fences(raw_response)

    try:
        result = json.loads(cleaned_response)
    except json.JSONDecodeError as exc:
        preview = cleaned_response[:500]
        raise ValueError(
            f"The LLM returned malformed JSON while parsing the resume. "
            f"JSON error: {exc}. Response preview: {preview!r}"
        ) from exc

    if not isinstance(result, dict):
        raise ValueError("The LLM response must be a JSON object.")

    # Merge onto EMPTY_PROFILE so any keys the model omitted still exist
    # with safe defaults, rather than causing a KeyError downstream.
    profile = json.loads(json.dumps(EMPTY_PROFILE))
    profile.update({k: v for k, v in result.items() if k != "contact"})
    if isinstance(result.get("contact"), dict):
        profile["contact"].update(result["contact"])

    return profile


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def build_profile_manually() -> dict:
    """Interactively collect a complete profile via terminal prompts."""
    profile = json.loads(json.dumps(EMPTY_PROFILE))

    print("\n--- Basic info ---")
    profile["name"] = _prompt("Full name")
    profile["summary"] = _prompt("Professional summary (1-3 sentences)")

    print("\n--- Contact info ---")
    profile["contact"]["email"] = _prompt("Email")
    profile["contact"]["phone"] = _prompt("Phone")
    profile["contact"]["linkedin"] = _prompt("LinkedIn URL (optional, Enter to skip)")
    profile["contact"]["github"] = _prompt("GitHub URL (optional, Enter to skip)")
    profile["contact"]["location"] = _prompt("Location (optional, Enter to skip)")

    print("\n--- Skills ---")
    skills_raw = input("Skills, comma-separated: ").strip()
    profile["skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()]

    print("\n--- Experience ---")
    while input("Add a work experience? (y/n): ").strip().lower() == "y":
        entry = {
            "title": _prompt("  Title"),
            "company": _prompt("  Company"),
            "location": _prompt("  Location (optional)"),
            "start_date": _prompt("  Start date"),
            "end_date": _prompt("  End date (or 'Present')"),
            "bullets": [],
        }
        print("  Enter bullets one at a time. Blank line to finish.")
        while True:
            bullet = input("  Bullet: ").strip()
            if not bullet:
                break
            entry["bullets"].append(bullet)
        profile["experience"].append(entry)

    print("\n--- Projects ---")
    while input("Add a project? (y/n): ").strip().lower() == "y":
        entry = {
            "name": _prompt("  Project name"),
            "description": _prompt("  Short description"),
            "technologies": [
                t.strip()
                for t in input("  Technologies, comma-separated: ").strip().split(",")
                if t.strip()
            ],
            "bullets": [],
        }
        print("  Enter bullets one at a time. Blank line to finish.")
        while True:
            bullet = input("  Bullet: ").strip()
            if not bullet:
                break
            entry["bullets"].append(bullet)
        profile["projects"].append(entry)

    print("\n--- Education ---")
    while input("Add an education entry? (y/n): ").strip().lower() == "y":
        entry = {
            "degree": _prompt("  Degree"),
            "institute": _prompt("  Institute"),
            "location": _prompt("  Location (optional)"),
            "year": _prompt("  Year(s)"),
        }
        profile["education"].append(entry)

    return profile


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def review_profile(profile: dict) -> bool:
    """Pretty-print the full profile and ask for explicit approval.

    Returns True only if the user explicitly confirms. This is the
    single gate that must pass before save_profile() is called.
    """
    _print_section("PROFILE REVIEW")
    print(f"Name: {profile.get('name', '')}")
    print(f"Summary: {profile.get('summary', '')}")

    contact = profile.get("contact", {})
    print("\nContact:")
    for key in ("email", "phone", "linkedin", "github", "location"):
        value = contact.get(key, "")
        if value:
            print(f"  {key}: {value}")

    skills = profile.get("skills", [])
    if skills:
        print(f"\nSkills: {', '.join(skills)}")

    experience = profile.get("experience", [])
    if experience:
        print(f"\nExperience ({len(experience)} entries):")
        for item in experience:
            print(f"  - {item.get('title', '')} at {item.get('company', '')} "
                  f"({item.get('start_date', '')} - {item.get('end_date', '')})")
            for bullet in item.get("bullets", []):
                print(f"      * {bullet}")

    projects = profile.get("projects", [])
    if projects:
        print(f"\nProjects ({len(projects)} entries):")
        for item in projects:
            print(f"  - {item.get('name', '')}: {item.get('description', '')}")
            for bullet in item.get("bullets", []):
                print(f"      * {bullet}")

    education = profile.get("education", [])
    if education:
        print(f"\nEducation ({len(education)} entries):")
        for item in education:
            print(f"  - {item.get('degree', '')}, {item.get('institute', '')} "
                  f"({item.get('year', '')})")

    print(f"\n{'=' * 60}")
    choice = input("Does this look correct? (y/n): ").strip().lower()
    return choice == "y"


def save_profile(profile: dict, path: str = "data/resume.json") -> None:
    """Write the profile to disk. Only call after review_profile() -> True."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nProfile saved to {output_path}")


def load_profile(path: str = "data/resume.json") -> dict:
    """Load an existing profile from disk."""
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(
            f"No profile found at {path}. Run profile setup first "
            "(tests/test_profile_setup.py)."
        )
    with profile_path.open(encoding="utf-8") as file:
        return json.load(file)


def is_profile_complete(profile: dict) -> tuple[bool, list[str]]:
    """Check whether the minimum fields needed for form-filling are present."""
    missing = [
        field_name
        for field_name, check in REQUIRED_FOR_FORM_FILL
        if not check(profile)
    ]
    return (len(missing) == 0, missing)


def build_profile_manually_web(form_data: dict) -> dict:
    """
    Web-friendly mapper that turns plain form submission data into the resume JSON schema.
    """
    return {
        "name": form_data.get("name", ""),
        "summary": form_data.get("summary", ""),
        "skills": [s.strip() for s in form_data.get("skills", "").split(",") if s.strip()],
        "experience": [{"title": form_data.get("exp_title", ""), "company": form_data.get("exp_company", ""), "bullets": [form_data.get("exp_bullets", "")]}],
        "projects": [{"name": form_data.get("proj_name", ""), "bullets": [form_data.get("proj_bullets", "")]}],
        "education": [{"degree": form_data.get("edu_degree", ""), "institute": form_data.get("edu_inst", ""), "year": form_data.get("edu_year", "")}],
        "contact": {
            "email": form_data.get("email", ""),
            "phone": form_data.get("phone", ""),
            "linkedin": form_data.get("linkedin", ""),
            "github": form_data.get("github", ""),
            "location": form_data.get("location", "")
        }
    }