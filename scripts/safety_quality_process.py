from __future__ import annotations
import argparse
import os

INPUT_CSV = "data/NYPD_Complaint_Data_Historic.csv"
OUTPUT_DIR = "outputs"
OUTPUT_CSV = "safety_quality_table.csv"
POINTS_OUTPUT_CSV = "safety_quality_points.csv"

GEO_LEVELS = {"precinct", "borough"}

REQUIRED_COLS_BASE = [
    "BORO_NM",
    "LAW_CAT_CD",
    "CRM_ATPT_CPTD_CD",
]
OPTIONAL_COLS = [
    "CMPLNT_NUM",
    "ADDR_PCT_CD",
    "OFNS_DESC",
    "PD_DESC",
    "CMPLNT_FR_DT",
    "CMPLNT_TO_DT",
    "LOC_OF_OCCUR_DESC",
    "PREM_TYP_DESC",
    "X_COORD_CD",
    "Y_COORD_CD",
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
        .replace({"": "UNKNOWN", "NAN": "UNKNOWN", "NONE": "UNKNOWN", "(NULL)": "UNKNOWN"})
    )


def _normalize_precinct_cpu(s):
    import pandas as pd

    pct_num = pd.to_numeric(s, errors="coerce")
    pct = pct_num.round().astype("Int64").astype(str)
    return pct.replace({"<NA>": "0", "NAN": "0", "NONE": "0", "": "0"})


def _add_geo_unit_cpu(df, geo_level: str):
    boro = _normalize_geo_boro_cpu(df["BORO_NM"])
    if geo_level == "borough":
        df["Geo_Unit"] = boro
    else:
        if "ADDR_PCT_CD" not in df.columns:
            raise RuntimeError("geo-level=precinct requires ADDR_PCT_CD column")
        pct = _normalize_precinct_cpu(df["ADDR_PCT_CD"])
        df["Geo_Unit"] = boro + "-PCT-" + pct
    return df


def _compute_weights_cpu(df):
    import numpy as np

    law = df["LAW_CAT_CD"].astype(str).str.strip().str.upper().map(LAW_WEIGHT).fillna(1.0)

    atpt = (
        df["CRM_ATPT_CPTD_CD"]
        .astype(str)
        .str.strip()
        .str.upper()
        .map(ATTEMPT_FACTOR)
        .fillna(1.0)
    )

    if "OFNS_DESC" in df.columns:
        ofn = df["OFNS_DESC"].astype(str).str.upper()
        over = np.full(len(df), np.nan, dtype=float)
        for k, v in OFFENSE_OVERRIDES.items():
            mask = ofn.str.contains(k, na=False)
            over = np.where(mask, v, over)
        sev = np.where(
            np.isnan(over),
            law.to_numpy(dtype=float),
            np.maximum(law.to_numpy(dtype=float), over),
        )
        sev = df.index.to_series().map(dict(zip(df.index, sev))).astype(float)
    else:
        sev = law.astype(float)

    df["severity_weight"] = sev
    df["attempt_factor"] = atpt.astype(float)
    df["weighted_incident"] = df["severity_weight"] * df["attempt_factor"]
    return df


def _attach_clean_location_cpu(df):
    import pandas as pd

    numeric_specs = {
        "Latitude": (40.45, 40.95),
        "Longitude": (-74.30, -73.65),
        "X_COORD_CD": (900000, 1100000),
        "Y_COORD_CD": (110000, 280000),
    }

    for col, bounds in numeric_specs.items():
        if col not in df.columns:
            continue

        series = pd.to_numeric(df[col], errors="coerce")
        lo, hi = bounds
        df[col] = series.where(series.between(lo, hi, inclusive="both"))

    has_latlon = df.get("Latitude", pd.Series(index=df.index, dtype=float)).notna() & df.get(
        "Longitude", pd.Series(index=df.index, dtype=float)
    ).notna()
    has_xy = df.get("X_COORD_CD", pd.Series(index=df.index, dtype=float)).notna() & df.get(
        "Y_COORD_CD", pd.Series(index=df.index, dtype=float)
    ).notna()

    df["has_valid_point"] = has_latlon & has_xy
    return df


