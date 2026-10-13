.PHONY: setup lint type test check live

setup:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

type:
	uv run mypy src tests

test:
	uv run pytest -m unit --cov=lgcw

check: lint type test

live:
	LGCW_LIVE=1 uv run pytest -m live
