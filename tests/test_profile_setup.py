

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from profile_manager import (
    build_profile_from_file,
    build_profile_manually,
    is_profile_complete,
    load_profile,
    review_profile,
    save_profile,
)


def _handle_upload() -> None:
    file_path = input("Path to your resume file (.pdf, .docx, or .txt): ").strip()

    try:
        profile = build_profile_from_file(file_path)
    except Exception as exc:
        print(f"\nCouldn't build a profile from that file: {exc}")
        return

    while True:
        if review_profile(profile):
            save_profile(profile)
            return

        print("\nNot saved. What would you like to do?")
        print("(r) retry parsing the same file")
        print("(m) switch to manual entry to fix specific fields")
        print("(q) quit without saving")
        choice = input("> ").strip().lower()

        if choice == "r":
            try:
                profile = build_profile_from_file(file_path)
            except Exception as exc:
                print(f"\nCouldn't build a profile from that file: {exc}")
                return
        elif choice == "m":
            profile = build_profile_manually()
        else:
            print("Nothing saved.")
            return


def _handle_manual() -> None:
    profile = build_profile_manually()
    if review_profile(profile):
        save_profile(profile)
    else:
        print("Nothing saved.")


def _handle_view() -> None:
    try:
        profile = load_profile()
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        return

    review_profile(profile)  # reuse for display; ignores the y/n answer here
    complete, missing = is_profile_complete(profile)
    if complete:
        print("\nProfile is complete enough for form-filling.")
    else:
        print(f"\nProfile is missing required fields for form-filling: {', '.join(missing)}")


def main() -> None:
    while True:
        print("\nHow would you like to set up your profile?")
        print("(1) Upload a resume file")
        print("(2) Enter details manually")
        print("(3) View current profile")
        print("(4) Quit")
        choice = input("> ").strip()

        if choice == "1":
            _handle_upload()
        elif choice == "2":
            _handle_manual()
        elif choice == "3":
            _handle_view()
        elif choice == "4":
            return
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()