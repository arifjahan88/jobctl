# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 1000 jobctl && \
    useradd --uid 1000 --gid jobctl --create-home jobctl && \
    mkdir -p /app/search_results /app/data && \
    chown -R jobctl:jobctl /app

COPY pyproject.toml README.md LICENSE jobctl.example.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

USER jobctl

VOLUME ["/app/search_results", "/app/data"]

ENTRYPOINT ["jobctl"]
CMD ["run"]
