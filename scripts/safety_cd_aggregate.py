from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

DEFAULT_POINTS = Path("outputs/safety_quality_points.csv")
DEFAULT_BOUNDARIES = Path("data/geographies/community_districts.geojson")
DEFAULT_OUTPUT = Path("outputs/safety_quality_cd_table.csv")
DEFAULT_JOINED_OUTPUT = Path("outputs/safety_points_with_cd.csv")

POINT_USECOLS = [
    "CMPLNT_NUM",
    "Geo_Unit",
    "BORO_NM",
    "ADDR_PCT_CD",
    "OFNS_DESC",
    "PD_DESC",
    "LAW_CAT_CD",
    "CRM_ATPT_CPTD_CD",
    "weighted_incident",
    "Latitude",
    "Longitude",
    "has_valid_point",
]


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {col.lower().replace("_", ""): col for col in columns}
    for candidate in candidates:
        key = candidate.lower().replace("_", "")
        if key in normalized:
            return normalized[key]
    return None


def _find_cd_id_column(columns: list[str]) -> str:
    candidates = [
        "boro_cd",
        "borocd",
        "boroCD",
        "communitydistrict",
        "community_district",
        "cdta2020",
        "geoid",
        "id",
    ]
    match = _find_column(columns, candidates)
    if not match:
        raise ValueError(
            "Could not find a Community District ID column in the boundaries file. "
            "Expected something like BoroCD, BORO_CD, CommunityDistrict, or GEOID."
        )
    return match


def _find_cd_name_column(columns: list[str]) -> str | None:
    candidates = [
        "cd_name",
        "name",
        "ntaname",
        "label",
        "boro_name",
        "borough",
    ]
    return _find_column(columns, candidates)


def _load_boundaries(boundary_path: Path) -> tuple[gpd.GeoDataFrame, str, str | None]:
    boundaries = gpd.read_file(boundary_path)
    if boundaries.empty:
        raise ValueError(f"No features found in boundaries file: {boundary_path}")

    id_col = _find_cd_id_column(list(boundaries.columns))
    name_col = _find_cd_name_column(list(boundaries.columns))

    boundaries[id_col] = boundaries[id_col].astype(str).str.strip()
    boundaries = boundaries[boundaries.geometry.notna()].copy()

    if boundaries.crs is None:
        boundaries = boundaries.set_crs(epsg=4326)
    elif str(boundaries.crs) != "EPSG:4326":
        boundaries = boundaries.to_crs(epsg=4326)

    keep_cols = [id_col, "geometry"]
    if name_col:
        keep_cols.insert(1, name_col)
    boundaries = boundaries[keep_cols].copy()
    return boundaries, id_col, name_col


def _valid_points_only(chunk: pd.DataFrame) -> pd.DataFrame:
    out = chunk.copy()
    out["Latitude"] = pd.to_numeric(out["Latitude"], errors="coerce")
    out["Longitude"] = pd.to_numeric(out["Longitude"], errors="coerce")
    out["weighted_incident"] = pd.to_numeric(out["weighted_incident"], errors="coerce")

    has_flag = out["has_valid_point"].astype(str).str.strip().str.lower().isin({"true", "1"})
    coord_mask = out["Latitude"].between(40.45, 40.95, inclusive="both") & out["Longitude"].between(
        -74.30, -73.65, inclusive="both"
    )
    out = out[has_flag & coord_mask & out["weighted_incident"].notna()].copy()
    return out


