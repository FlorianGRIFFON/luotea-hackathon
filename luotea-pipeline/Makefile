.PHONY: full ingest silver gold test

DATE ?= $(shell date +%Y-%m-%d)

full:
	python -m pipeline run --full --date $(DATE)

ingest:
	python -m pipeline ingest --source all --date $(DATE)

silver:
	python -m pipeline transform --layer silver --domain all --date $(DATE)

gold:
	python -m pipeline transform --layer gold --date $(DATE)

test:
	pytest tests/unit -q
