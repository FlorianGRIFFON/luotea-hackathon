# Data Audit Report — Luotea Hackathon 2026

## Context

The hackathon challenge is **predictive maintenance**: move from calendar-driven to data-driven building operations. There are **2 real sites** (Valmet Lentokentänkatu 11, Tampere + Valmet Hakkila, Vantaa) and **3 anonymous buildings** (Aurora House, Meridian Tower, Horizon Plaza).

---

## 1. Alarms (`Alarms/alarms.csv`)

**What it is:** 18,702 alarm events from building management and fire safety systems.
**Period:** Jan 2025 – May 2026 (~17 months)
**Sites:** Toimistotalo (13,310), Venttiilitehdas (3,617), Lentokentänkatu 11 (1,536), STD tehdas (236), Warehouse (3)

**Structure:** 25 columns — timestamp, site/customer, hardware device, alarm type, priority, free-text description (Finnish), optional work order link.

**Quality issues & what to clean:**
- `LOOP` field has leading spaces (e.g. `"     1"`) — must `strip()` before use
- One `ALERT_ID` can produce multiple rows (one per location) — group by `ALERT_ID` for unique events
- `LOG_ONLY` is null for 66% of rows (null = actionable alarm, `L` = log-only)
- `WORKORDER_NO` is null for **96%** of alarms — only 4% triggered a work order, making the alarm→work order join very sparse
- `EVENT_DESCRIPTION` is in Finnish

**Missing data:** No data for Aurora/Meridian/Horizon here — their alarms come from the Smartti JSON files instead. No data before Jan 2025 (relatively short history).

**Encoding:** UTF-8 with BOM — fine with `encoding='utf-8-sig'`

---

## 2. Work Orders (`Work orders/work_orders_anonymized 1.csv`)

**What it is:** 44,265 work orders from facility management. The richest dataset — 9 years of history.
**Period:** May 2017 – June 2026
**Sites:** Venttiilitehdas (25,744), Lentokentänkatu 11 (18,330), Toimistotalo (151), STD tehdas (40)
**Service lines:** Cleaning SP (60%), Facility KIPA (17%), Property Maintenance KH (15%), Technical KT (8%)

**Structure:** 33 columns — site, contract type, work type, free-text descriptions (anonymized), timestamps, duration, SLA dates, billing flags.

**Critical issues — spec vs. reality:**

| What the spec says | What the file actually is |
|---|---|
| Comma delimiter | **Semicolon** delimiter |
| UTF-8 encoding | **Latin-1** encoding |
| ISO date format | **Finnish format** (DD.MM.YYYY HH:MM) |

> **These three issues will break any naive CSV reader.** Must use `sep=';'`, `encoding='latin-1'`, and parse dates with `dayfirst=True`.

**Missing/null by design:**
- `ASSIGNMENT_TYPE` and `PRIORITY_ID`: null for all 26,616 SP (cleaning) rows — these fields don't apply to cleaning
- `WORK_DESCRIPTION` null for 30,631 rows, `WORK_ORDER_PERFORMED_ACTION` null for 30,974 rows — sparse notes, especially for cleaning
- `PM_NO` null for 41,024 rows (all on-demand work — only scheduled EH-työ have a PM_NO)
- `WORKTIME_HOURS` null for 6,542 rows (subcontractor work, billed differently)
- `WORK_FINISHED_DAYS` null for 1,477 rows

**Data quality flags:**
- **SLA violation rate: 53.8%** — extremely high, worth investigating per service line (likely driven by SP/cleaning orders)
- `WORK_FINISHED_DAYS` can be up to 1,261 days — re-opened/long-running orders, needs outlier handling
- `NULL` appears as a **literal string** in some columns (not a proper null) — must check for this

---

## 3. Maintenance Schedule (`Maintenance schedule (EH-työt)/Scheduled maitenance plans.csv`)

**What it is:** 316 rows defining recurring maintenance activities (the "calendar" the hackathon wants to move away from).
**Sites:** Lentokentänkatu 11 (177), Venttiilitehdas (138), STD tehdas (1)

**Structure:** 22 columns — plan number, contract type, activity description (FI+EN), frequency, planned hours, status, dates.

