import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import list_applications, log_application
from form_filler import UnsupportedPlatformError, run_form_fill
from profile_manager import is_profile_complete, load_profile


def main() -> None:
    try:
        profile = load_profile()
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        print("Run tests/test_profile_setup.py first to create your profile.")
        return

    complete, missing = is_profile_complete(profile)
    if not complete:
        print(f"\nProfile is missing required fields: {', '.join(missing)}")
        print("Run tests/test_profile_setup.py to fill these in before form-filling.")
        return

    url = input("Job posting URL: ").strip()
    company = input("Company name: ").strip()
    role = input("Role name: ").strip()
    jd_text = input("Paste the job description text, then press Enter:\n").strip()
    resume_file_path = input("Path to the resume file to upload: ").strip()

    application_id = log_application(
        company=company,
        role=role,
        jd_text=jd_text,
        resume_version="current",
        jd_url=url,
    )

    try:
        screenshot_path = run_form_fill(
            url=url,
            resume_json=profile,
            resume_file_path=resume_file_path,
            jd_text=jd_text,
            company=company,
            application_id=application_id,
        )
        print(f"\nReview screenshot: {screenshot_path}")
    except UnsupportedPlatformError as exc:
        print(f"\nPlatform error: {exc}")
        return
    except Exception as exc:
        print(f"\nForm-fill run failed for application {application_id}: {exc}")
        return

    applications = list_applications()
    matching = [a for a in applications if a["id"] == application_id]

    if matching:
        print(f"\nFinal application status: {matching[0]['status']} (application ID {application_id})")
    else:
        print(f"\nCould not find application ID {application_id} after the run.")


if __name__ == "__main__":
    main()