def _aggregate_scores_cpu(df):
    g = (
        df.groupby("Geo_Unit", as_index=False)
        .agg(
            Incident_Count=("Geo_Unit", "size"),
            Weighted_Severity_Sum=("weighted_incident", "sum"),
            Valid_Point_Count=("has_valid_point", "sum"),
            Representative_X=("X_COORD_CD", "median"),
            Representative_Y=("Y_COORD_CD", "median"),
            Representative_Latitude=("Latitude", "median"),
            Representative_Longitude=("Longitude", "median"),
        )
    )

    g["Point_Coverage_Rate"] = g["Valid_Point_Count"] / g["Incident_Count"].where(g["Incident_Count"] != 0, 1)
    return g


def _point_export_columns(df_cols):
    ordered = [
        "CMPLNT_NUM",
        "Geo_Unit",
        "BORO_NM",
        "ADDR_PCT_CD",
        "CMPLNT_FR_DT",
        "CMPLNT_TO_DT",
        "OFNS_DESC",
        "PD_DESC",
        "LOC_OF_OCCUR_DESC",
        "PREM_TYP_DESC",
        "LAW_CAT_CD",
        "CRM_ATPT_CPTD_CD",
        "severity_weight",
        "attempt_factor",
        "weighted_incident",
        "X_COORD_CD",
        "Y_COORD_CD",
        "Latitude",
        "Longitude",
        "has_valid_point",
    ]
    return [c for c in ordered if c in df_cols]


def _append_points_csv(df, outdir: str, wrote_header: bool) -> bool:
    point_cols = _point_export_columns(df.columns)
    if not point_cols:
        return wrote_header

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, POINTS_OUTPUT_CSV)
    df[point_cols].to_csv(out_csv, mode="a", header=not wrote_header, index=False)
    return True


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


