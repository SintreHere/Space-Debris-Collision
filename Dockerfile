FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# $PORT is injected by Railway; falls back to 8000 for local `docker run`
CMD uvicorn conjunction.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
