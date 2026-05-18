from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from flask import Flask, jsonify, render_template


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
COMBINED_SCORES_PATH = PROJECT_DIR / "outputs" / "combined_nqi_cd_table.csv"
GEOGRAPHIES_DIR = PROJECT_DIR / "data" / "geographies"

CD_GEOJSON_PATH = GEOGRAPHIES_DIR / "community_districts.geojson"
NTA_GEOJSON_PATH = GEOGRAPHIES_DIR / "nta_2020.geojson"
MODZCTA_GEOJSON_PATH = GEOGRAPHIES_DIR / "modzcta.geojson"
PROJECTED_CRS = "EPSG:2263"

QUALITY_COLS = [
    "Air_QualityScore",
    "Water_QualityScore",
    "Education_QualityScore",
    "Safety_QualityScore",
]

WEIGHTED_AVG_COLS = [
    "Air_QualityScore",
    "Water_QualityScore",
    "Education_QualityScore",
    "Safety_QualityScore",
    "AirScore",
    "PM2.5",
    "NO2",
    "O3",
    "WaterScore",
    "EducationScore",
    "SafetyScore",
]

WEIGHTED_SUM_COLS = [
    "Water_Point_Count",
    "Education_Point_Count",
    "Incident_Count",
    "Weighted_Severity_Sum",
]

GEOGRAPHY_CONFIGS = {
    "community_district": {
        "label": "Community District",
        "subtitle": "by community district",
    },
    "borough": {
        "label": "Borough",
        "subtitle": "by borough",
    },
    "nta": {
        "label": "Neighborhood",
        "subtitle": "by neighborhood tabulation area",
    },
    "zip": {
        "label": "ZIP Code",
        "subtitle": "by modified zip code tabulation area",
    },
}

app = Flask(__name__)
COMBINED_DF: pd.DataFrame | None = None
CD_GDF: gpd.GeoDataFrame | None = None
MAP_PAYLOAD_CACHE: dict[str, dict] = {}


def get_borough_from_cd(cd_id: str) -> str:
    if not cd_id:
        return "Unknown"

    prefix = str(cd_id)[0]
    return {
        "1": "Manhattan",
        "2": "Bronx",
        "3": "Brooklyn",
        "4": "Queens",
        "5": "Staten Island",
    }.get(prefix, "Unknown")


def format_cd_label(cd_id: str) -> str:
    return f"CD {cd_id[0]}-{cd_id[1:]}" if len(cd_id) >= 3 else f"CD {cd_id}"


def load_combined_df() -> pd.DataFrame:
    global COMBINED_DF
    if COMBINED_DF is None:
        df = pd.read_csv(COMBINED_SCORES_PATH)
        df["Community_District_ID"] = df["Community_District_ID"].astype("Int64").astype(str)
        df["borough"] = df["Community_District_ID"].map(get_borough_from_cd)
        COMBINED_DF = df
    return COMBINED_DF.copy()


def load_cd_gdf(df: pd.DataFrame) -> gpd.GeoDataFrame:
    global CD_GDF
    if CD_GDF is None:
        gdf = gpd.read_file(CD_GEOJSON_PATH)
        gdf["Community_District_ID"] = gdf["BoroCD"].astype("Int64").astype(str)
        gdf = gdf.merge(
            df[
                [
                    "Community_District_ID",
                    "Community_District_Name",
                    "borough",
                    "Overall_QualityScore",
                    "Air_QualityScore",
                    "Water_QualityScore",
                    "Education_QualityScore",
                    "Safety_QualityScore",
                    "AirScore",
                    "PM2.5",
                    "NO2",
                    "O3",
                    "WaterScore",
                    "Water_Point_Count",
                    "EducationScore",
                    "Education_Point_Count",
                    "SafetyScore",
                    "Incident_Count",
                    "Weighted_Severity_Sum",
                    "Overall_Rank",
                ]
            ],
            on="Community_District_ID",
            how="left",
        )
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        CD_GDF = gdf
    return CD_GDF.copy()


def round_float(value: float | int | None, digits: int = 2) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def round_int(value: float | int | None) -> int | None:
    if pd.isna(value):
        return None
    return int(round(float(value)))


