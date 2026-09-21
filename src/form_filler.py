from __future__ import annotations

import json
import re
import os
from pathlib import Path
from typing import Any

from db import update_status
from llm_client import call_llm


class UnsupportedPlatformError(ValueError):
    """Raised when a job URL is not supported by this agent."""


# Best-effort selectors. ATS themes can vary by actual job posting, so
# these may need adjusting per posting.
SELECTOR_MAPS: dict[str, dict[str, str]] = {
    "greenhouse": {
        "first_name": (
            'input[name="first_name"], '
            'input[id*="first_name" i], '
            'input[autocomplete="given-name"]'
        ),
        "last_name": (
            'input[name="last_name"], '
            'input[id*="last_name" i], '
            'input[autocomplete="family-name"]'
        ),
        "email": (
            'input[name="email"], '
            'input[type="email"], '
            'input[autocomplete="email"]'
        ),
        "phone": (
            'input[name="phone"], '
            'input[type="tel"], '
            'input[autocomplete="tel"]'
        ),
        "linkedin": (
            'input[name*="linkedin" i], '
            'input[id*="linkedin" i]'
        ),
        "resume_upload": (
            'input[type="file"][name*="resume" i], '
            'input[type="file"][id*="resume" i], '
            'input[type="file"]'
        ),
    },
    "lever": {
        "full_name": (
            'input[name="name"], '
            'input[id*="name" i], '
            'input[autocomplete="name"]'
        ),
        "email": (
            'input[name="email"], '
            'input[type="email"], '
            'input[autocomplete="email"]'
        ),
        "phone": (
            'input[name="phone"], '
            'input[type="tel"], '
            'input[autocomplete="tel"]'
        ),
        "linkedin": (
            'input[name*="linkedin" i], '
            'input[id*="linkedin" i]'
        ),
        "resume_upload": (
            'input[type="file"][name*="resume" i], '
            'input[type="file"][id*="resume" i], '
            'input[type="file"]'
        ),
    },
}


def open_job_page(url: str) -> tuple[Any, Any, Any]:
    """Open a job page in a headed Chromium browser."""
    from playwright.sync_api import sync_playwright

    playwright_instance = sync_playwright().start()
    browser = playwright_instance.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded")
    return playwright_instance, browser, page


def detect_platform(url: str) -> str:
    if "boards.greenhouse.io" in url:
        return "greenhouse"
    if "jobs.lever.co" in url:
        return "lever"
    raise UnsupportedPlatformError(f"Unsupported job platform for URL: {url}")


def _resume_contact(resume_json: dict[str, Any]) -> dict[str, Any]:
    contact = resume_json.get("contact", {})
    return contact if isinstance(contact, dict) else {}


def _resume_name(resume_json: dict[str, Any]) -> tuple[str, str]:
    name = str(resume_json.get("name", "")).strip()
    parts = name.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _fill(page: Any, selector: str, value: str, field_name: str) -> None:
    try:
        if value:
            page.locator(selector).first.fill(value)
        else:
            print(f"Warning: skipped {field_name}; no value was found in the profile.")
    except Exception as exc:
        print(f"Warning: skipped {field_name}: {exc}")


def fill_standard_fields(
    page: Any,
    platform: str,
    resume_json: dict,
    resume_file_path: str,
) -> None:
    if platform not in SELECTOR_MAPS:
        raise UnsupportedPlatformError(f"Unsupported platform: {platform}")

    selectors = SELECTOR_MAPS[platform]
    contact = _resume_contact(resume_json)
    first_name, last_name = _resume_name(resume_json)

    if platform == "greenhouse":
        _fill(page, selectors["first_name"], first_name, "first name")
        _fill(page, selectors["last_name"], last_name, "last name")
    else:
        _fill(
            page,
            selectors["full_name"],
            str(resume_json.get("name", "")).strip(),
            "full name",
        )

    _fill(page, selectors["email"], str(contact.get("email", "")).strip(), "email")
    _fill(page, selectors["phone"], str(contact.get("phone", "")).strip(), "phone")

    if contact.get("linkedin") and "linkedin" in selectors:
        _fill(page, selectors["linkedin"], str(contact["linkedin"]).strip(), "linkedin")

    try:
        if resume_file_path and Path(resume_file_path).exists():
            page.locator(selectors["resume_upload"]).first.set_input_files(resume_file_path)
    except Exception as exc:
        print(f"Warning: skipped resume upload: {exc}")


