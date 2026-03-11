from __future__ import annotations
import argparse
import os

INPUT_CSV = "data/NYPD_Complaint_Data_Historic.csv"
OUTPUT_DIR = "outputs"
OUTPUT_CSV = "safety_quality_table.csv"

GEO_LEVELS = {"precinct", "borough"}

REQUIRED_COLS_BASE = [
    "BORO_NM",
    "LAW_CAT_CD",
    "CRM_ATPT_CPTD_CD",
]
OPTIONAL_COLS = [
    "ADDR_PCT_CD",
    "OFNS_DESC",
    "CMPLNT_FR_DT",
    "CMPLNT_TO_DT",
    "Latitude",
    "Longitude",
]

LAW_WEIGHT = {
    "FELONY": 5.0,
    "MISDEMEANOR": 3.0,
    "VIOLATION": 1.0,
}

ATTEMPT_FACTOR = {
    "COMPLETED": 1.0,
    "ATTEMPTED": 0.7,
}

# Optional offense overrides aligned with your presentation direction.
OFFENSE_OVERRIDES = {
    "ASSAULT": 5.0,
    "ROBBERY": 4.0,
    "BURGLARY": 3.0,
    "LARCENY": 2.0,
}


def has_gpu_stack() -> bool:
    try:
        import cudf  # noqa: F401
        import cupy  # noqa: F401
        return True
    except Exception:
        return False


def _require_columns(cols):
    missing = [c for c in REQUIRED_COLS_BASE if c not in cols]
    if missing:
        raise RuntimeError(f"Missing required columns: {missing}")


def _normalize_geo_boro_cpu(s):
    return (
        s.astype(str)
        .str.strip()
        .str.upper()
        .replace({"": "UNKNOWN", "NAN": "UNKNOWN", "NONE": "UNKNOWN", "(null)": "UNKNOWN"})
    )


def _add_geo_unit_cpu(df, geo_level: str):
    boro = _normalize_geo_boro_cpu(df["BORO_NM"])
    if geo_level == "borough":
        df["Geo_Unit"] = boro
    else:
        if "ADDR_PCT_CD" not in df.columns:
            raise RuntimeError("geo-level=precinct requires ADDR_PCT_CD column")
        pct = (
            df["ADDR_PCT_CD"]
            .astype(str)
            .str.strip()
            .replace({"": "0", "NAN": "0", "NONE": "0", "(null)": "0"})
        )
        df["Geo_Unit"] = boro + "-PCT-" + pct
    return df


def _compute_weights_cpu(df):
    import numpy as np

    law = (
        df["LAW_CAT_CD"].astype(str).str.strip().str.upper().map(LAW_WEIGHT).fillna(1.0)
    )

    atpt = (
        df["CRM_ATPT_CPTD_CD"].astype(str).str.strip().str.upper().map(ATTEMPT_FACTOR).fillna(1.0)
    )

    if "OFNS_DESC" in df.columns:
        ofn = df["OFNS_DESC"].astype(str).str.upper()
        over = np.full(len(df), np.nan, dtype=float)
        for k, v in OFFENSE_OVERRIDES.items():
            mask = ofn.str.contains(k, na=False)
            over = np.where(mask, v, over)
        over_s = df.index.to_series().map(dict(zip(df.index, over))).astype(float)
        sev = np.where(np.isnan(over), law.to_numpy(dtype=float), np.maximum(law.to_numpy(dtype=float), over))
        sev = df.index.to_series().map(dict(zip(df.index, sev))).astype(float)
    else:
        sev = law.astype(float)

    df["severity_weight"] = sev
    df["attempt_factor"] = atpt.astype(float)
    df["weighted_incident"] = df["severity_weight"] * df["attempt_factor"]
    return df


