"""Feature engineering for site_daily_signals anomaly detection."""
import numpy as np
import polars as pl
from src.config import VALMET_L11_FEATURES, AURORA_FEATURES


SITE_FEATURE_MAP = {
    "site_valmet_l11": VALMET_L11_FEATURES,
    "site_aurora": AURORA_FEATURES,
    "site_meridian": ["electricity_kwh", "heating_mwh", "avg_co2_ppm", "incident_count"],
    "site_horizon": ["electricity_kwh", "heating_mwh", "avg_co2_ppm", "incident_count"],
}

DEFAULT_FEATURES = ["alarm_count", "open_work_orders", "electricity_kwh", "heating_mwh"]


def get_feature_columns(site_id: str) -> list[str]:
    return SITE_FEATURE_MAP.get(site_id, DEFAULT_FEATURES)


def build_feature_matrix(df: pl.DataFrame, site_id: str) -> tuple[np.ndarray, pl.Series, list[str]]:
    """
    Returns (X, dates, feature_names) for the given site's daily signals.
    Only rows where ALL selected features are non-null are included.
    Uses median imputation for features with some nulls if >50% non-null.
    """
    feature_cols = get_feature_columns(site_id)
    available = [c for c in feature_cols if c in df.columns]

    sub = df.select(["signal_date"] + available)

    # For each column, use median fill if >50% non-null, else drop the column
    kept_cols = []
    for col in available:
        non_null_frac = sub[col].drop_nulls().len() / len(sub)
        if non_null_frac >= 0.3:
            kept_cols.append(col)

    sub = sub.select(["signal_date"] + kept_cols)

    # Impute remaining nulls with column median
    for col in kept_cols:
        med = sub[col].drop_nulls().median()
        if med is not None:
            sub = sub.with_columns(pl.col(col).fill_null(pl.lit(med)))

    # Drop any remaining rows with nulls
    sub = sub.drop_nulls()

    dates = sub["signal_date"]
    X = sub.select(kept_cols).to_numpy().astype(float)

    return X, dates, kept_cols


def add_calendar_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add day-of-week and month features for contextual anomaly scoring."""
    return df.with_columns([
        pl.col("signal_date").dt.weekday().alias("weekday"),
        pl.col("signal_date").dt.month().alias("month"),
        (pl.col("signal_date").dt.weekday() >= 5).alias("is_weekend"),
    ])
