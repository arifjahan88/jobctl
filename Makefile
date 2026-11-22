.PHONY: install lint test run dry-run sources history docker-build docker-run clean

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

sources:
	$(PYTHON) -m jobctl sources

history:
	$(PYTHON) -m jobctl history

docker-build:
	docker build -t jobctl:latest .

docker-run:
	docker run --rm -v "$$(pwd)/search_results:/app/search_results" -v "$$(pwd)/data:/app/data" jobctl:latest run

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
