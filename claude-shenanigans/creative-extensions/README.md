# Creative extensions — Luotea Reliability Risk Engine

These are prototype-quality additions that push the hackathon submission from good to first place.
All three were evaluated; two were built.

## What's here

| Folder / File | Status | What it does |
|---|---|---|
| `api/` | ✅ **Built** | FastAPI REST layer over prediction artifacts |
| `calendar/` | ✅ **Built** | Predictive maintenance ICS calendar |

---

## 1. REST API (`api/`)

A minimal FastAPI service that makes the demo production-minded.

```bash
pip install -r creative-extensions/api/requirements.txt
uvicorn creative-extensions.api.main:app --reload --port 8000
# → Swagger UI at http://localhost:8000/docs
```

Endpoints: `GET /health` · `GET /sites` · `GET /sites/{id}/reliability` · `GET /sites/{id}/dispatch`

---

## 2. Predictive Maintenance Calendar (`calendar/`)

The star of the show. Converts SLA-breach risk scores and historical RRI patterns into an RFC 5545
`.ics` file that a facility manager can subscribe to in Outlook, Google Calendar, or iOS Calendar.

**Demo moment:** "Click download — drag into your calendar app. You now have a dynamic maintenance
schedule that reflects real risk, not a fixed annual calendar."

### Generate the calendar

```bash
# from claude-shenanigans/
PYTHONPATH=. ../luotea-pipeline/.venv/bin/python creative-extensions/calendar/generate.py
# → creative-extensions/calendar/sample_luotea_maintenance.ics (committed, works offline)
```

### Streamlit demo tab

```bash
cd creative-extensions/calendar
streamlit run demo_calendar.py
```

### What's in the calendar

| Event type | Source | Example |
|---|---|---|
| 🔴 Elevated site inspection | `portfolio_today.parquet` (ELEVATED band) | "ELEVATED RISK – Urgent inspection · Horizon Plaza" |
| ⚠️ HIGH work-order | `dispatch_today_site_valmet_l11.parquet` | "HIGH – Outdoor area maintenance · Valmet L11" |
| 🟡 MEDIUM work-order | same | "MEDIUM – Additional cleaning services · Valmet L11" |
| 📅 Projected risk window | `reliability_index.parquet` historical pattern | "Projected risk window — Meridian Tower (week 26, hist. RRI 84/100)" |

The **committed sample file** `calendar/sample_luotea_maintenance.ics` has 41 events and can be
opened immediately without running any code.

---

## Jury talking points

1. **Dynamic maintenance calendar** — directly answers the hackathon brief ("fixed calendar →
   data-driven schedule"). The calendar updates whenever new data flows in.

2. **Production-ready API** — `GET /sites/site_valmet_l11/dispatch` returns the same dispatch
   list the Streamlit app shows, but now it's a typed, documented REST endpoint a customer
   integration team can connect to.

3. **Subscribable artifact** — the `.ics` file is a *thing*, not a chart. A facility manager
   opens their phone, imports the calendar, and sees "Tuesday: HIGH RISK — start outdoor area
   maintenance today." No app install required.

4. **Cross-customer anomaly signal** (in `demo_calendar.py` expander) — Pearson correlation
   between Valmet L11 and Aurora House anomaly scores shows the platform detects platform-wide
   risk patterns that single-customer tools miss.