**Critical cleaning needed:**
- **Triplicate rows**: every `PM_NO` appears **3 times** (export artifact). There are only 106 unique plans but 316 rows. Must deduplicate by `PM_NO` before any analysis.
- 37% of plans are `Obsolete` (no longer generating work orders) — filter to `Active` (198 rows / 63%) for current operations
- 28% of rows have no `INTERVAL`/`PM_INTERVAL_UNIT` — these are ad-hoc/seasonal tasks (snow removal, etc.)
- 17% missing detailed description, 13% missing `PLAN_HRS`

**Key link:** `PM_NO` joins to work orders (`PM_NO` field) to see planned vs. actual execution.

---

## 4. Need-Based Cleaning Data

### 4a. Desk Utilization (10 CSV files)

**What it is:** Daily desk occupancy (minutes used) for 176 desks at Lentokentänkatu 11.
**Period:** Jan 2024 – May 2026, split into 3-month chunks across 10 files
**Format:** Wide format — `asset` column (desk name) + one column per workday date

**Quality:**
- ~250 "missing" days in full calendar range — these are **weekends and holidays**, not gaps. Only ~628 working days are included, which is correct.
- 9 desks show all-zeros across an entire file — likely newly installed sensors or unused area
- Values represent minutes of use (0–90), but this needs confirmation

### 4b. Room Utilization (10 CSV files, same structure)

**What it is:** Daily room occupancy for 38 meeting rooms, same location and period.

### 4c. Sensor Metadata (`need-based cleaning/Valmet_sensoritiedot.xlsx`)

**What it is:** Inventory of 389 IoT sensors at Lentokentänkatu 11.

| Sensor type | Count |
|---|---|
| Occupancy (desk/room presence) | 214 |
| Distance (soap/sanitizer dispenser) | 140 |
| Counter (WC) | 31 |
| Gateway | 4 |

**All sensors are active** (`aktiivinen`), battery avg 87%.

**Massive metadata gaps:**
- `Asennuspäivä` (install date): **100% null**
- `Koordinaatti`, `Pinta-ala`, `Kapasiteetti`, `Aukiopoajat`: **100% null**
- `Tarkkuusluokka` (accuracy class): **100% null**
- Floor 22 appears for 1 sensor — likely a **typo** for floor 2
- This metadata would be needed for floor-level or zone-level analysis but is almost completely missing

**Note:** Desk sensors → desk utilization CSVs; Room sensors → room utilization CSVs. Only ~10% of the building is covered by sensors — the rest is cleaned conventionally with no data.

---

## 5. Smartti Energy & Climate Data (JSON)

**What it is:** Building energy consumption, indoor temperature, and CO2 readings for 4 properties.

| Property | Size | Readings | Incidents | Metrics | History |
|---|---|---|---|---|---|
| Aurora House | 28 MB | 179,216 | 90 | Electricity, Heating, Water, Temp, CO2 | From Feb 2021 |
| Meridian Tower | 72 MB | 422,983 | 231 | Temp, CO2 only (energy in children) | From Nov 2025 (climate) |
| Horizon Plaza | 29 MB | 190,307 | 153 | Electricity, Heating, Cooling, Water, Temp, CO2 | From 2021+ |
| Valmet Flow Control | ~165k readings | 56 incidents | Electricity, Heating, Water, Temp, CO2 | From Jan 2024 |

**Important gaps:**
- **Gross area (`gross_area_m2`) is null for all properties** — can't normalize energy by m²
- **Meridian Tower has no energy data** at parent level — electricity/heating/water live in its 3 child buildings, must merge with children
- Indoor climate data (temperature, CO2) only starts **Nov/Dec 2025** for Aurora House and Valmet FC — only ~6 months of climate history
- Energy data is hourly (`enerkey`), climate data is irregular 5–15 min intervals (`smartti_automation`)

**Alarms in Smartti:** Incidents are in Finnish (`Vikailmoitus` = fault report, `Energiansäästötoimenpide` = energy saving action). These are the alarm proxies for the anonymous buildings.

---

## 6. KONE Elevator Occupancy Data (`Smartti/kone/`)

**What it is:** Floor-by-floor hourly occupancy profiles for 3 buildings.