def _finalize_table_cpu(g):
    import numpy as np

    x = g["Weighted_Severity_Sum"].to_numpy(dtype=float)
    mu = np.nanmean(x)
    sigma = np.nanstd(x)
    g["CrimeBurden_z"] = (x - mu) / (sigma + 1e-12)

    # Higher is safer.
    g["SafetyScore"] = -g["CrimeBurden_z"]

    g = g.sort_values("SafetyScore", ascending=False).reset_index(drop=True)
    g["Rank"] = np.arange(1, len(g) + 1)

    top_n = min(10, len(g) // 2)
    g["Segment"] = "Middle"
    if top_n > 0:
        g.loc[: top_n - 1, "Segment"] = "Top"
        g.loc[len(g) - top_n :, "Segment"] = "Bottom"

    return g


def run_cpu(input_path: str, outdir: str, geo_level: str, chunksize: int) -> None:
    import pandas as pd

    first = pd.read_csv(input_path, nrows=1)
    cols = list(first.columns)
    _require_columns(cols)

    use_cols = [c for c in (REQUIRED_COLS_BASE + OPTIONAL_COLS) if c in cols]

    acc = {}  # Geo_Unit -> [incident_count, weighted_sum]

    for chunk in pd.read_csv(input_path, usecols=use_cols, chunksize=chunksize, low_memory=False):
        chunk = _add_geo_unit_cpu(chunk, geo_level)
        chunk = _compute_weights_cpu(chunk)

        part = (
            chunk.groupby("Geo_Unit", as_index=False)
            .agg(
                Incident_Count=("Geo_Unit", "size"),
                Weighted_Severity_Sum=("weighted_incident", "sum"),
            )
        )

        for _, r in part.iterrows():
            key = r["Geo_Unit"]
            cnt = float(r["Incident_Count"])
            wsum = float(r["Weighted_Severity_Sum"])
            if key not in acc:
                acc[key] = [0.0, 0.0]
            acc[key][0] += cnt
            acc[key][1] += wsum

    if not acc:
        raise RuntimeError("No rows processed. Check input file and filters.")

    out = pd.DataFrame(
        {
            "Geo_Unit": list(acc.keys()),
            "Incident_Count": [v[0] for v in acc.values()],
            "Weighted_Severity_Sum": [v[1] for v in acc.values()],
        }
    )

    out = _finalize_table_cpu(out)

    out = out[
        [
            "Geo_Unit",
            "Incident_Count",
            "Weighted_Severity_Sum",
            "CrimeBurden_z",
            "SafetyScore",
            "Rank",
            "Segment",
        ]
    ]

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    out.to_csv(out_csv, index=False)

    print("[INFO] CPU pipeline complete (fallback)")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 SafetyScore areas")
    print(out[["Rank", "Geo_Unit", "SafetyScore"]].head(5).to_string(index=False))


def run_gpu(input_path: str, outdir: str, geo_level: str) -> None:
    import cudf

    # Read with cudf, then use pandas for robust text mapping logic.
    cdf = cudf.read_csv(input_path)
    cols = list(cdf.columns)
    _require_columns(cols)

    use_cols = [c for c in (REQUIRED_COLS_BASE + OPTIONAL_COLS) if c in cols]
    pdf = cdf[use_cols].to_pandas()

    pdf = _add_geo_unit_cpu(pdf, geo_level)
    pdf = _compute_weights_cpu(pdf)

    # Back to GPU for heavy aggregation + scoring.
    gdf = cudf.from_pandas(pdf[["Geo_Unit", "weighted_incident"]])
    out = (
        gdf.groupby("Geo_Unit")
        .agg(
            {
                "Geo_Unit": "count",
                "weighted_incident": "sum",
            }
        )
        .reset_index()
        .rename(
            columns={
                "Geo_Unit_count": "Incident_Count",
                "weighted_incident_sum": "Weighted_Severity_Sum",
            }
        )
    )

    # Convert to pandas for stable cross-env ranking behavior.
    out_pdf = out.to_pandas()
    out_pdf = _finalize_table_cpu(out_pdf)

    out_pdf = out_pdf[
        [
            "Geo_Unit",
            "Incident_Count",
            "Weighted_Severity_Sum",
            "CrimeBurden_z",
            "SafetyScore",
            "Rank",
            "Segment",
        ]
    ]

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    out_pdf.to_csv(out_csv, index=False)

    print("[INFO] GPU pipeline complete")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 SafetyScore areas")
    print(out_pdf[["Rank", "Geo_Unit", "SafetyScore"]].head(5).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=INPUT_CSV, help="Path to NYPD complaints CSV")
    ap.add_argument("--outdir", default=OUTPUT_DIR, help="Output directory")
    ap.add_argument("--geo-level", default="precinct", choices=sorted(GEO_LEVELS), help="Aggregation geography")
    ap.add_argument("--chunksize", type=int, default=300000, help="CPU chunk size for large CSV")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input CSV not found: {args.input}")

    if has_gpu_stack():
        run_gpu(args.input, args.outdir, args.geo_level)
    else:
        print("[INFO] GPU libs not found (cudf/cupy). Running CPU fallback.")
        run_cpu(args.input, args.outdir, args.geo_level, args.chunksize)


if __name__ == "__main__":
    main()
