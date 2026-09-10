from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{40,}\b",
    r"\bsk-[A-Za-z0-9_-]{32,}\b",
    r"\bAKIA[A-Z0-9]{16}\b",
    r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the exact staged publication snapshot without printing sensitive content")
    parser.add_argument("--forbid-brand", action="append", default=[])
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    issues = []
    total_bytes = 0
    checked = 0
    brand_patterns = [re.compile(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", re.IGNORECASE) for term in args.forbid_brand]
    for name in filter(None, paths):
        path = Path(name)
        forbidden = any(part in {"node_modules", ".venv", "__pycache__", "logs", "dist"} for part in path.parts)
        forbidden = forbidden or name.startswith("data/") or path.name.startswith(".env") and path.name != ".env.example"
        forbidden = forbidden or path.suffix.lower() in {".pem", ".key", ".token", ".db", ".pyc"}
        forbidden = forbidden or name.startswith("research/")
        if forbidden:
            issues.append({"path": name, "issue": "private or generated artifact staged"})
        content = subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)
        checked += 1
        total_bytes += len(content)
        if len(content) > 50 * 1024 * 1024:
            issues.append({"path": name, "issue": "file exceeds 50 MiB review threshold"})
        if any(pattern.search(name) for pattern in brand_patterns):
            issues.append({"path": name, "issue": "forbidden brand in path"})
        if b"\x00" in content[:8192]:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in brand_patterns):
            issues.append({"path": name, "issue": "forbidden brand in text"})
        if any(re.search(pattern, text) for pattern in SECRET_PATTERNS):
            issues.append({"path": name, "issue": "potential credential material; inspect locally"})
    print(json.dumps({"stagedFiles": checked, "bytes": total_bytes, "issues": issues}, ensure_ascii=False, indent=2))
    if not checked or issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()