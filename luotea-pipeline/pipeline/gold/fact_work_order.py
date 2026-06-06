"""Gold mart: fact_work_order enriched with work-type severity."""

from __future__ import annotations

import polars as pl

from pipeline.gold.io import load_silver

# fmt: off
WORK_TYPE_SEVERITY: dict[str, str] = {
    "Repairs and maintenance building automation":                                        "High",
    "Project services property operation and maintenance":                               "Medium",
    "Periodic maintenance heating and water systems":                                    "Medium",
    "Project services ventilation":                                                      "Medium",
    "Machine-based winter maintenance of outdoor areas":                                 "High",
    "Repairs and maintenance heating and water systems":                                 "High",
    "Repairs and maintenance Smartti":                                                   "Medium",
    "Cleaning services":                                                                 "Low",
    "Repairs and maintenance expert services":                                           "Medium",
    "Project services building automation":                                              "Medium",
    "Landscape construction services":                                                   "Low",
    "Periodic maintenance property operation and maintenance":                           "Medium",
    "Additional landscaping services":                                                   "Low",
    "Project services heating and water systems":                                        "Medium",
    "Periodic maintenance building automation":                                          "Medium",
    "Energy management":                                                                 "Medium",
    "Repairs and maintenance sprinklers and other automatic fire extinguishing equipment": "Critical",
    "Project services expert services":                                                  "Medium",
    "Additional property maintenance services":                                          "Low",
    "Winter maintenance of outdoor areas":                                               "High",
    "Project services electrical":                                                       "Medium",
    "Repairs and maintenance property operation and maintenance":                        "Medium",
    "Smartti building automation":                                                       "Medium",
    "Periodic maintenance expert services":                                              "Medium",
    "Repairs and maintenance fire safety":                                               "Critical",
    "Repairs and maintenance fire alarm systems":                                        "Critical",
    "Additional cleaning services":                                                      "Low",
    "Periodic maintenance sprinklers and other automatic fire extinguishing equipment":  "Critical",
    "Outdoor area and green area maintenance":                                           "Low",
    "Technical maintenance and operational maintenance":                                 "High",
    "Periodic maintenance electrical":                                                   "Medium",
    "Unclassified":                                                                      "Low",
    "Repairs and maintenance ventilation":                                               "High",
    "Periodic maintenance ventilation":                                                  "Medium",
    "Periodic maintenance fire safety":                                                  "Critical",
    "Periodic maintenance fire alarm systems":                                           "Critical",
    "Repairs and maintenance electrical":                                                "High",
    "Workplace and premises services":                                                   "Low",
    "Security services":                                                                 "Critical",
}
# fmt: on


def build_fact_work_order() -> pl.DataFrame:
    """Enrich silver fact_work_order with a severity column derived from work_type_eng."""
    df = load_silver("fact_work_order")
    return df.with_columns(
        pl.col("work_type_eng").replace(WORK_TYPE_SEVERITY).alias("severity")
    )