def build_cd_scores(df: pd.DataFrame) -> dict[str, dict]:
    scores: dict[str, dict] = {}

    for row in df.to_dict(orient="records"):
        cd_id = str(row["Community_District_ID"]).strip()
        scores[cd_id] = {
            "name": row["Community_District_Name"],
            "borough": row["borough"],
            "geography_type": "community_district",
            "code": cd_id,
            "overall": round_float(row["Overall_QualityScore"]),
            "air": round_float(row["Air_QualityScore"]),
            "water": round_float(row["Water_QualityScore"]),
            "edu": round_float(row["Education_QualityScore"]),
            "nypd": round_float(row["Safety_QualityScore"]),
            "details": {
                "overall": {
                    "rank": round_int(row["Overall_Rank"]),
                    "components_used": 4,
                    "method": "Equal average of air, water, education, and public safety quality scores",
                },
                "air": {
                    "raw_score": round_float(row["AirScore"], 3),
                    "pm25": round_float(row["PM2.5"], 3),
                    "no2": round_float(row["NO2"], 3),
                    "o3": round_float(row["O3"], 3),
                },
                "water": {
                    "raw_score": round_float(row["WaterScore"], 3),
                    "sample_sites": round_int(row["Water_Point_Count"]),
                },
                "edu": {
                    "raw_score": round_float(row["EducationScore"], 3),
                    "schools": round_int(row["Education_Point_Count"]),
                },
                "nypd": {
                    "raw_score": round_float(row["SafetyScore"], 3),
                    "incidents": round_int(row["Incident_Count"]),
                    "weighted_severity_sum": round_float(row["Weighted_Severity_Sum"], 1),
                },
            },
        }

    return scores


def build_geojson_from_gdf(gdf: gpd.GeoDataFrame, id_col: str, label_col: str) -> dict:
    out = gdf.copy()
    out["geo_id"] = out[id_col].astype(str)
    out["geo_label"] = out[label_col].astype(str)
    return json.loads(out.to_json())


def build_borough_geography(cd_gdf: gpd.GeoDataFrame) -> tuple[dict[str, dict], dict]:
    borough_gdf = cd_gdf[["borough", "geometry"]].dissolve(by="borough", as_index=False)
    geojson = build_geojson_from_gdf(borough_gdf, "borough", "borough")
    scores = build_rollup_scores(
        source_cd_gdf=cd_gdf,
        target_gdf=borough_gdf,
        target_id_col="borough",
        target_name_col="borough",
        geography_type="borough",
        method_copy="Borough rollup of community-district prototype scores.",
        detail_note=None,
    )
    return scores, geojson


