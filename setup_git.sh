#!/usr/bin/env bash
set -euo pipefail

# Run this from /home/itspe/right_hire
# Does NOT touch /home/itspe/.git and does NOT push anywhere.

cd /home/itspe/right_hire

# --- Step 0: bring the .gitignore that's sitting one level up (in $HOME)
# into the project, since its rules (.env, __pycache__, .egg-info, .vscode,
# storage/) are clearly scoped to this project, not your home directory.
mv ../.gitignore .

# --- Step 1: init a fresh repo scoped ONLY to this directory
git init
git branch -m main-c   # match the branch name used on origin

# Sanity check: this must print /home/itspe/right_hire, not /home/itspe
git rev-parse --show-toplevel

# --- Step 2 (optional, do it yourself when ready): wire up the remote.
# Left commented out on purpose - pushing will conflict with the existing
# origin/main-c history (unrelated histories: this repo starts fresh).
# git remote add origin git@github-personal:shyamsingh19/right_hire.git

# =====================================================================
# 15 logical commits
# =====================================================================

# 1. Project scaffolding & config
git add pyproject.toml Makefile .gitignore .env.example docker-compose.yml
git commit -m "chore: initial project scaffolding and configuration"

# 2. Architecture & implementation docs
git add CLAUDE.md implementation.md
git commit -m "docs: add architecture overview and implementation notes"

# 3. Core settings and DB engine
git add app/config.py app/db.py
git commit -m "feat: add pydantic settings and async SQLAlchemy engine"

# 4. Data models and schemas
git add app/models.py app/schemas.py
git commit -m "feat: add ORM models and pydantic I/O schemas"

# 5. LLM provider abstraction layer
git add app/llm/base.py app/llm/factory.py app/llm/__init__.py \
        app/llm/local.py app/llm/groq.py app/llm/openai.py
git commit -m "feat: add swappable LLM provider abstraction layer"

# 6. Prompt templates and judge grammar
git add prompts/ grammars/
git commit -m "feat: add prompt templates and judge output grammar"

# 7. Parsing and hard-filter pipeline stages
git add app/pipeline/__init__.py app/pipeline/parse.py app/pipeline/filters.py
git commit -m "feat: add resume/JD parsing and hard-filter pipeline stages"

# 8. Embedding and matching pipeline stages
git add app/pipeline/embed.py app/pipeline/match.py
git commit -m "feat: add embedding and candidate-matching pipeline stages"

# 9. Judge and scoring pipeline stages
git add app/pipeline/judge.py app/pipeline/score.py
git commit -m "feat: add LLM judge and weighted scoring pipeline stages"

# 10. Skills taxonomy canonicalizer
git add app/skills/
git commit -m "feat: add skills taxonomy and canonicalization utility"

# 11. Worker orchestration
git add app/workers/
git commit -m "feat: add RQ worker task orchestrating the full pipeline"

# 12. API routes and app entrypoint
git add app/api/ app/main.py
git commit -m "feat: add FastAPI routes and application entrypoint"

# 13. Alembic migration environment
git add alembic/env.py
git commit -m "chore: add alembic migration environment"

# 14. Seed script, eval harness, Streamlit UI
git add scripts/ ui/
git commit -m "feat: add demo seed script, eval harness, and Streamlit UI"

# 15. Tests and README
git add tests/ README.md
git commit -m "test: add unit/integration tests and project README"

echo "Done. Review with: git log --oneline"
