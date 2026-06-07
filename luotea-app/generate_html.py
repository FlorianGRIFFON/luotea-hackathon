"""Generate a standalone HTML presentation from the precomputed outputs."""
from __future__ import annotations
import base64, json, pathlib, re, subprocess, textwrap
import polars as pl
import pandas as pd

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "outputs"
FIG = OUT / "figures"
PRED = OUT / "predictions"

# --- data ------------------------------------------------------------------ #
sla = json.loads((OUT / "metrics/sla_risk_metrics.json").read_text())
summary = json.loads((OUT / "metrics/demo_summary.json").read_text())
h = summary["headline"]
ds = sla["dataset"]

ta = pl.read_parquet(PRED / "task_assignments.parquet").to_pandas()
port = pl.read_parquet(PRED / "portfolio_today.parquet").to_pandas()
crew_df = pl.read_parquet(PRED / "crew_workload.parquet").to_pandas()
unified = pl.read_parquet(PRED / "unified_sample.parquet").to_pandas()

rri = pl.read_parquet(PRED / "reliability_index.parquet").to_pandas()
rri = rri.dropna(subset=["reliability_risk_index"])
rri["signal_date"] = pd.to_datetime(rri["signal_date"])
cutoff = rri["signal_date"].max() - pd.Timedelta(days=730)
rri = rri[rri["signal_date"] >= cutoff]
rri["signal_date"] = rri["signal_date"].dt.strftime("%Y-%m-%d")
rri_chart_sites = {"site_valmet_l11", "site_aurora"}
rri_data = (rri[rri["site_id"].isin(rri_chart_sites)]
            [["site_id", "signal_date", "reliability_risk_index"]]
            .to_dict(orient="records"))

SITE_DISPLAY = {
    "site_valmet_l11": "Valmet L11",
    "site_valmet_venttiilitehdas": "Valmet Venttiilitehdas",
    "site_valmet_std": "Valmet STD",
    "site_valmet_toimistotalo": "Valmet Toimistotalo",
    "site_aurora": "Aurora",
    "site_horizon": "Horizon",
    "site_meridian": "Meridian",
}

def fmt_site(s: str) -> str:
    return SITE_DISPLAY.get(s, s.replace("site_", "").replace("_", " ").title())

# --- images ---------------------------------------------------------------- #
def img64(name: str) -> str:
    return base64.b64encode((FIG / name).read_bytes()).decode()

img_roc = img64("sla_roc_pr.png")
img_cal = img64("sla_calibration.png")
img_imp = img64("sla_feature_importance.png")

# --- graphviz diagram ------------------------------------------------------ #
DOT_SRC = r"""digraph {
  rankdir=LR; bgcolor="transparent";
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#d0d0d0"];
  edge [color="#9e9e9e"];
  subgraph cluster_src {
    label="Four worlds · four ID systems"; fontname="Helvetica"; fontsize=11;
    style=dashed; color="#bdbdbd";
    erp     [label="ERP\nalarms · work orders\nCUSTOMER_NO", fillcolor="#E3F2FD"];
    smartti [label="Smartti IoT\nenergy · CO₂\nproperty.id", fillcolor="#E8F5E9"];
    kone    [label="KONE\nelevator occupancy\nbuilding name", fillcolor="#FFF3E0"];
    clean   [label="Cleaning\nroom / desk use\nasset names", fillcolor="#F3E5F5"];
  }
  pipe [label="Medallion pipeline\nBronze → Silver → Gold\n+ QA gate", shape=box3d, fillcolor="#ECEFF1"];
  gold [label="site_daily_signals\none row per site_id × day", fillcolor="#1565C0", fontcolor="white"];
  erp -> pipe; smartti -> pipe; kone -> pipe; clean -> pipe; pipe -> gold;
}"""

