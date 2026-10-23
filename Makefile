.PHONY: install test test-fast lint format benchmark benchmark-quick generate docker clean

install:
	pip install -e ".[dev,plots]"

test:
	pytest

test-fast:
	pytest -m "not slow"

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests
	ruff check --fix src tests

generate:
	qdc generate --out data/telemetry.csv

benchmark:
	qdc benchmark --config configs/default.yaml

# Small enough to finish in a couple of minutes on a laptop.
benchmark-quick:
	qdc benchmark --config configs/default.yaml --out results-quick \
		--set data.n_racks=4 --set data.n_steps=600 \
		--set benchmark.n_train=60 --set benchmark.n_test=150 \
		--set benchmark.seeds=[0] --set quantum.epochs=15

docker:
	docker build -t qdc-anomaly .

clean:
	rm -rf results results-quick results-ci data .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
