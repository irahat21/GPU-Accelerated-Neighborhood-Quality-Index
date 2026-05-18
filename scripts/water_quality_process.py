from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from pyproj import Transformer

INPUT_CSV = "data/Drinking_Water_Quality_Distribution_Monitoring_Data_20260218.csv"
OUTPUT_DIR = "outputs"
OUTPUT_CSV = "water_quality_table.csv"
LOOKUP_CSV = "data/water_sampling_sites.csv"

GROUP_KEY = "Sample Site"
SAMPLE_CLASS_COL = "Sample class"
TARGET_SAMPLE_CLASS = "Compliance"

CHLORINE_COL = "Residual Free Chlorine (mg/L)"
TURBIDITY_COL = "Turbidity (NTU)"
FLUORIDE_COL = "Fluoride (mg/L)"
COLIFORM_COL = "Coliform (Quanti-Tray) (MPN /100mL)"
ECOLI_COL = "E.coli(Quanti-Tray) (MPN/100mL)"

NUMERIC_COLS = [CHLORINE_COL, TURBIDITY_COL, FLUORIDE_COL, COLIFORM_COL, ECOLI_COL]


def has_gpu_stack() -> bool:
    try:
        import cudf  # noqa: F401
        import cupy  # noqa: F401
        return True
    except Exception:
        return False


def _safe_z_from_array(x, xp):
    mu = xp.nanmean(x)
    sigma = xp.nanstd(x)
    return (x - mu) / (sigma + 1e-12)


def _to_numeric_cpu(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _replace_less_than_one_cpu(df, cols):
    for c in cols:
        if c in df.columns:
            s = df[c].astype(str).str.replace(r"^\s*<\s*1\s*$", "0.5", regex=True)
            df[c] = s
    return df


def _replace_less_than_one_gpu(df, cols):
    import cudf

    for c in cols:
        if c in df.columns:
            s_cpu = df[c].astype("str").to_pandas().str.replace(r"^\s*<\s*1\s*$", "0.5", regex=True)
            df[c] = cudf.Series(s_cpu)
    return df


def _add_lat_lon_from_xy(df: pd.DataFrame) -> pd.DataFrame:
    if "X_COORDINATE" not in df.columns or "Y_COORDINATE" not in df.columns:
        df["Latitude"] = pd.NA
        df["Longitude"] = pd.NA
        return df

    x = pd.to_numeric(df["X_COORDINATE"], errors="coerce")
    y = pd.to_numeric(df["Y_COORDINATE"], errors="coerce")

    transformer = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x.to_numpy(), y.to_numpy())

    df["Latitude"] = lat
    df["Longitude"] = lon
    df.loc[x.isna() | y.isna(), ["Latitude", "Longitude"]] = pd.NA
    return df


def _attach_lookup_if_exists(df: pd.DataFrame, lookup_path: str | None) -> pd.DataFrame:
    if not lookup_path or not os.path.exists(lookup_path):
        return df

    lookup = pd.read_csv(lookup_path, low_memory=False)
    required = ["Sample Site", "X - Coordinate", "Y - Coordinate"]
    if "Sample Site" not in lookup.columns:
        return df

    keep_cols = [c for c in required if c in lookup.columns]
    extra_cols = [c for c in ["Sample Station (SS) - Location Description"] if c in lookup.columns]
    lookup = lookup[keep_cols + extra_cols].copy()
    lookup = lookup.rename(
        columns={
            "X - Coordinate": "X_COORDINATE",
            "Y - Coordinate": "Y_COORDINATE",
            "Sample Station (SS) - Location Description": "Location_Description",
        }
    )
    lookup["Sample Site"] = lookup["Sample Site"].astype(str).str.strip()
    lookup = lookup.drop_duplicates(subset=["Sample Site"], keep="first")

    out = df.copy()
    out["Sample Site"] = out["Sample Site"].astype(str).str.strip()
    out = out.merge(lookup, on="Sample Site", how="left")
    out = _add_lat_lon_from_xy(out)
    return out


def _finalize_output(site_means: pd.DataFrame, keep_cols: list[str], lookup_path: str | None) -> pd.DataFrame:
    out_cols = [GROUP_KEY] + keep_cols + [f"z_{c}" for c in keep_cols] + ["WaterScore", "Rank", "Segment"]
    final_output = site_means[out_cols].copy()
    final_output = _attach_lookup_if_exists(final_output, lookup_path)

    preferred_cols = [
        "Sample Site",
        "Location_Description",
        "X_COORDINATE",
        "Y_COORDINATE",
        "Latitude",
        "Longitude",
        CHLORINE_COL,
        TURBIDITY_COL,
        FLUORIDE_COL,
        COLIFORM_COL,
        ECOLI_COL,
        f"z_{CHLORINE_COL}",
        f"z_{TURBIDITY_COL}",
        f"z_{FLUORIDE_COL}",
        f"z_{COLIFORM_COL}",
        f"z_{ECOLI_COL}",
        "WaterScore",
        "Rank",
        "Segment",
    ]
    ordered = [c for c in preferred_cols if c in final_output.columns] + [
        c for c in final_output.columns if c not in preferred_cols
    ]
    return final_output[ordered]