def _finalize_scores(grouped: pd.DataFrame) -> pd.DataFrame:
    burden = grouped["Weighted_Severity_Sum"].to_numpy(dtype=float)
    mu = np.nanmean(burden)
    sigma = np.nanstd(burden)
    grouped["CrimeBurden_z"] = (burden - mu) / (sigma + 1e-12)
    grouped["SafetyScore"] = -grouped["CrimeBurden_z"]
    grouped = grouped.sort_values("SafetyScore", ascending=False).reset_index(drop=True)
    grouped["Rank"] = np.arange(1, len(grouped) + 1)

    top_n = min(10, len(grouped) // 2)
    grouped["Segment"] = "Middle"
    if top_n > 0:
        grouped.loc[: top_n - 1, "Segment"] = "Top"
        grouped.loc[len(grouped) - top_n :, "Segment"] = "Bottom"

    return grouped


def build_cd_safety_table(
    points_path: Path,
    boundaries_path: Path,
    output_path: Path,
    joined_output_path: Path | None = None,
    chunksize: int = 250000,
) -> tuple[Path, int]:
    if not points_path.exists():
        raise FileNotFoundError(
            f"Points file not found: {points_path}\n"
            "Run safety_quality_process.py with --write-points first."
        )
    if not boundaries_path.exists():
        raise FileNotFoundError(
            f"Community District boundary file not found: {boundaries_path}\n"
            "Place the file under data/geographies before running this step."
        )

    boundaries, id_col, name_col = _load_boundaries(boundaries_path)
    boundary_centroids = boundaries.to_crs(epsg=2263).copy()
    boundary_centroids["geometry"] = boundary_centroids.geometry.centroid
    boundary_centroids = boundary_centroids.to_crs(epsg=4326)
    boundary_centroids["Representative_Latitude"] = boundary_centroids.geometry.y
    boundary_centroids["Representative_Longitude"] = boundary_centroids.geometry.x

    grouped_parts: list[pd.DataFrame] = []
    wrote_joined = False

    for chunk in pd.read_csv(points_path, usecols=lambda c: c in POINT_USECOLS, chunksize=chunksize, low_memory=False):
        clean = _valid_points_only(chunk)
        if clean.empty:
            continue

        points_gdf = gpd.GeoDataFrame(
            clean,
            geometry=gpd.points_from_xy(clean["Longitude"], clean["Latitude"]),
            crs="EPSG:4326",
        )

        joined = gpd.sjoin(points_gdf, boundaries, how="inner", predicate="within")
        if joined.empty:
            continue

        if joined_output_path is not None:
            joined_to_write = joined.drop(columns=["geometry", "index_right"], errors="ignore").copy()
            joined_output_path.parent.mkdir(parents=True, exist_ok=True)
            joined_to_write.to_csv(joined_output_path, mode="a", header=not wrote_joined, index=False)
            wrote_joined = True

        grouped = (
            joined.groupby(id_col, as_index=False)
            .agg(Incident_Count=("CMPLNT_NUM", "count"), Weighted_Severity_Sum=("weighted_incident", "sum"))
        )
        if name_col:
            names = joined.groupby(id_col, as_index=False).agg(**{"Community_District_Name": (name_col, "first")})
            grouped = grouped.merge(names, on=id_col, how="left")

        grouped_parts.append(grouped)

    if not grouped_parts:
        raise RuntimeError("No safety incidents were matched to Community District boundaries.")

    combined = pd.concat(grouped_parts, ignore_index=True)
    grouped = (
        combined.groupby(id_col, as_index=False)
        .agg(
            Incident_Count=("Incident_Count", "sum"),
            Weighted_Severity_Sum=("Weighted_Severity_Sum", "sum"),
            **(
                {"Community_District_Name": ("Community_District_Name", "first")}
                if "Community_District_Name" in combined.columns
                else {}
            ),
        )
    )

    centroid_cols = [id_col, "Representative_Latitude", "Representative_Longitude"]
    if name_col and name_col in boundary_centroids.columns and "Community_District_Name" not in grouped.columns:
        boundary_centroids = boundary_centroids.rename(columns={name_col: "Community_District_Name"})
        centroid_cols.append("Community_District_Name")

    grouped = grouped.merge(boundary_centroids[centroid_cols].drop_duplicates(subset=[id_col]), on=id_col, how="left")
    grouped = grouped.rename(columns={id_col: "Community_District_ID"})
    grouped["Valid_Point_Count"] = grouped["Incident_Count"]
    grouped["Point_Coverage_Rate"] = 1.0

    grouped = _finalize_scores(grouped)

    ordered_cols = [
        "Community_District_ID",
        "Community_District_Name",
        "Incident_Count",
        "Weighted_Severity_Sum",
        "Valid_Point_Count",
        "Point_Coverage_Rate",
        "Representative_Latitude",
        "Representative_Longitude",
        "CrimeBurden_z",
        "SafetyScore",
        "Rank",
        "Segment",
    ]
    grouped = grouped[[c for c in ordered_cols if c in grouped.columns]]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(output_path, index=False)
    return output_path, int(grouped["Incident_Count"].sum())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign safety incident points to Community Districts and aggregate scores."
    )
    parser.add_argument("--points", default=str(DEFAULT_POINTS), help="Path to safety_quality_points.csv")
    parser.add_argument(
        "--boundaries",
        default=str(DEFAULT_BOUNDARIES),
        help="Path to Community District boundary GeoJSON or shapefile",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output Community District score table")
    parser.add_argument(
        "--joined-output",
        default=None,
        help="Optional CSV path for the incident-level file after Community District assignment",
    )
    parser.add_argument("--chunksize", type=int, default=250000, help="CSV chunksize for large incident files")
    args = parser.parse_args()

    output_path, matched_incidents = build_cd_safety_table(
        points_path=Path(args.points),
        boundaries_path=Path(args.boundaries),
        output_path=Path(args.output),
        joined_output_path=Path(args.joined_output) if args.joined_output else None,
        chunksize=args.chunksize,
    )
    print(f"[INFO] Saved Community District safety table to: {output_path}")
    print(f"[INFO] Matched incidents: {matched_incidents}")


if __name__ == "__main__":
    main()
