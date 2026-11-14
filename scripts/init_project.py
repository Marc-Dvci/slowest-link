"""Turn the template into a project: fill the known placeholders, then delete the template's own files.

    python scripts/init_project.py --name "<Name>" --repo <repo> [--tagline "<what it does for whom>"] [--owner Marc-Dvci]

Run once, right after creating the repository from the template. It lists the placeholders left for later.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "node_modules", "__pycache__"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tagline")
    ap.add_argument("--owner", default="Marc-Dvci")
    a = ap.parse_args()
    values = {
        "{{NAME}}": a.name,
        "{{REPO}}": a.repo,
        "{{OWNER}}": a.owner,
        "{{OWNER_LOWER}}": a.owner.lower(),
        "{{YEAR}}": str(datetime.date.today().year),
    }
    if a.tagline:
        values["{{TAGLINE}}"] = a.tagline
    changed = 0
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for key, value in values.items():
            new = new.replace(key, value)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="")
            changed += 1
    print(f"filled placeholders in {changed} files", flush=True)
    for leftover in (ROOT / "TEMPLATE.md", Path(__file__)):
        leftover.unlink(missing_ok=True)
    print("deleted TEMPLATE.md and this script; placeholders left for later:", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_placeholders.py")], check=False)


if __name__ == "__main__":
    main()