| Building | Floors | Rows | Variant |
|---|---|---|---|
| Aurora House | 7 (P, 1–6) | 294 | Normalized 0–10 + raw counts |
| Meridian Tower | 10 (K1, K2, 1–8) | 420 | Normalized 0–10 + raw counts |
| Horizon Plaza | 13 (P1, −1, 0–10) | 546 | Normalized 0–10 + raw counts |

**Period:** December 2025 – May 2026 (6 months only)

**Format:** Not raw time series. Each row is a `(month, weekday, floor)` triplet with 24 hourly values. This is an **averaged profile** — Monday in March across all Mondays in March — not individual days.

**Gaps:**
- December 2025 entries have `site_connection_ok = null` — no data for December
- Only available for the 3 anonymous buildings, **not for the Valmet sites**
- Only 6 months of history

---

## 7. Cleaning Robots (`Cleaning Robots/`)

**What it is:** Task logs from 2 autonomous cleaning robots at Lentokentänkatu 11.

| Robot | Tasks | Period | Avg Completion | Manual Stops |
|---|---|---|---|---|
| Phantas (vacuum) | 332 | May 2024 – Jun 2026 | 39.3% | 99 (30%) |
| Scrub 50 (wet scrubber) | 4,346 | Apr 2022 – May 2026 | 47.8% | 559 (13%) |

**Key metrics per task:** area planned vs. cleaned, duration, battery start/end, brush/filter/squeegee wear %, water usage.

**Quality issues:**
- **Low completion rates**: Phantas at 39.3% average is concerning — many tasks end early or are manually stopped. Worth investigating if this is normal or if there are robot issues.
- `Planned crystallization area`: **100% null** for both robots
- `Plan running time` and `Remarks`: null for ~47% of Scrub 50 tasks
- `Task type` null for 202 Scrub 50 rows

**Scrub 50 is the richer dataset** — 4,346 tasks vs. 332, longer history since 2022.

---

## 8. Maintenance Reports (`Huoltoraportit/`)

### Excel Summary (`Huoltoraporttien tiedot Valmetit.xlsx`)

Structured extracts from PDF reports across 3 sheets:

**KTE sheet (Technical Maintenance Reports): 395 rows**
- Report types: ~28 types — electrical safety measurements, sprinkler maintenance, ventilation, cold storage, fire alarm annual service, etc.
- Sites: Venttiilitehdas (169), Lentokentänkatu 11 (157), plus 15 more variant names for these same 2 sites
- Period: Jan 2022 – May 2026
- **Site name inconsistency**: 16 different strings for essentially 2 sites — needs normalization before grouping
- `Suositukset` (recommendations): null for 57% of rows — either no follow-up needed or not extracted
- `KP` (technician/cost center): null for 93/395 rows

**STP sheet (Cleaning Quality Inspection Reports): 90 rows**
- Periodic spot-checks of cleaning quality, scored 1–5
- Average scores by site: ~3.6–3.9/5 (satisfactory to good)
- `Toimenpiteet` (actions taken): **100% null** — column exists but nothing was extracted
- 7 site name variants for 2 sites

**KHU sheet: Empty (0 rows)**
- 12 KHU PDF reports exist for Lentokentänkatu 11 but their data was **not extracted** into the Excel

### PDF Files (418 PDFs total)

| Location | Category | Count |
|---|---|---|
| Lentokentänkatu 11 | KHU (property maintenance) | 12 |
| Lentokentänkatu 11 | KTE (technical) | 155 |
| Lentokentänkatu 11 | STP (cleaning quality) | 37 |
| Vanha Porvoontie 229 | KTE (technical) | 160 |
| Vanha Porvoontie 229 | STP (cleaning quality) | 54 |

KTE and STP PDFs have structured extracts in the Excel. The **12 KHU PDFs are raw/unextracted**.

---

## 9. Service Descriptions (`Service descriptions/`)

**What it is:** Cleaning service scope documents — room-by-room task lists and frequency schedules.
**Not time-series data** — defines what should be done (5×/week, 1×/month, etc.) per room type.
**Available for:** Lentokentänkatu 11 and Toimistotalo.
**Use:** Ground truth for "what was the contract?" — compare against actual work orders and sensor data.

