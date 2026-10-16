"""Check this change's Markdown links and fences; semantic review is still required."""
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def changed_markdown():
    # -z avoids Git quoting non-ASCII paths in filenames.
    names = []
    for command in (["git", "diff", "--name-only", "-z", "HEAD"],
                    ["git", "ls-files", "--others", "--exclude-standard", "-z"]):
        names.extend(subprocess.check_output(command, cwd=ROOT).decode("utf-8").split("\0"))
    return sorted({name for name in names if name.endswith(".md") and (ROOT / name).is_file()})


def main():
    errors = []
    paths = sys.argv[1:] or changed_markdown()
    for name in paths:
        path = ROOT / name
        content = path.read_text(encoding="utf-8")
        if len(re.findall(r"^```", content, re.M)) % 2:
            errors.append(f"{name}: unpaired code fence")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if target.startswith(("http://", "https://", "#")):
                continue
            target = unquote(target.split("#", 1)[0].strip("<>"))
            if not (path.parent / target).exists():
                errors.append(f"{name}: missing target {target}")
    for error in errors:
        print(error)
    print(f"Checked {len(paths)} Markdown files; {len(errors)} errors")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
