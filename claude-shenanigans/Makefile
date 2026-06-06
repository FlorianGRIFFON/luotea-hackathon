# Luotea Reliability Risk Engine — one-command workflows.
# Gold/Silver Parquet is already built, so `make demo` works out of the box.
#
#   make verify     # check the pipeline's Gold data is present (read-only)
#   make train      # train the SLA-breach model + write metrics/figures
#   make predict    # build the Reliability Index + dispatch artifacts
#   make app        # launch the interactive Streamlit demo
#   make test       # run the test suite
#   make demo       # verify -> train -> predict -> test  (everything but the UI)
#
# Uses the shared luotea-pipeline venv by default; override with `make PYTHON=...`.

PYTHON ?= ../luotea-pipeline/.venv/bin/python
export PYTHONPATH := .

.PHONY: demo all verify pipeline train predict artifacts app test setup clean

demo: verify train predict test ## full flow except the UI
	@echo ""
	@echo "Done. Launch the demo with:  make app"

all: demo

setup: ## create a local venv and install pinned deps (optional; pipeline venv works too)
	python3 -m venv .venv && ./.venv/bin/pip install -U pip && ./.venv/bin/pip install -r requirements.txt

verify: ## confirm the upstream Gold data exists — does NOT run the pipeline
	@$(PYTHON) -c "from pathlib import Path; \
p=Path('../luotea-pipeline/data/gold/site_daily_signals/site_daily_signals.parquet'); \
import sys; sys.exit(0) if p.exists() else (print('MISSING Gold parquet — see pipeline target'), sys.exit(1))"
	@echo "Gold data present."

pipeline: ## (production / re-ingest only) rebuild Gold from raw via the upstream pipeline + QA gate
	@echo "Gold is already built for the hackathon — only run this to re-ingest fresh customer data:"
	@echo "    cd ../luotea-pipeline && python -m pipeline qa --date 2026-06-05"

train: verify ## train the SLA-breach model (writes model + metrics + figures)
	$(PYTHON) -m src.models.train_sla

predict: ## build Reliability Index, dispatch list, and cross-site figures
	$(PYTHON) -m src.demo.build_demo_artifacts

artifacts: predict

app: ## launch the Streamlit demo at http://localhost:8501
	$(PYTHON) -m streamlit run src/demo/app.py

test: ## run the test suite
	$(PYTHON) -m pytest tests/ -q

clean: ## remove generated outputs (keeps source)
	rm -f outputs/models/* outputs/metrics/* outputs/predictions/* outputs/figures/*
