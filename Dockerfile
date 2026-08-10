# Single image for both the `app` (FastAPI) and `worker` (RQ) services — see
# docker-compose.yml, which sets the actual `command:` per service.
FROM python:3.11-slim

# tesseract-ocr: required by app/pipeline/parse.py's OCR fallback for scanned resumes.
# supervisor: only used when the container is started with supervisord.conf's command
# (see render.yaml) to run the API and the RQ worker as one process group — e.g. on
# Render's free tier, which only offers Web Services, not Background Workers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY prompts ./prompts
COPY grammars ./grammars
COPY alembic ./alembic
COPY alembic.ini ./
COPY supervisord.conf ./

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
