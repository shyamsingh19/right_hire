#!/usr/bin/env python
"""Count tokens for a resume file against the actual parse_resume prompt.

Extracts text the same way the pipeline does (app/pipeline/parse.py:extract_text for
PDF/DOCX/images, or reads a .txt file directly), builds the real prompts/parse_resume.txt
prompt with the same text[:6000] cap used in parse_resume(), and reports tiktoken counts
for the raw resume text and the full prompt.

Usage:
    python scripts/count_resume_tokens.py path/to/resume.pdf
    python scripts/count_resume_tokens.py path/to/resume.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

import tiktoken

from app.pipeline.parse import extract_text

_ENCODING = "cl100k_base"  # matches gpt-4o-mini tokenization closely enough for budgeting
_PROMPT_TOKEN_BUDGET = 2024  # see CLAUDE.md: resume parse prompt budget


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <resume_file>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    text = path.read_text(errors="ignore") if path.suffix.lower() == ".txt" else extract_text(str(path))
    capped = text[:6000]

    template = Path("prompts/parse_resume.txt").read_text()
    prompt = template.replace("{{RESUME_TEXT}}", capped)

    enc = tiktoken.get_encoding(_ENCODING)
    text_tokens = len(enc.encode(text))
    capped_tokens = len(enc.encode(capped))
    prompt_tokens = len(enc.encode(prompt))

    print(f"file:                 {path}")
    print(f"raw text chars:       {len(text)}")
    print(f"raw text tokens:      {text_tokens}")
    print(f"capped (6000 char):   {len(capped)} chars, {capped_tokens} tokens")
    print(f"full prompt tokens:   {prompt_tokens}")
    over = prompt_tokens > _PROMPT_TOKEN_BUDGET
    print(
        f"vs prompt budget ({_PROMPT_TOKEN_BUDGET}): "
        f"{'OVER by ' + str(prompt_tokens - _PROMPT_TOKEN_BUDGET) if over else 'within budget'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
