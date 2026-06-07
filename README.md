# Luotea Hackathon 2026

Predictive maintenance for facility management — from calendar-based to data-driven reliability.

We built a full data pipeline and ML system on top of Luotea's real facility data: work orders, alarms, IoT sensors, cleaning robots, and elevator telemetry — all joined into a single canonical model, then used to predict SLA breaches before they happen and surface a daily Reliability Risk Index per site.

---

## Run the demo

```bash
cd claude-shenanigans
make run
```

This will create the Python environment, train the model, build all artifacts, run the tests, and open the interactive app at **http://localhost:8501**.

**Requires Python 3.11+** — install it first if needed:

| Platform | Command |
|---|---|
| Mac | `brew install python@3.11` |
| Ubuntu/Debian | `sudo apt install python3.11 python3.11-venv` |
| Windows | Download from [python.org](https://www.python.org/downloads/), then run `claude-shenanigans\setup.bat` |

For full details see [`claude-shenanigans/README.md`](./claude-shenanigans/README.md).

---

## Repository layout

```
luotea-hackathon/
├── claude-shenanigans/    ← ML engine + interactive demo (start here)
├── luotea-pipeline/       ← data pipeline: Bronze → Silver → Gold
├── luotea-data-analysis/  ← exploratory notebooks
└── Luotea-Hackathon-2026/ ← original raw data provided by Luotea
```