def _textarea_context(textarea: Any) -> str:
    try:
        placeholder = textarea.get_attribute("placeholder") or ""
        aria_label = textarea.get_attribute("aria-label") or ""
        textarea_id = textarea.get_attribute("id") or ""

        labels = []
        if textarea_id:
            labels = textarea.locator(
                f"xpath=preceding::label[@for='{textarea_id}'][1]"
            ).all_inner_texts()

        context = " ".join(
            part.strip() for part in [*labels, placeholder, aria_label] if part and part.strip()
        )
        return context or "Application question"
    except Exception:
        return "Application question"


def fill_free_text_questions(
    page: Any,
    jd_text: str,
    resume_json: dict,
) -> None:
    textareas = page.locator("textarea")
    count = textareas.count()

    system_prompt = (
        "You answer job application questions using only the supplied resume "
        "and job description. Do not invent facts, employers, dates, metrics, "
        "skills, degrees, work authorization, sponsorship, or experiences not "
        "present in the provided data. If the available information is "
        "insufficient to answer well, say so briefly rather than guessing. "
        "Return only the answer text, under 400 characters, no markdown."
    )

    for index in range(count):
        textarea = textareas.nth(index)
        question = _textarea_context(textarea)
        user_prompt = (
            f"QUESTION:\n{question}\n\n"
            f"RESUME JSON:\n{json.dumps(resume_json, ensure_ascii=False)}\n\n"
            f"JOB DESCRIPTION:\n{jd_text}"
        )

        try:
            answer = call_llm(system_prompt, user_prompt).strip()
            answer = re.sub(r"\s+", " ", answer)[:400]
            textarea.fill(answer)
        except Exception as exc:
            print(f"Warning: skipped free-text question {index + 1}: {exc}")


def take_review_screenshot(
    page: Any,
    company: str,
    output_dir: str = "outputs",
) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    safe_company = re.sub(r"[^A-Za-z0-9._-]+", "_", company).strip("._-") or "company"
    screenshot_path = output_path / f"review_{safe_company}.png"

    page.screenshot(path=str(screenshot_path), full_page=True)
    return str(screenshot_path)


def run_form_fill(
    url: str,
    resume_json: dict,
    resume_file_path: str,
    jd_text: str,
    company: str,
    application_id: int,
) -> str:
    playwright_instance = None
    browser = None

    try:
        playwright_instance, browser, page = open_job_page(url)
        platform = detect_platform(url)
        fill_standard_fields(page, platform, resume_json, resume_file_path)
        fill_free_text_questions(page, jd_text, resume_json)

        screenshot_path = take_review_screenshot(page, company)
        update_status(application_id, "Ready for review")

        print(
            "\nBrowser is open for manual review. Review every field before "
            "deciding whether to submit. Press Enter only once you have "
            "finished reviewing."
        )
        input("Press Enter once you've reviewed (and manually submitted if you chose to)...")
        return screenshot_path
    finally:
        if browser is not None:
            browser.close()
        if playwright_instance is not None:
            playwright_instance.stop()


def run_form_fill_web(job_url: str, profile: dict) -> tuple[Any, Any, Any]:
    """
    Web-friendly wrapper that disables standard input blocking (no auto-submit risk)
    and surfaces explicit Playwright display environment errors.
    """
    from playwright.sync_api import sync_playwright

    # Pre-flight check for headless-unfriendly environments
    if os.name == 'posix' and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError("No DISPLAY environment variable found. A real or virtual display is required.")
         
    try:
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(job_url, wait_until="domcontentloaded")
        
        try:
            platform = detect_platform(job_url)
            # Default fallbacks since the web route doesn't track current jd_text or active tailored file path
            fallback_resume_path = "outputs/tailored_resume.docx"
            
            fill_standard_fields(page, platform, profile, fallback_resume_path)
            fill_free_text_questions(page, "", profile)
        except UnsupportedPlatformError as e:
            print(f"Platform detection failed or unsupported: {e}")
            
        take_review_screenshot(page, "web_review")
        
        # Explicitly returns the objects so they aren't garbage collected immediately,
        # leaving the browser open for the user's manual review & submit click.
        return p, browser, page
    except Exception as e:
        raise RuntimeError(f"Playwright display error: {str(e)}")