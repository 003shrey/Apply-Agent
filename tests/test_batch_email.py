"""Manual integration test for batch cold-email mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from batch_email import parse_batch_input, prepare_batch, run_batch_review


def _read_pasted_block() -> str:
    print(
        "Paste the batch input below. Finish with an empty line or a line "
        "containing only END:"
    )

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break

        if not line.strip() or line.strip() == "END":
            break

        lines.append(line)

    return "\n".join(lines)


def main() -> None:
    resume_path = PROJECT_ROOT / "data" / "resume.json"
    with resume_path.open("r", encoding="utf-8") as file:
        resume_json = json.load(file)

    raw_text = _read_pasted_block()
    if not raw_text.strip():
        print("No input supplied.")
        return

    entries = parse_batch_input(raw_text)

    print("\nParsed entries:")
    for index, entry in enumerate(entries, start=1):
        print(f"{index}. {json.dumps(entry, indent=2)}")

    resume_version = input(
        "\nResume version to record in the tracker [default: current]: "
    ).strip() or "current"

    prepared_batch = prepare_batch(
        entries=entries,
        resume_json=resume_json,
        resume_version=resume_version,
    )

    try:
        run_batch_review(
            prepared_batch=prepared_batch,
            resume_json=resume_json,
        )
    except Exception as exc:
        print(f"\nGmail-related or review failure: {exc}")


if __name__ == "__main__":
    main()