result = subprocess.run(["dot", "-Tsvg"], input=DOT_SRC.encode(), capture_output=True)
pipeline_svg = result.stdout.decode()
# strip XML declaration and DOCTYPE (DOCTYPE can span two lines)
pipeline_svg = re.sub(r'<\?xml[^?]*\?>\s*', '', pipeline_svg)
pipeline_svg = re.sub(r'<!DOCTYPE[^>]*>\s*', '', pipeline_svg)

# --- helpers --------------------------------------------------------------- #
def je(obj) -> str:
    return json.dumps(obj, default=str)

def html_table(df: pd.DataFrame, style_col: str | None = None,
               style_map: dict | None = None, bold_last: bool = False) -> str:
    header = "".join(f"<th>{c}</th>" for c in df.columns)
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        bold = "font-weight:600;" if bold_last and i == len(df) - 1 else ""
        cells = []
        for c in df.columns:
            v = r[c]
            bg = ""
            if style_col and style_map and c == style_col:
                bg = f"background:{style_map.get(str(v), '')};"
            cells.append(f'<td style="{bg}{bold}">{v}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"

ACTION_BG  = {"Urgent": "#ffcdd2", "Monitor": "#fff3cd", "Low priority": "#c8e6c9"}
BAND_EMOJI = {"ELEVATED": "⚠️", "NORMAL": "🟡", "CALM": "🟢"}
BAND_BG    = {"ELEVATED": "#ffcdd2", "NORMAL": "#fff3cd", "CALM": "#c8e6c9"}

# risk queue (8 cols)
def queue_table(df: pd.DataFrame) -> str:
    cols_in  = ["wo_no","site_id","work_type_eng","assigned_to","breach_risk_pct","risk_band","severity","action"]
    cols_out = ["WO #","Site","Work type","Assigned to","Breach risk %","Risk","Severity","Action"]
    rows = []
    for _, r in df[cols_in].iterrows():
        bg = ACTION_BG.get(r["action"], "")
        rows.append(
            f"<tr>"
            f"<td>{r['wo_no']}</td>"
            f"<td>{fmt_site(r['site_id'])}</td>"
            f"<td>{r['work_type_eng']}</td>"
            f"<td>{r['assigned_to']}</td>"
            f"<td>{r['breach_risk_pct']:.1f}%</td>"
            f"<td>{r['risk_band']}</td>"
            f"<td>{r['severity']}</td>"
            f'<td style="background:{bg}">{r["action"]}</td>'
            f"</tr>"
        )
    header = "".join(f"<th>{c}</th>" for c in cols_out)
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"

# unified sample table
def unified_table(df: pd.DataFrame) -> str:
    header = "".join(f"<th>{c}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = "".join(f"<td>{'' if pd.isna(v) else v}</td>" for v in r)
        rows.append(f"<tr>{cells}</tr>")
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"

# crew workload
def crew_table(df: pd.DataFrame) -> str:
    header = "<th>Worker</th><th>Role</th><th>Tasks</th><th>Urgent</th><th>Monitor</th><th>Low priority</th>"
    rows = []
    for _, r in df.iterrows():
        rows.append(
            f"<tr><td>{r['assigned_to']}</td><td>{r['role']}</td>"
            f"<td>{r['tasks']}</td>"
            f'<td style="background:#ffcdd2">{r["urgent"]}</td>'
            f'<td style="background:#fff3cd">{r["monitor"]}</td>'
            f"<td>{r['low_priority']}</td></tr>"
        )
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"

# model comparison
def model_comp_table() -> str:
    def pick(x):
        p10 = next(p for p in x["precision_at_k"] if p["k_frac"] == 0.10)
        return {"ROC-AUC": round(x["roc_auc"], 3), "PR-AUC": round(x["pr_auc"], 3),
                "F1": round(x["f1"], 3), "Brier": round(x["brier"], 3),
                "Prec@10%": round(p10["precision"], 3)}
    models = [
        ("Majority class",              pick(sla["baselines"]["majority_class"])),
        ("Priority-rate rule (baseline)", pick(sla["baselines"]["priority_rate_rule"])),
        ("Logistic regression",         pick(sla["baselines"]["logistic_regression"])),
        ("★ HistGradientBoosting",      pick(sla["model"])),
    ]
    header = "<th>Model</th><th>ROC-AUC</th><th>PR-AUC</th><th>F1</th><th>Brier</th><th>Prec@10%</th>"
    rows = []
    for name, m in models:
        bold = "font-weight:600;" if "★" in name else ""
        rows.append(
            f'<tr style="{bold}">'
            f"<td>{name}</td><td>{m['ROC-AUC']}</td><td>{m['PR-AUC']}</td>"
            f"<td>{m['F1']}</td><td>{m['Brier']}</td><td>{m['Prec@10%']}</td></tr>"
        )
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"

# portfolio today cards
def portfolio_cards() -> str:
    cards = []
    for _, r in port.iterrows():
        emoji = BAND_EMOJI.get(r["band"], "")
        bg = BAND_BG.get(r["band"], "#fff")
        cards.append(
            f'<div class="metric-card" style="background:{bg}">'
            f'<div class="metric-label">{emoji} {fmt_site(r["site_id"])}</div>'
            f'<div class="metric-value">{r["rri"]:.0f}</div>'
            f"</div>"
        )
    return "".join(cards)

# worker options
worker_options = "".join(
    f'<option value="{w}">{w}</option>'
    for w in sorted(ta["assigned_to"].unique())
)

# =========================================================================== #
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Luotea Reliability Risk Engine</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8f9fa; color: #212529; font-size: 14px; }}
.app {{ max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.2rem 3rem; }}
h1 {{ font-size: 1.8rem; font-weight: 700; color: #1a1a2e; }}
.subtitle {{ color: #666; margin-top: 0.25rem; margin-bottom: 1.2rem; font-size: 0.93rem; }}

/* global KPIs */
.kpi-row {{ display: flex; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 1.5rem; }}
.kpi {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 1rem 1.2rem; flex: 1; min-width: 180px; }}
.kpi-value {{ font-size: 1.55rem; font-weight: 700; color: #1565c0; }}
.kpi-label {{ font-size: 0.76rem; color: #666; margin-bottom: 0.2rem; }}
.kpi-delta {{ font-size: 0.78rem; color: #2e7d32; margin-top: 0.15rem; }}

/* tabs */
.tabs {{ display: flex; border-bottom: 2px solid #dee2e6; margin-bottom: 1.5rem; overflow-x: auto; }}
.tab-btn {{ padding: 0.55rem 1.15rem; border: none; background: none; cursor: pointer; font-size: 0.93rem; color: #666; border-bottom: 3px solid transparent; margin-bottom: -2px; white-space: nowrap; }}
.tab-btn.active {{ color: #1565c0; border-bottom-color: #1565c0; font-weight: 600; }}
.tab-pane {{ display: none; }}
.tab-pane.active {{ display: block; }}

/* typography */
h2 {{ font-size: 1.15rem; font-weight: 700; margin: 1.4rem 0 0.45rem; color: #1a1a2e; }}
h3 {{ font-size: 1rem; font-weight: 600; margin: 1.1rem 0 0.35rem; }}
p {{ font-size: 0.88rem; line-height: 1.65; margin-bottom: 0.65rem; color: #444; }}
ul {{ font-size: 0.88rem; line-height: 1.65; color: #444; padding-left: 1.4rem; margin-bottom: 0.65rem; }}
ul li {{ margin-bottom: 0.25rem; }}
code {{ background: #f0f0f0; padding: 0.1em 0.35em; border-radius: 3px; font-size: 0.83em; }}
hr {{ border: none; border-top: 1px solid #dee2e6; margin: 1.3rem 0; }}
strong {{ color: #1a1a2e; }}

/* scrollable tables */
.table-wrap {{ overflow-x: auto; margin-bottom: 1rem; border: 1px solid #dee2e6; border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.81rem; background: white; }}
th {{ background: #e8eaf6; text-align: left; padding: 0.45rem 0.7rem; font-weight: 600; white-space: nowrap; border-bottom: 1px solid #c5cae9; }}
td {{ padding: 0.38rem 0.7rem; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #f5f5f5; }}
.coverage-table td, .coverage-table th {{ text-align: center; }}
.coverage-table td:first-child, .coverage-table th:first-child {{ text-align: left; }}

/* metric cards */
.metrics-row {{ display: flex; flex-wrap: wrap; gap: 0.7rem; margin: 0.7rem 0; }}
.metric-card {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 0.8rem 1rem; flex: 1; min-width: 130px; }}
.metric-value {{ font-size: 1.4rem; font-weight: 700; color: #1565c0; }}
.metric-label {{ font-size: 0.74rem; color: #555; margin-bottom: 0.15rem; }}
.metric-sub {{ font-size: 0.72rem; color: #888; margin-top: 0.1rem; }}

/* bordered container (mimics st.container(border=True)) */
.bordered-box {{ border: 1px solid #dee2e6; border-radius: 8px; padding: 1rem 1.2rem; margin: 0.8rem 0; background: white; }}
.bordered-box h3 {{ margin-top: 0; }}

/* charts */
.chart-wrap {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 1rem; margin-bottom: 0.8rem; }}
canvas {{ max-height: 370px; width: 100% !important; }}

/* images */
.fig-row {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 0.8rem 0; }}
.fig-box {{ flex: 1; min-width: 260px; background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 0.8rem; text-align: center; }}
.fig-box img {{ max-width: 100%; border-radius: 4px; }}
.fig-caption {{ font-size: 0.73rem; color: #777; margin-top: 0.4rem; }}

/* graphviz SVG */
.svg-wrap {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 0.8rem; margin: 0.8rem 0; overflow-x: auto; text-align: center; }}
.svg-wrap svg {{ max-width: 100%; height: auto; }}

/* two-column text layout */
.two-col {{ display: flex; flex-wrap: wrap; gap: 1.2rem; margin: 0.5rem 0; }}
.two-col > div {{ flex: 1; min-width: 220px; background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 0.9rem 1rem; font-size: 0.88rem; line-height: 1.6; }}

/* caption */
.caption {{ font-size: 0.76rem; color: #888; margin-top: -0.4rem; margin-bottom: 0.7rem; }}

/* worker filter */
.filter-row {{ display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.8rem; flex-wrap: wrap; }}
.filter-row select {{ padding: 0.38rem 0.6rem; border: 1px solid #ccc; border-radius: 6px; font-size: 0.9rem; }}
.filter-row label {{ font-size: 0.9rem; font-weight: 600; }}

@media (max-width: 640px) {{
  h1 {{ font-size: 1.3rem; }}
  .kpi-value, .metric-value {{ font-size: 1.15rem; }}
  .tab-btn {{ padding: 0.45rem 0.7rem; font-size: 0.82rem; }}
}}
</style>
</head>
<body>
<div class="app">

<h1>Luotea Reliability Risk Engine</h1>
<p class="subtitle">From calendar-based maintenance to <strong>data-driven reliability</strong> · <em>data → signals → decisions</em></p>

<!-- global KPIs -->
<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-label">Model ROC-AUC</div>
    <div class="kpi-value">{h['model_roc_auc']:.3f}</div>
    <div class="kpi-delta">+{h['model_roc_auc']-h['priority_rule_roc_auc']:.3f} vs rule</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Work orders scored</div>
    <div class="kpi-value">{h['n_work_orders_scored']:,}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Top-10% precision</div>
    <div class="kpi-value">{h['dispatch_top10pct_precision']*100:.0f}%</div>
    <div class="kpi-delta">base {h['test_base_rate']*100:.0f}%</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Breaches caught (top-10%)</div>
    <div class="kpi-value">{h['dispatch_top10pct_breaches_caught']:,}</div>
  </div>
</div>

<!-- tabs -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('story',this)">Story</button>
  <button class="tab-btn" onclick="switchTab('manager',this)">Manager</button>
  <button class="tab-btn" onclick="switchTab('mytasks',this)">My tasks</button>
  <button class="tab-btn" onclick="switchTab('datamodel',this)">Data &amp; model</button>
</div>

<!-- ========================================================= STORY -->
<div id="tab-story" class="tab-pane active">

  <h2>The problem: four worlds that were never built to be joined</h2>
  <p>Luotea's facility data comes from <strong>four different worlds that were never designed to be joined</strong>. Each one has its own format, its own grain, and its own idea of an <em>identity</em>:</p>

  <div class="table-wrap">
    <table>
      <thead><tr><th>World</th><th>Format</th><th>Identity</th></tr></thead>
      <tbody>
        <tr><td><strong>ERP</strong> (alarms, work orders, maintenance)</td><td>CSV (cp1252, <code>;</code>-delimited)</td><td><code>CUSTOMER_NO</code>, <code>CUSTOMER_SITE_NO</code></td></tr>
        <tr><td><strong>Smartti IoT</strong> (energy, CO₂, temperature)</td><td>nested JSON</td><td><code>property.id</code>, <code>node.id</code></td></tr>
        <tr><td><strong>KONE</strong> (elevator occupancy)</td><td>JSON arrays</td><td>building name</td></tr>
        <tr><td><strong>Cleaning</strong> (room / desk utilization)</td><td>wide CSV</td><td>asset names (<code>K2</code>, <code>Letto</code>, …)</td></tr>
      </tbody>
    </table>
  </div>

  <p>On top of that, the raw files are messy: odd text encodings, literal <code>"NULL"</code> strings, Finnish dates, free text, mixed time zones.</p>

  <hr>
  <h2>What we built first: one canonical model</h2>
  <p>Before any machine learning, we built a <strong>medallion pipeline</strong> (Bronze, Silver, Gold) that ingests all six source families, cleans them, and <strong>joins every world onto one canonical <code>site_id</code></strong>, behind an automated QA gate (row counts, key uniqueness, PII scan).</p>

  <div class="svg-wrap">
    {pipeline_svg}
  </div>

  <p><strong>The result: one Parquet table, <code>site_daily_signals</code>, joined on <code>site_id</code>:</strong></p>
  <div class="table-wrap">
    <table>{unified_table(unified)}</table>
  </div>

  <hr>
  <h2>What this unified data lets us build</h2>
  <p>Once every source shares <strong>one <code>site_id</code> and one daily grain</strong>, we can ask <em>forward-looking</em> questions instead of only reporting the past. Our hackathon use case:</p>

  <div class="bordered-box">
    <h3>Predicting SLA breaches before they happen</h3>
    <p>At the moment a work order is <strong>created</strong>, we predict its probability of <strong>breaching its SLA</strong>. It is a machine-learning model trained on <strong>{ds['n_total']:,} real work orders</strong> and evaluated on a <strong>future hold-out</strong> ({ds['test_period_start'][:10]} to {ds['test_period_end'][:10]}) with <strong>no leakage</strong>, so the score is a genuine forecast, not hindsight.</p>
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">Breach-risk model ROC-AUC</div>
        <div class="metric-value">{h['model_roc_auc']:.3f}</div>
        <div class="metric-sub">+{h['model_roc_auc']-h['priority_rule_roc_auc']:.3f} vs priority-rule</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Riskiest-10% precision</div>
        <div class="metric-value">{h['dispatch_top10pct_precision']*100:.0f}%</div>
        <div class="metric-sub">{h['dispatch_top10pct_breaches_caught']:,} breaches caught early</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Work orders scored</div>
        <div class="metric-value">{h['n_work_orders_scored']:,}</div>
      </div>
    </div>
  </div>

  <p><strong>What the model produces: a risk-ranked, attributed queue.</strong></p>
  <p class="caption">Every open work order, scored for SLA-breach risk and assigned to the right crew member, worst first. This is the live Manager view; drill in there to act on it.</p>
  <div class="table-wrap">
    <table>{queue_table(ta)}</table>
  </div>

  <hr>
  <h2>One number per site: the Reliability Risk Index</h2>
  <p>A manager does not want hundreds of probabilities, they want one number. The <strong>Reliability Risk Index</strong> rolls the breach prediction together with the live signals (alarms, energy, incidents) into a single <strong>0 to 100 score per site</strong>. It is a <em>now-cast</em> of operational risk: the same scale for an ERP factory and an IoT office tower, so you can tell normal variation from genuinely elevated risk and watch a whole portfolio at a glance.</p>
  <div class="chart-wrap">
    <canvas id="rriChart1"></canvas>
  </div>
  <p class="caption">Orange dashed line = elevated-risk threshold (70).</p>

  <hr>
  <h2>What actions can people take thanks to this?</h2>
  <div class="two-col">
    <div>
      <p><strong>Managers</strong> <em>(Manager tab)</em></p>
      <p>See the whole portfolio's reliability at a glance, plus a <strong>risk-ranked queue with every job attributed to the right crew member</strong>. Dispatch by risk, not by calendar.</p>
    </div>
    <div>
      <p><strong>Maintainers</strong> <em>(My tasks tab)</em></p>
      <p>A personal, risk-ordered task list with a plain reason. <strong>Act on the prediction, before the fault</strong>, instead of reacting after a complaint.</p>
    </div>
  </div>

  <hr>
  <h2>How does it scale?</h2>
  <ul>
    <li><strong>API-ready:</strong> the trained model is a saved artifact. Wrap it in a scoring endpoint and run it nightly, right after the pipeline's QA gate passes.</li>
    <li><strong>New customer = one data export plus one <code>site_id</code> mapping row, with no new model</strong> (<code>site_id</code> is already a feature, so the model generalises across sites).</li>
    <li><strong>New data source = one Silver table</strong>, and the Reliability Index picks it up automatically, re-weighting over whatever signals a site has.</li>
    <li>Trains in <strong>seconds</strong> and runs on a laptop or a phone. The same 0 to 100 index gives <strong>cross-customer benchmarking</strong> for free as more sites are onboarded.</li>
  </ul>
</div>

<!-- ========================================================= MANAGER -->
<div id="tab-manager" class="tab-pane">

  <h2>Site reliability today</h2>
  <div class="metrics-row">
    {portfolio_cards()}
  </div>

  <p><strong>Reliability over time:</strong> the trend behind today's numbers. One score per site, 0–100, same scale for every customer; pick sites to compare.</p>
  <div class="chart-wrap">
    <canvas id="rriChart2"></canvas>
  </div>
  <p class="caption">Orange dashed line = elevated-risk threshold (70).</p>

  <hr>
  <h2>Crew workload</h2>
  <div class="metrics-row">
    <div class="metric-card">
      <div class="metric-label">Urgent tasks</div>
      <div class="metric-value" style="color:#c62828">{summary['crew']['urgent_tasks']}</div>
      <div class="metric-sub">Act now: high breach risk + high severity</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Monitor tasks</div>
      <div class="metric-value" style="color:#e65100">{summary['crew']['monitor_tasks']}</div>
      <div class="metric-sub">Keep an eye on; clear if capacity allows</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total tasks</div>
      <div class="metric-value">{summary['crew']['tasks_assigned']}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Crew</div>
      <div class="metric-value">{summary['crew']['workers']}</div>
    </div>
  </div>
  <div class="table-wrap">
    <table>{crew_table(crew_df)}</table>
  </div>

  <p><strong>Risk-ranked queue (attributed)</strong> — ordered by recommended action:</p>
  <div class="table-wrap">
    <table>{queue_table(ta)}</table>
  </div>
</div>

<!-- ========================================================= MY TASKS -->
<div id="tab-mytasks" class="tab-pane">

  <h2>My tasks</h2>
  <div class="filter-row">
    <label for="workerSelect">I am:</label>
    <select id="workerSelect" onchange="filterWorker()">{worker_options}</select>
  </div>
  <div id="worker-kpis" class="metrics-row"></div>
  <div class="table-wrap">
    <table id="workerTable">
      <thead><tr><th>WO #</th><th>Site</th><th>Task</th><th>Action</th></tr></thead>
      <tbody id="workerBody"></tbody>
    </table>
  </div>
</div>

<!-- ========================================================= DATA & MODEL -->
<div id="tab-datamodel" class="tab-pane">

  <h2>One canonical model spans very different customers</h2>
  <p>Luotea's value is <strong>unifying fragmented facility data</strong>. The same Gold schema and <code>site_id</code> key carry <strong>Valmet ERP</strong> (alarms, work orders, SLA) and <strong>NovaProp IoT</strong> (Smartti energy, KONE, incidents) with honest nulls where a source is absent.<br>
  Onboarding a new customer is a new Bronze export, <strong>not</strong> a new model.</p>

  <div class="table-wrap">
    <table class="coverage-table">
      <thead><tr><th>Site</th><th>Work orders / SLA</th><th>Alarms</th><th>Energy (Smartti)</th><th>Incidents / KONE</th></tr></thead>
      <tbody>
        <tr><td>Valmet L11</td><td>✅</td><td>✅ (2025+)</td><td>—</td><td>—</td></tr>
        <tr><td>Valmet Venttiilitehdas</td><td>✅</td><td>✅</td><td>—</td><td>—</td></tr>
        <tr><td>Aurora (NovaProp)</td><td>—</td><td>—</td><td>✅</td><td>✅</td></tr>
        <tr><td>Horizon (NovaProp)</td><td>—</td><td>—</td><td>✅</td><td>✅</td></tr>
      </tbody>
    </table>
  </div>

  <hr>
  <h2>Model evaluation</h2>
  <ul>
    <li><strong>Target:</strong> <code>is_sla_violation</code> on <strong>{ds['n_total']:,}</strong> Valmet work orders (2017→2026).</li>
    <li><strong>Split:</strong> time-based, train on the past, test on <strong>{ds['test_period_start'][:10]} → {ds['test_period_end'][:10]}</strong> ({ds['n_test']:,} work orders). No shuffling, no leakage.</li>
    <li><strong>Features:</strong> {ds['n_features']} creation-time attributes only. Post-completion fields excluded by assertion.</li>
  </ul>

  <div class="table-wrap">
    <table>{model_comp_table()}</table>
  </div>

  <div class="fig-row">
    <div class="fig-box" style="flex:2;min-width:300px">
      <img src="data:image/png;base64,{img_roc}" alt="ROC &amp; PR curves">
      <div class="fig-caption">ROC &amp; Precision-Recall vs baselines</div>
    </div>
  </div>
  <div class="fig-row">
    <div class="fig-box">
      <img src="data:image/png;base64,{img_cal}" alt="Calibration">
      <div class="fig-caption">Calibration: predicted ≈ observed</div>
    </div>
    <div class="fig-box">
      <img src="data:image/png;base64,{img_imp}" alt="Feature importance">
      <div class="fig-caption">Permutation importance (held-out test)</div>
    </div>
  </div>
</div>

</div><!-- /app -->

<script>
// ---- tab switching --------------------------------------------------------
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  if (id === 'manager' && !window._mgr) {{ buildChart('rriChart2'); window._mgr = true; }}
}}

// ---- RRI chart data ------------------------------------------------------
const RRI_DATA = {je(rri_data)};
const SITE_DISPLAY = {je({k: fmt_site(k) for k in rri["site_id"].unique()})};
const TASK_DATA = {je(ta.to_dict(orient='records'))};
const ACTION_BG = {{"Urgent":"#ffcdd2","Monitor":"#fff3cd","Low priority":"#c8e6c9"}};
const COLORS = ['#1565c0','#c62828','#2e7d32','#6a1b9a','#e65100','#00695c','#4e342e'];

function buildChart(canvasId) {{
  const ctx = document.getElementById(canvasId).getContext('2d');
  const bysite = {{}};
  RRI_DATA.forEach(d => {{
    if (!bysite[d.site_id]) bysite[d.site_id] = [];
    bysite[d.site_id].push({{x: d.signal_date, y: d.reliability_risk_index}});
  }});
  const sites = Object.keys(bysite);
  const datasets = sites.map((s, i) => ({{
    label: SITE_DISPLAY[s] || s,
    data: bysite[s].sort((a,b) => a.x.localeCompare(b.x)),
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: 'transparent',
    borderWidth: 1.5, pointRadius: 0, tension: 0.3,
  }}));
  const allDates = [...new Set(RRI_DATA.map(d => d.signal_date))].sort();
  datasets.push({{
    label: 'Elevated threshold (70)',
    data: [{{x: allDates[0], y: 70}}, {{x: allDates[allDates.length-1], y: 70}}],
    borderColor: 'orange', borderDash: [6,4], borderWidth: 1.5,
    pointRadius: 0, backgroundColor: 'transparent',
  }});
  new Chart(ctx, {{
    type: 'line',
    data: {{ datasets }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ boxWidth: 14, font: {{ size: 11 }} }} }},
        tooltip: {{ callbacks: {{ label: c => `${{c.dataset.label}}: ${{c.parsed.y.toFixed(0)}}` }} }},
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 10, maxRotation: 30, font: {{ size: 10 }} }} }},
        y: {{ min: 0, max: 100, title: {{ display: true, text: 'Reliability Risk Index', font: {{ size: 11 }} }} }},
      }},
    }},
  }});
}}

// ---- My tasks ------------------------------------------------------------
function filterWorker() {{
  const who = document.getElementById('workerSelect').value;
  const mine = TASK_DATA.filter(r => r.assigned_to === who);
  const urgent = mine.filter(r => r.action === 'Urgent').length;
  const monitor = mine.filter(r => r.action === 'Monitor').length;
  document.getElementById('worker-kpis').innerHTML = `
    <div class="metric-card"><div class="metric-label">Tasks</div><div class="metric-value">${{mine.length}}</div></div>
    <div class="metric-card"><div class="metric-label">Urgent</div><div class="metric-value" style="color:#c62828">${{urgent}}</div></div>
    <div class="metric-card"><div class="metric-label">Monitor</div><div class="metric-value" style="color:#e65100">${{monitor}}</div></div>
  `;
  document.getElementById('workerBody').innerHTML = mine.map(r => `
    <tr>
      <td>${{r.wo_no}}</td>
      <td>${{(SITE_DISPLAY[r.site_id] || r.site_id)}}</td>
      <td>${{r.work_type_eng}}</td>
      <td style="background:${{ACTION_BG[r.action]||''}}">${{r.action}}</td>
    </tr>
  `).join('');
}}

document.addEventListener('DOMContentLoaded', () => {{
  buildChart('rriChart1');
  filterWorker();
}});
</script>
</body>
</html>"""

out_path = OUT / "luotea_demo.html"
out_path.write_text(html, encoding="utf-8")
print(f"Written {out_path} ({out_path.stat().st_size/1024:.0f} KB)")