---

## Cross-Dataset Join Keys

| From | To | Key |
|---|---|---|
| Alarms | Work orders | `WORKORDER_NO` ↔ `WO_NO` (4% match rate) |
| Work orders | Maintenance schedule | `PM_NO` ↔ `PM_NO` (only EH-työ orders) |
| All Valmet datasets | Site identification | `CUSTOMER_NO` + `CUSTOMER_SITE_NO` |
| Sensor metadata | Desk/room utilization CSVs | `Nimi` (sensor name) ↔ `asset` (column) |
| Smartti incidents | Work orders | Manual match only (no shared ID) |

---

## Availability Map

| Dataset | Lentokentänkatu 11 | Venttiilitehdas | Toimistotalo | STD tehdas | Aurora / Meridian / Horizon |
|---|---|---|---|---|---|
| Alarms | ✅ 1,536 | ✅ 3,617 | ✅ 13,310 | ✅ 236 | ✅ via Smartti JSON |
| Work orders | ✅ 18,330 | ✅ 25,744 | ✅ 151 | ✅ 40 | ❌ |
| Maintenance schedule | ✅ 177 plans | ✅ 138 plans | ❌ | ✅ 1 plan | ❌ |
| Maintenance reports | ✅ PDFs + Excel | ✅ PDFs + Excel | ❌ | ❌ | ❌ |
| Desk/room utilization | ✅ 176 desks + 38 rooms | ❌ | ❌ | ❌ | ❌ |
| Sensor metadata | ✅ 389 sensors | ❌ | ❌ | ❌ | ❌ |
| Cleaning robots | ✅ 2 robots | ❌ | ❌ | ❌ | ❌ |
| Smartti energy/climate | ❌ | ✅ (Venttiilitehdas) | ❌ | ❌ | ✅ full |
| KONE elevator occupancy | ❌ | ❌ | ❌ | ❌ | ✅ (anon only) |

---

## Summary of What Needs Cleaning

| Issue | Dataset | Action |
|---|---|---|
| Semicolon delimiter (not comma) | Work orders | `sep=';'` |
| Latin-1 encoding (not UTF-8) | Work orders | `encoding='latin-1'` |
| Finnish date format DD.MM.YYYY | Work orders | `dayfirst=True` |
| Literal `"NULL"` strings in columns | Work orders | Replace with `NaN` |
| Triplicate rows (same PM_NO 3×) | Maintenance schedule | Deduplicate by `PM_NO` |
| Leading spaces in LOOP field | Alarms | `.str.strip()` |
| Site name has 16 variants for 2 sites | Maintenance reports (KTE) | Normalize with mapping dict |
| Floor 22 typo (likely floor 2) | Sensor metadata | Manual fix |
| All metadata columns 100% null | Sensor metadata | Accept — not recoverable |
| Empty KHU Excel sheet | Maintenance reports | Extract from 12 PDFs if needed |
| Obsolete maintenance plans | Maintenance schedule | Filter `OBJSTATE == 'Active'` |

---

## Recommended Priorities for the Hackathon

Given the quality and richness of the data, here's what to prioritize:

**1. Alarms + Work orders + Maintenance schedule**
The cleanest combo for technical predictive maintenance. Analyze: which alarm types precede work orders, which equipment has escalating alarm frequency, which maintenance plans have poor SLA compliance (53.8% violations!). These 3 datasets join directly.

**2. Desk/Room utilization + Cleaning work orders + Robot logs**
Strong combo for usage-based cleaning at Lentokentänkatu 11. You can show: clean when needed (high utilization) not on a fixed schedule. The CSVs cover Jan 2024–May 2026 at desk and room level resolution.

**3. Smartti JSON**
Richest energy/climate dataset for the anonymous buildings (5 years of hourly data from 2021). Good for energy anomaly detection or comfort-driven maintenance signals. Needs JSON parsing but the structure is clean and well-documented.

**Avoid as primary data:**
- KHU PDFs — unextracted, would require NLP/OCR
- KONE elevator data — only 5 months, averaged profiles (not daily records)
- STD tehdas — too sparse across all datasets (40 work orders, 1 maintenance plan, 236 alarms)
