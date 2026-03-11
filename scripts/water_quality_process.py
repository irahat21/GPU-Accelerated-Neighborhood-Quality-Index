from __future__ import annotations
import argparse
import os

INPUT_CSV = "data/Drinking_Water_Quality_Distribution_Monitoring_Data_20260218.csv"
OUTPUT_DIR = "outputs"
OUTPUT_CSV = "water_quality_table.csv"

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
    import pandas as pd

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


def run_gpu(input_path: str, outdir: str, sample_class: str) -> None:
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

    # Lower score is treated as better (fewer concentration exceedance tendencies).
    site_means = site_means.sort_values("WaterScore", ascending=True).reset_index(drop=True)
    site_means["Rank"] = site_means.index + 1

    top_n = min(10, len(site_means) // 2)
    site_means["Segment"] = "Middle"
    if top_n > 0:
        seg_col = site_means.columns.get_loc("Segment")
        site_means.iloc[:top_n, seg_col] = "Top"
        site_means.iloc[len(site_means) - top_n :, seg_col] = "Bottom"

    out_cols = [GROUP_KEY] + keep_cols + z_cols + ["WaterScore", "Rank", "Segment"]
    final_output = site_means[out_cols]

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    final_output.to_csv(out_csv, index=False)

    print("[INFO] GPU pipeline complete")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 WaterScore sites (lower is better)")
    print(final_output[["Rank", GROUP_KEY, "WaterScore"]].head(5).to_pandas())


def run_cpu(input_path: str, outdir: str, sample_class: str) -> None:
    import pandas as pd
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

    # Lower score is treated as better (fewer concentration exceedance tendencies).
    site_means = site_means.sort_values("WaterScore", ascending=True).reset_index(drop=True)
    site_means["Rank"] = np.arange(1, len(site_means) + 1)

    top_n = min(10, len(site_means) // 2)
    site_means["Segment"] = "Middle"
    if top_n > 0:
        site_means.loc[: top_n - 1, "Segment"] = "Top"
        site_means.loc[len(site_means) - top_n :, "Segment"] = "Bottom"

    out_cols = [GROUP_KEY] + keep_cols + z_cols + ["WaterScore", "Rank", "Segment"]
    final_output = site_means[out_cols]

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
    ap.add_argument("--outdir", default=OUTPUT_DIR, help="Output directory")
    ap.add_argument("--sample-class", default=TARGET_SAMPLE_CLASS, help="Sample class filter (empty to disable)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input CSV not found: {args.input}")

    if has_gpu_stack():
        run_gpu(args.input, args.outdir, args.sample_class)
    else:
        print("[INFO] GPU libs not found (cudf/cupy). Running CPU fallback.")
        run_cpu(args.input, args.outdir, args.sample_class)


if __name__ == "__main__":
    main()
