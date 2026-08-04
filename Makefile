.PHONY: run worker migrate seed test test-int lint eval

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

worker:
	rq worker --url $${REDIS_URL:-redis://localhost:6379/0} ats

migrate:
	alembic upgrade head

seed:
	python scripts/seed_demo.py

test:
	pytest tests/unit -v --tb=short

test-int:
	pytest tests/integration -v --tb=short -m "not local"

lint:
	ruff check app tests scripts ui
	ruff format --check app tests scripts ui

eval:
	python scripts/eval_harness.py
