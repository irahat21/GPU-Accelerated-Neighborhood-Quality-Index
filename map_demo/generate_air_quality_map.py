from __future__ import annotations

import argparse
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd


DEFAULT_BOUNDARY = Path("map_demo/data/uhf42.geojson")
DEFAULT_AIR_TABLE = Path("outputs/air_quality_table.csv")
DEFAULT_OUTPUT = Path("map_demo/output/air_quality_map.html")


def load_air_scores(csv_path: Path) -> pd.DataFrame:
    air = pd.read_csv(csv_path)
    air["Geo Join ID"] = air["Geo Join ID"].astype(str).str.strip()
    if "Rank" in air.columns:
        max_rank = int(air["Rank"].max())
        air["Air Quality Rank"] = max_rank - air["Rank"].astype(int) + 1
    if "Segment" in air.columns:
        air["Air Quality Level"] = (
            air["Segment"]
            .map({"Top": "Low", "Middle": "Medium", "Bottom": "High"})
            .fillna("Medium")
        )
    return air


def find_join_column(boundaries: gpd.GeoDataFrame) -> str:
    normalized = {col.lower(): col for col in boundaries.columns}
    candidates = [
        "geoid",
        "geoid",
        "uhf_code",
        "uhfcode",
        "uhf",
        "geojoinid",
        "geo_join_id",
        "id",
    ]
    for key in candidates:
        if key in normalized:
            return normalized[key]
    raise ValueError(
        "Could not find a join column in the boundary file. "
        "Expected something like GEOID, UHF_CODE, UHF, or Geo Join ID."
    )


def build_map(boundary_path: Path, air_path: Path, output_path: Path) -> tuple[Path, int]:
    boundaries = gpd.read_file(boundary_path)
    join_col = find_join_column(boundaries)

    boundaries[join_col] = boundaries[join_col].astype(str).str.strip()
    if boundaries.crs is not None and str(boundaries.crs) != "EPSG:4326":
        boundaries = boundaries.to_crs(epsg=4326)

    air = load_air_scores(air_path)
    merged = boundaries.merge(air, left_on=join_col, right_on="Geo Join ID", how="left")

    match_count = int(merged["AirScore"].notna().sum())
    if match_count == 0:
        raise ValueError(
            "The join produced 0 matched regions. Check that the GeoJSON uses UHF42 IDs "
            "that line up with outputs/air_quality_table.csv."
        )

    union_geom = merged.geometry.union_all() if hasattr(merged.geometry, "union_all") else merged.geometry.unary_union
    center = union_geom.centroid
    fmap = folium.Map(
        location=[center.y, center.x],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
        zoom_control=True,
    )

    choropleth = folium.Choropleth(
        geo_data=merged.to_json(),
        data=merged,
        columns=[join_col, "AirScore"],
        key_on=f"feature.properties.{join_col}",
        fill_color="YlOrRd",
        fill_opacity=0.75,
        line_opacity=0.35,
        line_color="#333333",
        nan_fill_color="#d9d9d9",
        nan_fill_opacity=0.3,
        legend_name="Pollution Burden (Higher = Worse Air Quality)",
        highlight=True,
    )
    choropleth.add_to(fmap)

    tooltip_fields = [join_col]
    tooltip_aliases = ["Region ID"]
    for field, label in [
        ("Geo Place Name", "Region"),
        ("Air Quality Rank", "Air Quality Rank"),
        ("Air Quality Level", "Air Quality Level"),
        ("AirScore", "Pollution Burden"),
        ("NO2", "NO2"),
        ("O3", "O3"),
        ("PM2.5", "PM2.5"),
    ]:
        if field in merged.columns:
            tooltip_fields.append(field)
            tooltip_aliases.append(label)

    folium.GeoJson(
        merged.to_json(),
        name="Air Quality",
        style_function=lambda _: {
            "fillColor": "transparent",
            "color": "#3f3f3f",
            "weight": 1.1,
            "fillOpacity": 0,
        },
        highlight_function=lambda _: {
            "weight": 2.8,
            "color": "#111111",
            "fillOpacity": 0.15,
        },
        tooltip=folium.features.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
            labels=True,
            style=(
                "background-color: white; color: #222; font-family: Arial, sans-serif; "
                "font-size: 12px; padding: 10px; border: 1px solid #d0d0d0; border-radius: 6px;"
            ),
        ),
    ).add_to(fmap)

    title_html = """
    <div style="
        position: fixed;
        top: 14px;
        left: 50px;
        z-index: 9999;
        background: rgba(255,255,255,0.92);
        padding: 12px 16px;
        border: 1px solid #cfcfcf;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        font-family: Arial, sans-serif;
    ">
      <div style="font-size: 18px; font-weight: 700;">NYC Neighborhood Quality Index Prototype</div>
      <div style="font-size: 13px; margin-top: 4px;">Air Quality Layer by UHF42 Region</div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(title_html))

    note_html = """
    <div style="
        position: fixed;
        bottom: 22px;
        left: 50px;
        z-index: 9999;
        background: rgba(255,255,255,0.90);
        padding: 8px 12px;
        border: 1px solid #d7d7d7;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        font-family: Arial, sans-serif;
        font-size: 12px;
        color: #333333;
    ">
      Hover over a region to see its air-quality level, better-is-lower rank, and pollutant values.
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(note_html))

    minx, miny, maxx, maxy = merged.total_bounds
    fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(18, 18))
    folium.LayerControl().add_to(fmap)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(output_path)
    return output_path, match_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the first Folium air-quality map demo.")
    parser.add_argument("--boundaries", default=str(DEFAULT_BOUNDARY), help="Path to UHF42 GeoJSON")
    parser.add_argument("--air-table", default=str(DEFAULT_AIR_TABLE), help="Path to air_quality_table.csv")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    output_path, match_count = build_map(
        boundary_path=Path(args.boundaries),
        air_path=Path(args.air_table),
        output_path=Path(args.output),
    )
    print(f"[INFO] Saved map to: {output_path}")
    print(f"[INFO] Matched {match_count} air-quality regions")


if __name__ == "__main__":
    main()
