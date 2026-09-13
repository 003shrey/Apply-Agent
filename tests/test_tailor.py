import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import argparse
import json

from tailor import export_resume, tailor_resume


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tailor resume.json against a pasted or file-based job description."
    )
    parser.add_argument(
        "--resume",
        default="data/resume.json",
        help="Path to resume JSON file.",
    )
    parser.add_argument(
        "--jd-file",
        help="Read the job description from a text file instead of pasting it.",
    )
    parser.add_argument(
        "--output",
        default="outputs/tailored_resume.docx",
        help="Output DOCX path.",
    )
    args = parser.parse_args()

    try:
        resume_json = json.loads(Path(args.resume).read_text(encoding="utf-8"))

        if args.jd_file:
            jd_text = Path(args.jd_file).read_text(encoding="utf-8")
        else:
            print("Paste the job description. Press Ctrl-D on Unix/macOS or Ctrl-Z then Enter on Windows.")
            jd_text = sys.stdin.read()

        result = tailor_resume(resume_json, jd_text)
        tailored_resume = result["tailored_resume"]

        output_path = export_resume(tailored_resume, args.output)

        print("\n=== Tailored Resume JSON ===")
        print(json.dumps(tailored_resume, indent=2, ensure_ascii=False))

        print("\n=== Missing Keywords ===")
        print(json.dumps(result["missing_keywords"], indent=2, ensure_ascii=False))

        print(f"\nExported DOCX: {output_path}")
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())