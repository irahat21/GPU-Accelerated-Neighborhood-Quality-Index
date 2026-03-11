from __future__ import annotations
import argparse
import os

INPUT_CSV = "data/Air_Quality_20260217.csv"
OUTPUT_DIR = "outputs"
OUTPUT_CSV = "air_quality_table.csv"

TARGET_INDICATORS = {
    "Nitrogen dioxide (NO2)": "NO2",
    "Fine particles (PM 2.5)": "PM2.5",
    "Ozone (O3)": "O3",
}


def has_gpu_stack() -> bool:
    try:
        import cudf  # noqa: F401
        import cupy  # noqa: F401
        return True
    except Exception:
        return False


def normalize_indicator_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def run_gpu(input_path: str, outdir: str) -> None:
    import cudf
    import cupy as cp

    df = cudf.read_csv(input_path)
    if "Message" in df.columns:
        df = df.drop(columns=["Message"])

    df = df[df["Geo Type Name"] == "UHF42"]
    df = df.dropna(subset=["Name", "Geo Join ID", "Geo Place Name", "Data Value"])

    names_cpu = df["Name"].astype("str").to_pandas().map(normalize_indicator_name)
    pol_cpu = names_cpu.map(TARGET_INDICATORS)
    df["Pollutant"] = cudf.Series(pol_cpu)
    df = df.dropna(subset=["Pollutant"])

    df["Data Value"] = cudf.to_numeric(df["Data Value"], errors="coerce")
    df = df.dropna(subset=["Data Value"])

    means_long = (
        df.groupby(["Geo Join ID", "Geo Place Name", "Pollutant"])
        .agg({"Data Value": "mean"})
        .reset_index()
        .rename(columns={"Data Value": "avg_value"})
    )

    wide = means_long.pivot(
        index=["Geo Join ID", "Geo Place Name"],
        columns="Pollutant",
        values="avg_value",
    ).reset_index()

    score_cols = []
    for col in ["PM2.5", "NO2", "O3"]:
        if col in wide.columns:
            x = cp.asarray(wide[col].fillna(cp.nan).to_cupy())
            mu = cp.nanmean(x)
            sigma = cp.nanstd(x)
            z_col = f"z_{col}"
            wide[z_col] = cudf.Series((x - mu) / (sigma + 1e-12))
            score_cols.append(z_col)

    if not score_cols:
        raise RuntimeError("No pollutant columns found after filtering. Check indicator names.")

    zmat = cp.stack([cp.asarray(wide[c].fillna(cp.nan).to_cupy()) for c in score_cols], axis=1)
    wide["AirScore"] = cudf.Series(cp.nanmean(zmat, axis=1))

    wide = wide.sort_values("AirScore", ascending=False).reset_index(drop=True)
    wide["Rank"] = wide.index + 1

    top_n = min(10, len(wide) // 2)
    wide["Segment"] = "Middle"
    if top_n > 0:
        seg_col = wide.columns.get_loc("Segment")
        wide.iloc[:top_n, seg_col] = "Top"
        wide.iloc[len(wide) - top_n :, seg_col] = "Bottom"

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    wide.to_csv(out_csv, index=False)

    print("[INFO] GPU pipeline complete")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 AirScore districts")
    print(wide[["Rank", "Geo Place Name", "AirScore"]].head(5).to_pandas())


def run_cpu(input_path: str, outdir: str) -> None:
    import pandas as pd
    import numpy as np

    df = pd.read_csv(input_path)
    if "Message" in df.columns:
        df = df.drop(columns=["Message"])

    df = df[df["Geo Type Name"] == "UHF42"].copy()
    df = df.dropna(subset=["Name", "Geo Join ID", "Geo Place Name", "Data Value"])

    df["Name"] = df["Name"].astype(str).map(normalize_indicator_name)
    df["Pollutant"] = df["Name"].map(TARGET_INDICATORS)
    df = df.dropna(subset=["Pollutant"])

    df["Data Value"] = pd.to_numeric(df["Data Value"], errors="coerce")
    df = df.dropna(subset=["Data Value"])

    means_long = (
        df.groupby(["Geo Join ID", "Geo Place Name", "Pollutant"], as_index=False)["Data Value"]
        .mean()
        .rename(columns={"Data Value": "avg_value"})
    )

    wide = means_long.pivot_table(
        index=["Geo Join ID", "Geo Place Name"],
        columns="Pollutant",
        values="avg_value",
    ).reset_index()

    score_cols = []
    for col in ["PM2.5", "NO2", "O3"]:
        if col in wide.columns:
            x = wide[col].to_numpy(dtype=float)
            mu = np.nanmean(x)
            sigma = np.nanstd(x)
            z_col = f"z_{col}"
            wide[z_col] = (x - mu) / (sigma + 1e-12)
            score_cols.append(z_col)

    if not score_cols:
        raise RuntimeError("No pollutant columns found after filtering. Check indicator names.")

    wide["AirScore"] = np.nanmean(wide[score_cols].to_numpy(dtype=float), axis=1)

    wide = wide.sort_values("AirScore", ascending=False).reset_index(drop=True)
    wide["Rank"] = np.arange(1, len(wide) + 1)

    top_n = min(10, len(wide) // 2)
    wide["Segment"] = "Middle"
    if top_n > 0:
        wide.loc[: top_n - 1, "Segment"] = "Top"
        wide.loc[len(wide) - top_n :, "Segment"] = "Bottom"

    os.makedirs(outdir, exist_ok=True)
    out_csv = os.path.join(outdir, OUTPUT_CSV)
    wide.to_csv(out_csv, index=False)

    print("[INFO] CPU pipeline complete (fallback)")
    print(f"[INFO] Saved: {out_csv}")
    print("\n[INFO] Top 5 AirScore districts")
    print(wide[["Rank", "Geo Place Name", "AirScore"]].head(5).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=INPUT_CSV, help="Path to Air Quality CSV")
    ap.add_argument("--outdir", default=OUTPUT_DIR, help="Output directory")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input CSV not found: {args.input}")

    if has_gpu_stack():
        run_gpu(args.input, args.outdir)
    else:
        print("[INFO] GPU libs not found (cudf/cupy). Running CPU fallback.")
        run_cpu(args.input, args.outdir)


if __name__ == "__main__":
    main()
