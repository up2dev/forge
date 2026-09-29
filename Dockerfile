FROM python:3.12-slim

WORKDIR /app

# libpq-dev needed for the psycopg/asyncpg build chain in some base
# images; kept minimal since asyncpg ships its own C extension wheels
# for this platform and rarely needs it, but build-essential is cheap
# insurance against a source build on an unsupported arch.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY forge ./forge
COPY example_app ./example_app
COPY scripts ./scripts
COPY tests ./tests
COPY alembic ./alembic
COPY alembic.ini .
COPY pytest.ini .

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "example_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
