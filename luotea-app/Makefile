# Luotea Reliability Risk Engine — one-command workflows.
# Gold/Silver Parquet is already built, so `make run` works out of the box.
#
#   make run        # ← start here: venv + deps + train + predict + test + app
#   make app        # launch the Streamlit demo (artifacts already built)
#   make demo       # verify -> train -> predict -> test  (no UI)
#   make train      # train the SLA-breach model + write metrics/figures
#   make predict    # build the Reliability Index + dispatch artifacts
#   make test       # run the test suite
#   make clean      # remove generated outputs

PYTHON  ?= .venv/bin/python
# Find Python 3.11+ — tries versioned names first, then falls back to python3/python
PYTHON3 ?= $(shell \
  for py in python3.13 python3.12 python3.11 python3 python; do \
    ok=$$($$py -c "import sys; print(sys.version_info>=(3,11))" 2>/dev/null); \
    if [ "$$ok" = "True" ]; then echo $$py; break; fi; \
  done)
export PYTHONPATH := .

.PHONY: run demo all verify pipeline train predict artifacts app test setup clean

# auto-create venv on first run
.venv/bin/python:
	@test -n "$(PYTHON3)" || (echo "ERROR: Python 3.11+ not found. Install it first:\n  Mac:   brew install python@3.11\n  Linux: sudo apt install python3.11 python3.11-venv\n  Win:   use WSL2 or https://python.org/downloads" && exit 1)
	$(PYTHON3) -m venv .venv
	.venv/bin/python -m pip install --upgrade pip -q
	.venv/bin/python -m pip install -r requirements.txt -q
	@echo "Venv ready."

run: .venv/bin/python verify train predict test app ## ← one command: build everything and open the demo

demo: .venv/bin/python verify train predict test ## full flow except the UI
	@echo ""
	@echo "Done. Launch the demo with:  make app"

all: demo

setup: .venv/bin/python ## create venv and install deps

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
