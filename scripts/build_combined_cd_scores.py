from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BOUNDARIES_PATH = Path("data/geographies/community_districts.geojson")
AIR_PATH = Path("outputs/air_quality_table.csv")
SAFETY_PATH = Path("outputs/safety_quality_cd_table.csv")
WATER_PATH = Path("outputs/water_quality_table.csv")
EDUCATION_PATH = Path("outputs/education_quality_table.csv")

WATER_CD_OUTPUT = Path("outputs/water_quality_cd_table.csv")
EDUCATION_CD_OUTPUT = Path("outputs/education_quality_cd_table.csv")
COMBINED_CD_OUTPUT = Path("outputs/combined_nqi_cd_table.csv")
FRONTEND_JSON_OUTPUT = Path("frontend/data.json")


def load_cd_boundaries(path: Path) -> list[dict]:
    geojson = json.loads(path.read_text())
    boundaries: list[dict] = []

    for feature in geojson["features"]:
        props = feature.get("properties", {})
        cd_id = str(props.get("BoroCD", "")).strip()
        geometry = feature.get("geometry") or {}
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])

        polygons: list[list[list[tuple[float, float]]]] = []
        if geom_type == "Polygon":
            polygons = [normalize_polygon(coords)]
        elif geom_type == "MultiPolygon":
            polygons = [normalize_polygon(poly) for poly in coords]
        else:
            continue

        boxes = [polygon_bbox(poly) for poly in polygons]
        overall_bbox = merge_boxes(boxes)
        boundaries.append(
            {
                "id": cd_id,
                "polygons": polygons,
                "bbox": overall_bbox,
            }
        )

    return boundaries


def normalize_polygon(coords: list) -> list[list[tuple[float, float]]]:
    rings: list[list[tuple[float, float]]] = []
    for ring in coords:
        rings.append([(float(lon), float(lat)) for lon, lat in ring])
    return rings


