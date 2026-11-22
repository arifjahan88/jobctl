.PHONY: install lint test run dry-run daemon notify-test sources history history-clear reset-all docker-build docker-run docker-up docker-down docker-logs clean

PYTHON ?= .venv/bin/python
JOBCTL ?= .venv/bin/jobctl

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

lint:
	.venv/bin/ruff check src tests

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" || .venv/bin/pytest -q

run:
	$(PYTHON) -m jobctl run

dry-run:
	$(PYTHON) -m jobctl run --dry-run -v

daemon:
	$(PYTHON) -m jobctl daemon

notify-test:
	$(PYTHON) -m jobctl notify-test

sources:
	$(PYTHON) -m jobctl sources

history:
	$(PYTHON) -m jobctl history

history-clear:
	$(PYTHON) -m jobctl history --clear

reset-all:
	rm -f data/jobctl.db && rm -rf search_results/*

docker-build:
	docker build -t jobctl:latest .

docker-run:
	docker run --rm --env-file .env -v "$$(pwd)/search_results:/app/search_results" -v "$$(pwd)/data:/app/data" jobctl:latest run

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker logs -f jobctl-daemon

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
