FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY ev_platform ./ev_platform
COPY data ./data

RUN useradd --create-home app && chown -R app /app
USER app

# Railway injects PORT. Migrations run on boot; they are a no-op when already applied.
CMD ["sh", "-c", "python -m ev_platform.cli migrate && exec uvicorn ev_platform.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]