def polygon_bbox(polygon: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for ring in polygon for x, _ in ring]
    ys = [y for ring in polygon for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def merge_boxes(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    return min_x, min_y, max_x, max_y


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False

    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]

        intersects = ((y1 > y) != (y2 > y))
        if intersects:
            x_cross = (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-15) + x1
            if x < x_cross:
                inside = not inside

    return inside


def point_in_polygon(x: float, y: float, polygon: list[list[tuple[float, float]]]) -> bool:
    if not polygon:
        return False

    if not point_in_ring(x, y, polygon[0]):
        return False

    for hole in polygon[1:]:
        if point_in_ring(x, y, hole):
            return False

    return True


def assign_cd_id(lat: float, lon: float, boundaries: list[dict]) -> str | None:
    x = float(lon)
    y = float(lat)

    for boundary in boundaries:
        min_x, min_y, max_x, max_y = boundary["bbox"]
        if x < min_x or x > max_x or y < min_y or y > max_y:
            continue

        for polygon in boundary["polygons"]:
            p_min_x, p_min_y, p_max_x, p_max_y = polygon_bbox(polygon)
            if x < p_min_x or x > p_max_x or y < p_min_y or y > p_max_y:
                continue
            if point_in_polygon(x, y, polygon):
                return boundary["id"]

    return None


def normalize_quality(series: pd.Series, higher_is_better: bool) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce")
    min_val = vals.min()
    max_val = vals.max()

    if pd.isna(min_val) or pd.isna(max_val) or max_val == min_val:
        return pd.Series([50.0] * len(vals), index=vals.index, dtype=float)

    scaled = (vals - min_val) / (max_val - min_val)
    if higher_is_better:
        return scaled * 100.0
    return (1.0 - scaled) * 100.0


def aggregate_points_to_cd(
    input_path: Path,
    score_col: str,
    output_path: Path,
    boundaries: list[dict],
    higher_is_better: bool,
    prefix: str,
) -> pd.DataFrame:
    df = pd.read_csv(input_path, low_memory=False).copy()
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df[score_col] = pd.to_numeric(df[score_col], errors="coerce")
    df = df.dropna(subset=["Latitude", "Longitude", score_col]).copy()

    df["Community_District_ID"] = [
        assign_cd_id(lat, lon, boundaries) for lat, lon in zip(df["Latitude"], df["Longitude"])
    ]
    df = df.dropna(subset=["Community_District_ID"]).copy()

    grouped = (
        df.groupby("Community_District_ID", as_index=False)
        .agg(
            Point_Count=(score_col, "size"),
            Raw_Score=(score_col, "mean"),
            Representative_Latitude=("Latitude", "median"),
            Representative_Longitude=("Longitude", "median"),
        )
        .rename(
            columns={
                "Point_Count": f"{prefix}_Point_Count",
                "Raw_Score": score_col,
                "Representative_Latitude": f"{prefix}_Representative_Latitude",
                "Representative_Longitude": f"{prefix}_Representative_Longitude",
            }
        )
    )

    grouped[f"{prefix}_QualityScore"] = normalize_quality(grouped[score_col], higher_is_better=higher_is_better)
    grouped = grouped.sort_values(f"{prefix}_QualityScore", ascending=False).reset_index(drop=True)
    grouped["Rank"] = grouped.index + 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(output_path, index=False)
    return grouped


def build_combined_table() -> None:
    boundaries = load_cd_boundaries(BOUNDARIES_PATH)

    water_cd = aggregate_points_to_cd(
        input_path=WATER_PATH,
        score_col="WaterScore",
        output_path=WATER_CD_OUTPUT,
        boundaries=boundaries,
        higher_is_better=False,
        prefix="Water",
    )
    edu_cd = aggregate_points_to_cd(
        input_path=EDUCATION_PATH,
        score_col="EducationScore",
        output_path=EDUCATION_CD_OUTPUT,
        boundaries=boundaries,
        higher_is_better=True,
        prefix="Education",
    )

    air = pd.read_csv(AIR_PATH).copy()
    air["Community_District_ID"] = air["Geo Join ID"].astype("Int64").astype(str)
    air["Community_District_Name"] = air["Geo Place Name"]
    air["Air_QualityScore"] = normalize_quality(air["AirScore"], higher_is_better=False)
    air = air[
        [
            "Community_District_ID",
            "Community_District_Name",
            "AirScore",
            "Air_QualityScore",
            "NO2",
            "O3",
            "PM2.5",
        ]
    ]

    safety = pd.read_csv(SAFETY_PATH).copy()
    safety["Community_District_ID"] = safety["Community_District_ID"].astype("Int64").astype(str)
    safety["Safety_QualityScore"] = normalize_quality(safety["SafetyScore"], higher_is_better=True)
    safety = safety[
        [
            "Community_District_ID",
            "SafetyScore",
            "Safety_QualityScore",
            "Incident_Count",
            "Weighted_Severity_Sum",
        ]
    ]

    water_cd = water_cd[
        [
            "Community_District_ID",
            "WaterScore",
            "Water_QualityScore",
            "Water_Point_Count",
        ]
    ]
    edu_cd = edu_cd[
        [
            "Community_District_ID",
            "EducationScore",
            "Education_QualityScore",
            "Education_Point_Count",
        ]
    ]

    combined = air.merge(safety, on="Community_District_ID", how="left")
    combined = combined.merge(water_cd, on="Community_District_ID", how="left")
    combined = combined.merge(edu_cd, on="Community_District_ID", how="left")

    metric_cols = [
        "Air_QualityScore",
        "Water_QualityScore",
        "Education_QualityScore",
        "Safety_QualityScore",
    ]
    combined["Overall_QualityScore"] = combined[metric_cols].mean(axis=1, skipna=True)
    combined = combined.sort_values("Overall_QualityScore", ascending=False).reset_index(drop=True)
    combined["Overall_Rank"] = combined.index + 1

    COMBINED_CD_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(COMBINED_CD_OUTPUT, index=False)

    frontend_payload = {}
    for _, row in combined.iterrows():
        cd_id = str(row["Community_District_ID"])
        frontend_payload[cd_id] = {
            "name": row["Community_District_Name"],
            "overall": round(float(row["Overall_QualityScore"]), 2) if pd.notna(row["Overall_QualityScore"]) else None,
            "air": round(float(row["Air_QualityScore"]), 2) if pd.notna(row["Air_QualityScore"]) else None,
            "water": round(float(row["Water_QualityScore"]), 2) if pd.notna(row["Water_QualityScore"]) else None,
            "edu": round(float(row["Education_QualityScore"]), 2) if pd.notna(row["Education_QualityScore"]) else None,
            "nypd": round(float(row["Safety_QualityScore"]), 2) if pd.notna(row["Safety_QualityScore"]) else None,
        }

    FRONTEND_JSON_OUTPUT.write_text(json.dumps(frontend_payload, indent=2))

    print(f"[INFO] Saved: {WATER_CD_OUTPUT}")
    print(f"[INFO] Saved: {EDUCATION_CD_OUTPUT}")
    print(f"[INFO] Saved: {COMBINED_CD_OUTPUT}")
    print(f"[INFO] Saved: {FRONTEND_JSON_OUTPUT}")
    print("\n[INFO] Top 10 combined community districts")
    print(
        combined[
            [
                "Overall_Rank",
                "Community_District_ID",
                "Community_District_Name",
                "Overall_QualityScore",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    build_combined_table()
