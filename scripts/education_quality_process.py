from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from pyproj import Transformer


DEFAULT_INPUT = Path("/Users/darienramdass/Downloads/school_grades_final.csv")
DEFAULT_OUTPUT = Path("outputs/education_quality_table.csv")


def add_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standardize the official education results file into the project output format."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to education results CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to project output CSV")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    rename_map = {
        "Final_Weighted_Grade": "EducationScore",
    }
    df = df.rename(columns=rename_map)
    df = add_lat_lon(df)

    preferred_order = [
        "BN",
        "location_name",
        "EducationScore",
        "Average_Completeness_Score",
        "Number_of_Years",
        "Earliest_Year",
        "Latest_Year",
        "X_COORDINATE",
        "Y_COORDINATE",
        "Latitude",
        "Longitude",
        "Location_Category_Description",
    ]
    ordered_cols = [c for c in preferred_order if c in df.columns] + [
        c for c in df.columns if c not in preferred_order
    ]
    df = df[ordered_cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    with_lat_lon = int(df["Latitude"].notna().sum()) if "Latitude" in df.columns else 0
    print(f"[INFO] Saved: {output_path}")
    print(f"[INFO] Rows: {len(df)}")
    print(f"[INFO] Rows with latitude/longitude: {with_lat_lon}")
    print("\n[INFO] Top 5 Education scores")
    sample_cols = [c for c in ["BN", "EducationScore"] if c in df.columns]
    print(df[sample_cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