def run_gpu(input_path: str, outdir: str, sample_class: str, lookup_path: str | None) -> None:
    import cudf
    import cupy as cp

    df = cudf.read_csv(input_path)

    if SAMPLE_CLASS_COL in df.columns and sample_class:
        df = df[df[SAMPLE_CLASS_COL] == sample_class]

    df = df.dropna(subset=[GROUP_KEY])
    df = _replace_less_than_one_gpu(df, [COLIFORM_COL, ECOLI_COL])
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = cudf.to_numeric(df[c], errors="coerce")

    keep_cols = [c for c in NUMERIC_COLS if c in df.columns]
    if not keep_cols:
        raise RuntimeError("No numeric water columns found. Check input schema.")

    site_means = (
        df[[GROUP_KEY] + keep_cols]
        .groupby(GROUP_KEY)
        .agg({c: "mean" for c in keep_cols})
        .reset_index()
    )

    z_cols = []
    for c in keep_cols:
        x = cp.asarray(site_means[c].fillna(cp.nan).to_cupy())
        zc = f"z_{c}"
        site_means[zc] = cudf.Series(_safe_z_from_array(x, cp))
        z_cols.append(zc)

    zmat = cp.stack([cp.asarray(site_means[c].fillna(cp.nan).to_cupy()) for c in z_cols], axis=1)
    site_means["WaterScore"] = cudf.Series(cp.nanmean(zmat, axis=1))

    site_means = site_means.sort_values("WaterScore", ascending=True).reset_index(drop=True)
    site_means["Rank"] = site_means.index + 1

    top_n = min(10, len(site_means) // 2)
    site_means["Segment"] = "Middle"
    if top_n > 0:
        seg_col = site_means.columns.get_loc("Segment")
        site_means.iloc[:top_n, seg_col] = "Top"
        site_means.iloc[len(site_means) - top_n :, seg_col] = "Bottom"

    final_output = _finalize_output(site_means.to_pandas(), keep_cols, lookup_path)

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    final_output.to_csv(out_csv, index=False)

    print("[INFO] GPU pipeline complete")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 WaterScore sites (lower is better)")
    print(final_output[["Rank", GROUP_KEY, "WaterScore"]].head(5).to_string(index=False))


def run_cpu(input_path: str, outdir: str, sample_class: str, lookup_path: str | None) -> None:
    import numpy as np

    df = pd.read_csv(input_path, low_memory=False)

    if SAMPLE_CLASS_COL in df.columns and sample_class:
        df = df[df[SAMPLE_CLASS_COL] == sample_class]

    df = df.dropna(subset=[GROUP_KEY]).copy()
    df = _replace_less_than_one_cpu(df, [COLIFORM_COL, ECOLI_COL])
    df = _to_numeric_cpu(df, NUMERIC_COLS)

    keep_cols = [c for c in NUMERIC_COLS if c in df.columns]
    if not keep_cols:
        raise RuntimeError("No numeric water columns found. Check input schema.")

    site_means = df[[GROUP_KEY] + keep_cols].groupby(GROUP_KEY, as_index=False).mean(numeric_only=True)

    z_cols = []
    for c in keep_cols:
        x = site_means[c].to_numpy(dtype=float)
        zc = f"z_{c}"
        site_means[zc] = _safe_z_from_array(x, np)
        z_cols.append(zc)

    site_means["WaterScore"] = np.nanmean(site_means[z_cols].to_numpy(dtype=float), axis=1)

    site_means = site_means.sort_values("WaterScore", ascending=True).reset_index(drop=True)
    site_means["Rank"] = np.arange(1, len(site_means) + 1)

    top_n = min(10, len(site_means) // 2)
    site_means["Segment"] = "Middle"
    if top_n > 0:
        site_means.loc[: top_n - 1, "Segment"] = "Top"
        site_means.loc[len(site_means) - top_n :, "Segment"] = "Bottom"

    final_output = _finalize_output(site_means, keep_cols, lookup_path)

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    final_output.to_csv(out_csv, index=False)

    print("[INFO] CPU pipeline complete (fallback)")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 WaterScore sites (lower is better)")
    print(final_output[["Rank", GROUP_KEY, "WaterScore"]].head(5).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=INPUT_CSV, help="Path to Water Quality CSV")
    ap.add_argument("--lookup", default=LOOKUP_CSV, help="Optional water site lookup CSV path")
    ap.add_argument("--outdir", default=OUTPUT_DIR, help="Output directory")
    ap.add_argument("--sample-class", default=TARGET_SAMPLE_CLASS, help="Sample class filter (empty to disable)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input CSV not found: {args.input}")

    lookup_path = args.lookup if args.lookup and os.path.exists(args.lookup) else None

    if has_gpu_stack():
        run_gpu(args.input, args.outdir, args.sample_class, lookup_path)
    else:
        print("[INFO] GPU libs not found (cudf/cupy). Running CPU fallback.")
        run_cpu(args.input, args.outdir, args.sample_class, lookup_path)


if __name__ == "__main__":
    main()