def build_rollup_scores(
    source_cd_gdf: gpd.GeoDataFrame,
    target_gdf: gpd.GeoDataFrame,
    target_id_col: str,
    target_name_col: str,
    geography_type: str,
    method_copy: str,
    detail_note: str | None,
) -> dict[str, dict]:
    source = source_cd_gdf.copy()
    target = target_gdf.copy()

    source = source.to_crs(PROJECTED_CRS)
    target = target.to_crs(PROJECTED_CRS)
    target["target_area"] = target.geometry.area
    target["target_geo_id"] = target[target_id_col].astype(str)
    target["target_geo_name"] = target[target_name_col].astype(str)

    keep_cols = ["Community_District_ID", "Community_District_Name", "borough", "geometry"] + WEIGHTED_AVG_COLS + WEIGHTED_SUM_COLS
    source = source[keep_cols]
    target = target[["target_geo_id", "target_geo_name", "geometry", "target_area"]]

    intersections = gpd.overlay(source, target, how="intersection", keep_geom_type=False)
    intersections["intersection_area"] = intersections.geometry.area
    intersections = intersections[intersections["intersection_area"] > 0].copy()
    intersections["weight"] = intersections["intersection_area"] / intersections["target_area"]
    intersections = pd.DataFrame(intersections.drop(columns="geometry"))

    aggregated_rows: list[dict] = []
    for (target_id, target_name), group in intersections.groupby(["target_geo_id", "target_geo_name"], dropna=False):
        row: dict[str, object] = {
            "geo_id": str(target_id),
            "name": str(target_name),
        }

        for col in WEIGHTED_AVG_COLS:
            valid = group[group[col].notna() & group["weight"].notna() & (group["weight"] > 0)]
            row[col] = (valid[col] * valid["weight"]).sum() / valid["weight"].sum() if not valid.empty else None

        for col in WEIGHTED_SUM_COLS:
            valid = group[group[col].notna() & group["weight"].notna()]
            row[col] = (valid[col] * valid["weight"]).sum() if not valid.empty else None

        quality_values = [row[col] for col in QUALITY_COLS if row.get(col) is not None and not pd.isna(row[col])]
        row["Overall_QualityScore"] = sum(quality_values) / len(quality_values) if quality_values else None
        aggregated_rows.append(row)

    aggregated = pd.DataFrame(aggregated_rows)
    aggregated = aggregated.sort_values("Overall_QualityScore", ascending=False, na_position="last").reset_index(drop=True)
    aggregated["Overall_Rank"] = aggregated.index + 1

    scores: dict[str, dict] = {}
    for row in aggregated.to_dict(orient="records"):
        geo_id = str(row["geo_id"])
        scores[geo_id] = {
            "name": row["name"],
            "borough": row["name"] if geography_type == "borough" else None,
            "geography_type": geography_type,
            "code": geo_id,
            "overall": round_float(row["Overall_QualityScore"]),
            "air": round_float(row["Air_QualityScore"]),
            "water": round_float(row["Water_QualityScore"]),
            "edu": round_float(row["Education_QualityScore"]),
            "nypd": round_float(row["Safety_QualityScore"]),
            "details": {
                "overall": {
                    "rank": round_int(row["Overall_Rank"]),
                    "components_used": 4,
                    "method": method_copy,
                    "source_label": detail_note,
                },
                "air": {
                    "raw_score": round_float(row["AirScore"], 3),
                    "pm25": round_float(row["PM2.5"], 3),
                    "no2": round_float(row["NO2"], 3),
                    "o3": round_float(row["O3"], 3),
                },
                "water": {
                    "raw_score": round_float(row["WaterScore"], 3),
                    "sample_sites": round_int(row["Water_Point_Count"]),
                },
                "edu": {
                    "raw_score": round_float(row["EducationScore"], 3),
                    "schools": round_int(row["Education_Point_Count"]),
                },
                "nypd": {
                    "raw_score": round_float(row["SafetyScore"], 3),
                    "incidents": round_int(row["Incident_Count"]),
                    "weighted_severity_sum": round_float(row["Weighted_Severity_Sum"], 1),
                },
            },
        }
    return scores