def run_cpu(input_path: str, outdir: str, geo_level: str, chunksize: int, write_points: bool) -> None:
    import pandas as pd

    first = pd.read_csv(input_path, nrows=1)
    cols = list(first.columns)
    _require_columns(cols)

    use_cols = [c for c in (REQUIRED_COLS_BASE + OPTIONAL_COLS) if c in cols]

    acc = {}
    wrote_points = False

    for chunk in pd.read_csv(input_path, usecols=use_cols, chunksize=chunksize, low_memory=False):
        chunk = _add_geo_unit_cpu(chunk, geo_level)
        chunk = _compute_weights_cpu(chunk)
        chunk = _attach_clean_location_cpu(chunk)

        if write_points:
            wrote_points = _append_points_csv(chunk, outdir, wrote_points)

        part = _aggregate_scores_cpu(chunk)

        for _, r in part.iterrows():
            key = r["Geo_Unit"]
            metrics = {
                "Incident_Count": float(r["Incident_Count"]),
                "Weighted_Severity_Sum": float(r["Weighted_Severity_Sum"]),
                "Valid_Point_Count": float(r["Valid_Point_Count"]),
                "Representative_X": float(r["Representative_X"]) if pd.notna(r["Representative_X"]) else None,
                "Representative_Y": float(r["Representative_Y"]) if pd.notna(r["Representative_Y"]) else None,
                "Representative_Latitude": float(r["Representative_Latitude"])
                if pd.notna(r["Representative_Latitude"])
                else None,
                "Representative_Longitude": float(r["Representative_Longitude"])
                if pd.notna(r["Representative_Longitude"])
                else None,
            }
            if key not in acc:
                acc[key] = {
                    "Incident_Count": 0.0,
                    "Weighted_Severity_Sum": 0.0,
                    "Valid_Point_Count": 0.0,
                    "Representative_X": None,
                    "Representative_Y": None,
                    "Representative_Latitude": None,
                    "Representative_Longitude": None,
                }

            acc[key]["Incident_Count"] += metrics["Incident_Count"]
            acc[key]["Weighted_Severity_Sum"] += metrics["Weighted_Severity_Sum"]
            acc[key]["Valid_Point_Count"] += metrics["Valid_Point_Count"]

            for col in [
                "Representative_X",
                "Representative_Y",
                "Representative_Latitude",
                "Representative_Longitude",
            ]:
                if metrics[col] is not None:
                    acc[key][col] = metrics[col]

    if not acc:
        raise RuntimeError("No rows processed. Check input file and filters.")

    out = pd.DataFrame([{"Geo_Unit": key, **value} for key, value in acc.items()])
    out["Incident_Count"] = out["Incident_Count"].round().astype(int)
    out["Valid_Point_Count"] = out["Valid_Point_Count"].round().astype(int)
    out["Point_Coverage_Rate"] = out["Valid_Point_Count"] / out["Incident_Count"].where(out["Incident_Count"] != 0, 1)

    out = _finalize_table_cpu(out)

    out = out[
        [
            "Geo_Unit",
            "Incident_Count",
            "Weighted_Severity_Sum",
            "Valid_Point_Count",
            "Point_Coverage_Rate",
            "Representative_X",
            "Representative_Y",
            "Representative_Latitude",
            "Representative_Longitude",
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
    if write_points and wrote_points:
        print(f"[INFO] Saved point export: {os.path.join(outdir, POINTS_OUTPUT_CSV)}")
    print("\n[INFO] Top 5 SafetyScore areas")
    print(out[["Rank", "Geo_Unit", "SafetyScore"]].head(5).to_string(index=False))


def run_gpu(input_path: str, outdir: str, geo_level: str, write_points: bool) -> None:
    import cudf

    cdf = cudf.read_csv(input_path)
    cols = list(cdf.columns)
    _require_columns(cols)

    use_cols = [c for c in (REQUIRED_COLS_BASE + OPTIONAL_COLS) if c in cols]
    pdf = cdf[use_cols].to_pandas()

    pdf = _add_geo_unit_cpu(pdf, geo_level)
    pdf = _compute_weights_cpu(pdf)
    pdf = _attach_clean_location_cpu(pdf)

    if write_points:
        _append_points_csv(pdf, outdir, wrote_header=False)

    out_pdf = _aggregate_scores_cpu(pdf)
    out_pdf = _finalize_table_cpu(out_pdf)

    out_pdf = out_pdf[
        [
            "Geo_Unit",
            "Incident_Count",
            "Weighted_Severity_Sum",
            "Valid_Point_Count",
            "Point_Coverage_Rate",
            "Representative_X",
            "Representative_Y",
            "Representative_Latitude",
            "Representative_Longitude",
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
    if write_points:
        print(f"[INFO] Saved point export: {os.path.join(outdir, POINTS_OUTPUT_CSV)}")
    print("\n[INFO] Top 5 SafetyScore areas")
    print(out_pdf[["Rank", "Geo_Unit", "SafetyScore"]].head(5).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=INPUT_CSV, help="Path to NYPD complaints CSV")
    ap.add_argument("--outdir", default=OUTPUT_DIR, help="Output directory")
    ap.add_argument("--geo-level", default="precinct", choices=sorted(GEO_LEVELS), help="Aggregation geography")
    ap.add_argument("--chunksize", type=int, default=300000, help="CPU chunk size for large CSV")
    ap.add_argument(
        "--write-points",
        action="store_true",
        help="Also save an incident-level point file with cleaned coordinates for mapping/spatial joins",
    )
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input CSV not found: {args.input}")

    if has_gpu_stack():
        run_gpu(args.input, args.outdir, args.geo_level, args.write_points)
    else:
        print("[INFO] GPU libs not found (cudf/cupy). Running CPU fallback.")
        run_cpu(args.input, args.outdir, args.geo_level, args.chunksize, args.write_points)


if __name__ == "__main__":
    main()
