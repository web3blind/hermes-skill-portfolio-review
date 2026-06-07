#!/usr/bin/env python3
"""Validate that the public portfolio-review skill export is publishable.

Checks are intentionally lightweight and local:
- SKILL.md frontmatter is parseable and has required fields;
- ignored private/runtime file names are not tracked in the repo;
- markdown files do not contain obvious raw EVM/Solana wallet addresses;
- Python scripts compile.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FILE_NAMES = {
    ".env",
    "addresses.conf",
    "addresses.local.conf",
    "wallets.conf",
    "wallets.local.conf",
    "config.json",
    "config.local.json",
    "state.json",
    "chro-informer-state.json",
}
PRIVATE_PATH_PARTS = {"state", "runs", "output", "debug", "__pycache__"}
EVM_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}(?![a-fA-F0-9])")
# Broad enough for public docs. The allow-list below prevents flagging examples.
SOLANA_ADDRESS_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
SOLANA_EXAMPLE_VALUES = {"11111111111111111111111111111111"}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def validate_skill_frontmatter() -> None:
    skill = ROOT / "SKILL.md"
    text = skill.read_text("utf-8")
    if not text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        fail("SKILL.md frontmatter is not closed")
    _, frontmatter, body = parts
    if not body.strip():
        fail("SKILL.md body is empty")
    required = {"name", "description"}
    seen = set()
    for line in frontmatter.splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        key = line.split(":", 1)[0].strip()
        seen.add(key)
    missing = sorted(required - seen)
    if missing:
        fail(f"SKILL.md missing required frontmatter keys: {', '.join(missing)}")


def validate_no_private_tracked_files(files: list[Path]) -> None:
    for path in files:
        rel = path.relative_to(ROOT)
        parts = set(rel.parts)
        if path.name in PRIVATE_FILE_NAMES:
            fail(f"private runtime file is tracked: {rel}")
        if parts & PRIVATE_PATH_PARTS:
            fail(f"private/runtime directory content is tracked: {rel}")
        if path.suffix in {".log", ".tmp", ".pyc"}:
            fail(f"runtime artifact is tracked: {rel}")


def validate_no_raw_wallets(files: list[Path]) -> None:
    text_files = [p for p in files if p.suffix in {".md", ".conf", ".json"}]
    for path in text_files:
        rel = path.relative_to(ROOT)
        text = path.read_text("utf-8", errors="ignore")
        for match in EVM_ADDRESS_RE.findall(text):
            if match.lower() == "0xyour_evm_address":
                continue
            fail(f"raw EVM address found in tracked file {rel}: {match[:10]}…")
        for match in SOLANA_ADDRESS_RE.findall(text):
            if match in SOLANA_EXAMPLE_VALUES:
                continue
            # Ignore obvious prose/package words that happen to match the base58 alphabet.
            if not any(ch.isdigit() for ch in match):
                continue
            fail(f"raw Solana-like address found in tracked file {rel}: {match[:6]}…")


def validate_python_scripts(files: list[Path]) -> None:
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text("utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"Python syntax error in {path.relative_to(ROOT)}: {exc}")


def main() -> None:
    files = tracked_files()
    validate_skill_frontmatter()
    validate_no_private_tracked_files(files)
    validate_no_raw_wallets(files)
    validate_python_scripts(files)
    print("OK: portfolio-review public export checks passed")


if __name__ == "__main__":
    main()
