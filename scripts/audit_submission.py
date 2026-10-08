"""Inspect only project submission candidates; never read credential/cache files."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".aws", ".aws-sam", ".tools", ".venv", "node_modules", "dist", "data", "__pycache__",
        ".pytest_cache", "test-results", "playwright-report", ".lambda-src"}
SECRET_NAMES = {"credentials", "config", ".env", ".npmrc", ".pypirc"}
TEXT = {".py", ".ps1", ".mjs", ".ts", ".tsx", ".css", ".json", ".md", ".yaml", ".toml", ".html", ".txt", ".svg", ".csv", ".example"}
PATTERNS = (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r'''(?i)(?:aws_secret_access_key|aws_session_token)\s*[=:]\s*["'][A-Za-z0-9/+=]{30,}["']'''))


def sensitive_path(path):
    return (path.name in SECRET_NAMES or path.suffix.lower() in (".pem", ".key", ".p12", ".sqlite3", ".log", ".pyc")
            or path.name.startswith(".env") and not path.name.endswith(".example") or path.name.endswith(".tsbuildinfo"))


def main():
    flagged, scanned, skipped = [], [], []
    def walk(folder):
        for path in folder.iterdir():
            if path.is_symlink():
                skipped.append(path.relative_to(ROOT).as_posix()); continue
            if path.name in SKIP:
                continue
            if path.is_dir():
                yield from walk(path)
            else:
                yield path
    for path in walk(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        if sensitive_path(path):
            skipped.append(relative); continue  # Do not open potential credential files.
        if path.stat().st_size > 5 * 1024 * 1024:
            flagged.append({"path": relative, "reason": "large submission candidate"}); continue
        scanned.append(relative)
        if path.suffix.lower() in TEXT:
            content = path.read_text(encoding="utf-8-sig")
            if any(pattern.search(content) for pattern in PATTERNS):
                flagged.append({"path": relative, "reason": "possible secret pattern (value suppressed)"})
            if path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", content):
                    if "://" in target or target.startswith("#"):
                        continue
                    local = target.split("#", 1)[0]
                    if local and not (path.parent / local).exists():
                        flagged.append({"path": relative, "reason": "broken relative documentation link: " + local})
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, capture_output=True, text=True)
    git_status = "No repository found; no repository initialized."
    if result.returncode == 0:
        if Path(result.stdout.strip()).resolve() != ROOT:
            git_status = "Parent repository detected; left untouched."
        else:
            git_status = "Repository exists; tracked paths checked."
            tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True)
            for name in tracked.stdout.split("\0"):
                if name and (sensitive_path(Path(name)) or set(Path(name).parts) & SKIP):
                    flagged.append({"path": name, "reason": "excluded/sensitive file tracked (contents not opened)"})
    print(json.dumps({"candidate_files_checked": len(scanned), "git": git_status, "findings": flagged,
                      "sensitive_or_generated_file_contents": "not opened", "limitation": "Pattern check, not a guarantee of absence of secrets."}, indent=2))
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
