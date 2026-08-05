.PHONY: run worker migrate seed test test-int lint eval ui install

install:
	pip install -r requirements-torch-cpu.txt
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

ui:
	cd ui && reflex run

worker:
	rq worker --url $$(python -c 'from app.config import settings; print(settings.effective_redis_url)') ats

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