def load_target_gdf(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    elif str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
    return gdf


def build_nta_geography(cd_gdf: gpd.GeoDataFrame) -> tuple[dict[str, dict], dict]:
    nta_gdf = load_target_gdf(NTA_GEOJSON_PATH)
    nta_gdf["nta2020"] = nta_gdf["nta2020"].astype(str)
    nta_gdf["ntaname"] = nta_gdf["ntaname"].astype(str)
    geojson = build_geojson_from_gdf(nta_gdf, "nta2020", "ntaname")
    scores = build_rollup_scores(
        source_cd_gdf=cd_gdf,
        target_gdf=nta_gdf,
        target_id_col="nta2020",
        target_name_col="ntaname",
        geography_type="nta",
        method_copy="Area-weighted rollup of community-district prototype scores onto NTA neighborhood boundaries.",
        detail_note=None,
    )
    return scores, geojson


def build_zip_geography(cd_gdf: gpd.GeoDataFrame) -> tuple[dict[str, dict], dict]:
    zip_gdf = load_target_gdf(MODZCTA_GEOJSON_PATH)
    zip_gdf["modzcta"] = zip_gdf["modzcta"].astype(str)
    zip_gdf["label"] = zip_gdf["label"].astype(str)
    zip_gdf["geo_display"] = "ZIP " + zip_gdf["modzcta"]
    geojson = build_geojson_from_gdf(zip_gdf, "modzcta", "geo_display")
    scores = build_rollup_scores(
        source_cd_gdf=cd_gdf,
        target_gdf=zip_gdf,
        target_id_col="modzcta",
        target_name_col="label",
        geography_type="zip",
        method_copy="Area-weighted rollup of community-district prototype scores onto MODZCTA ZIP boundaries.",
        detail_note="MODZCTA geography",
    )
    return scores, geojson


def build_cd_geojson(cd_gdf: gpd.GeoDataFrame) -> dict:
    out = cd_gdf[["Community_District_ID", "geometry"]].copy()
    out["cd_label"] = out["Community_District_ID"].map(format_cd_label)
    return build_geojson_from_gdf(out, "Community_District_ID", "cd_label")


def build_payload_for_geography(geography: str) -> dict:
    combined_df = load_combined_df()
    cd_gdf = load_cd_gdf(combined_df)

    if geography == "community_district":
        return {
            **GEOGRAPHY_CONFIGS["community_district"],
            "scores": build_cd_scores(combined_df),
            "geojson": build_cd_geojson(cd_gdf),
        }
    if geography == "borough":
        borough_scores, borough_geojson = build_borough_geography(cd_gdf)
        return {
            **GEOGRAPHY_CONFIGS["borough"],
            "scores": borough_scores,
            "geojson": borough_geojson,
        }
    if geography == "nta":
        nta_scores, nta_geojson = build_nta_geography(cd_gdf)
        return {
            **GEOGRAPHY_CONFIGS["nta"],
            "scores": nta_scores,
            "geojson": nta_geojson,
        }
    if geography == "zip":
        zip_scores, zip_geojson = build_zip_geography(cd_gdf)
        return {
            **GEOGRAPHY_CONFIGS["zip"],
            "scores": zip_scores,
            "geojson": zip_geojson,
        }
    raise KeyError(geography)


def get_map_payload(geography: str) -> dict | None:
    if geography not in GEOGRAPHY_CONFIGS:
        return None
    if geography not in MAP_PAYLOAD_CACHE:
        print(f"[startup] building {geography} view...")
        MAP_PAYLOAD_CACHE[geography] = build_payload_for_geography(geography)
    return MAP_PAYLOAD_CACHE[geography]


SCORES = get_map_payload("community_district")["scores"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/map")
def map_page():
    return render_template("map.html")


@app.route("/neighborhood/<district_id>/")
def neighborhood(district_id: str):
    if district_id not in SCORES:
        return render_template("404.html"), 404
    return render_template("neighborhood.html", district_id=district_id)


@app.route("/api/scores")
def get_scores():
    return jsonify(SCORES)


@app.route("/api/score/<district_id>")
def get_score(district_id: str):
    if district_id in SCORES:
        return jsonify(SCORES[district_id])
    return jsonify({"error": "Community district not found"}), 404


@app.route("/api/community-districts")
def get_community_districts():
    return jsonify(get_map_payload("community_district")["geojson"])


@app.route("/api/geographies")
def get_geographies():
    return jsonify({key: {"label": meta["label"], "subtitle": meta["subtitle"]} for key, meta in GEOGRAPHY_CONFIGS.items()})


@app.route("/api/map-data/<geography>")
def get_map_data(geography: str):
    payload = get_map_payload(geography)
    if not payload:
        return jsonify({"error": "Unknown geography"}), 404

    return jsonify(
        {
            "geography": geography,
            "label": payload["label"],
            "subtitle": payload["subtitle"],
            "scores": payload["scores"],
            "geojson": payload["geojson"],
        }
    )


@app.route("/api/listings/<district_id>")
def get_listings(district_id: str):
    district = SCORES.get(district_id, {})
    name = district.get("name", f"CD {district_id}")

    sample_listings = [
        {"price": "$2,800", "beds": 1, "baths": 1, "sqft": 650, "address": f"123 Main St, {name}"},
        {"price": "$3,500", "beds": 2, "baths": 1, "sqft": 900, "address": f"456 Park Ave, {name}"},
        {"price": "$4,200", "beds": 2, "baths": 2, "sqft": 1100, "address": f"789 Broadway, {name}"},
    ]

    return jsonify(sample_listings)


@app.route("/api/borough/<district_id>")
def get_borough(district_id: str):
    return jsonify({"borough": get_borough_from_cd(district_id)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
