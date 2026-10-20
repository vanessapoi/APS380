# /***************************************************************************
#
#     file                 : test_apply_elevation.py
#     created              : 08 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import json
import math
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

import torcs_track_tools.cli.apply_elevation as apply_elevation
import torcs_track_tools.cli.render_terrain_elevation_diff_png as render_terrain_elevation_diff_png


def child_section(parent: ET.Element, name: str) -> ET.Element:
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    raise AssertionError(f"missing section: {name}")


def attnum(section: ET.Element, name: str) -> float:
    for child in section:
        if child.tag == "attnum" and child.get("name") == name:
            return float(child.get("val", "0"))
    raise AssertionError(f"missing attnum: {name}")


def attstr(section: ET.Element, name: str) -> str:
    for child in section:
        if child.tag == "attstr" and child.get("name") == name:
            return child.get("val", "")
    raise AssertionError(f"missing attstr: {name}")


def has_att(section: ET.Element, tag: str, name: str) -> bool:
    return any(child.tag == tag and child.get("name") == name for child in section)


def write_track(path) -> None:
    path.write_text(
        """
<params name="Elevation Unit">
  <section name="Graphic">
    <section name="Terrain Generation">
      <attstr name="elevation map" val="old-heightmap.png"/>
      <attnum name="minimum altitude" val="-10"/>
      <attnum name="maximum altitude" val="20"/>
    </section>
  </section>
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Left Side">
      <attnum name="width" unit="m" val="3"/>
    </section>
    <section name="Right Side">
      <attnum name="width" unit="m" val="3"/>
    </section>
    <section name="Left Border">
      <attnum name="width" unit="m" val="1"/>
    </section>
    <section name="Right Border">
      <attnum name="width" unit="m" val="1"/>
    </section>
    <section name="Track Segments">
      <section name="uphill">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
        <attnum name="grade" unit="%" val="5"/>
      </section>
      <section name="downhill">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def write_ascii_grid(path) -> None:
    ncols = 80
    nrows = 80
    cellsize = 10.0
    xllcorner = -300.0
    yllcorner = -300.0
    y_top = yllcorner + (nrows - 0.5) * cellsize
    rows = []
    for row in range(nrows):
        y = y_top - row * cellsize
        values = []
        for col in range(ncols):
            x = xllcorner + (col + 0.5) * cellsize
            values.append(f"{100.0 + 0.02 * x + 0.03 * y:.3f}")
        rows.append(" ".join(values))
    path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xllcorner}",
                f"yllcorner {yllcorner}",
                f"cellsize {cellsize}",
                "NODATA_value -9999",
                *rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main_track_with_width(width: float = 10.0) -> ET.Element:
    main_track = ET.Element("section", {"name": "Main Track"})
    ET.SubElement(main_track, "attnum", {"name": "width", "unit": "m", "val": str(width)})
    return main_track


def samples_from_xy(points: list[tuple[float, float]], step: float = 5.0) -> tuple[list[apply_elevation.Sample], float]:
    samples = []
    station = 0.0
    for start, end in zip(points[:-1], points[1:], strict=True):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        heading = math.atan2(dy, dx)
        if not samples:
            samples.append(apply_elevation.Sample(start[0], start[1], station, heading, "test"))
        count = max(1, int(math.ceil(length / step)))
        for i in range(1, count + 1):
            t = i / count
            samples.append(apply_elevation.Sample(start[0] + t * dx, start[1] + t * dy, station + t * length, heading, "test"))
        station += length
    return samples, station


def track_segments(root: ET.Element) -> list[ET.Element]:
    return [child for child in child_section(child_section(root, "Main Track"), "Track Segments") if child.tag == "section"]


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-apply-elevation", *args])
    return apply_elevation.main()


def run_terrain_diff_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-terrain-elevation-diff-png", *args])
    return render_terrain_elevation_diff_png.main()


def test_transform_with_fit_applies_uniform_scale() -> None:
    fit = {"c": 1.0, "s": 0.0, "ox": 10.0, "oy": -5.0, "scale": 0.5}

    assert apply_elevation.transform_with_fit(20.0, 8.0, fit) == pytest.approx((20.0, -1.0))


def test_boundary_tangents_ignore_micro_segments_at_loop_seam() -> None:
    stations = [0.0, 100.0, 200.0]
    elevations = [0.0, 10.0, 0.0]
    lengths = [100.0, 100.0, 0.015]

    tangents = apply_elevation.boundary_tangents(stations, elevations, lengths, 200.015)
    assert tangents[0] == pytest.approx(tangents[2])
    assert tangents[0] == pytest.approx(0.0)


def test_pit_station_ranges_split_wraparound_range() -> None:
    main_track = main_track_with_width()
    pits = ET.SubElement(main_track, "section", {"name": "Pits"})
    ET.SubElement(pits, "attstr", {"name": "type", "val": "pit lane"})
    ET.SubElement(pits, "attstr", {"name": "start", "val": "third"})
    ET.SubElement(pits, "attstr", {"name": "end", "val": "first"})
    segs = [ET.Element("section", {"name": name}) for name in ("first", "second", "third")]

    ranges = apply_elevation.pit_station_ranges(main_track, segs, [0.0, 40.0, 70.0], [40.0, 30.0, 50.0], 120.0)

    assert ranges == [
        {"start": 70.0, "end": 120.0, "start_segment": "third", "end_segment": "first"},
        {"start": 0.0, "end": 40.0, "start_segment": "third", "end_segment": "first"},
    ]


def test_pit_station_ranges_ignore_missing_or_disabled_pits() -> None:
    main_track = main_track_with_width()
    segs = [ET.Element("section", {"name": "a"}), ET.Element("section", {"name": "b"})]

    assert apply_elevation.pit_station_ranges(main_track, segs, [0.0, 50.0], [50.0, 50.0], 100.0) == []

    pits = ET.SubElement(main_track, "section", {"name": "Pits"})
    ET.SubElement(pits, "attstr", {"name": "type", "val": "none"})
    ET.SubElement(pits, "attstr", {"name": "start", "val": "a"})
    ET.SubElement(pits, "attstr", {"name": "end", "val": "b"})
    assert apply_elevation.pit_station_ranges(main_track, segs, [0.0, 50.0], [50.0, 50.0], 100.0) == []


def test_apply_pit_flattening_blends_to_endpoint_ramp_and_clamps_strength() -> None:
    stations = [0.0, 25.0, 50.0, 75.0, 100.0]
    elevations = [0.0, 10.0, 0.0, 20.0, 0.0]
    ranges = [{"start": 25.0, "end": 75.0}]

    full = apply_elevation.apply_pit_flattening(stations, elevations, ranges, 2.0)
    half = apply_elevation.apply_pit_flattening(stations, elevations, ranges, 0.5)

    assert full == pytest.approx([0.0, 10.0, 15.0, 20.0, 0.0])
    assert half == pytest.approx([0.0, 10.0, 7.5, 20.0, 0.0])
    assert apply_elevation.apply_pit_flattening(stations, elevations, ranges, 0.0) == elevations


def test_apply_profile_to_xml_removes_legacy_vertical_attributes() -> None:
    segs = [ET.Element("section", {"name": "first"}), ET.Element("section", {"name": "second"})]
    for seg in segs:
        ET.SubElement(seg, "attnum", {"name": "grade", "unit": "%", "val": "5"})
        ET.SubElement(seg, "attnum", {"name": "z start left", "unit": "m", "val": "1"})
        ET.SubElement(seg, "attnum", {"name": "z end right", "unit": "m", "val": "2"})
    profile = apply_elevation.BoundaryProfile([0.0, 100.0], [3.0, 5.0], [0.1, -0.2], [3.0, 5.0], [])

    apply_elevation.apply_profile_to_xml(segs, profile)

    assert attnum(segs[0], "z start") == pytest.approx(3.0)
    assert attnum(segs[0], "z end") == pytest.approx(5.0)
    assert attnum(segs[1], "z start") == pytest.approx(5.0)
    assert attnum(segs[1], "z end") == pytest.approx(3.0)
    assert attnum(segs[0], "profil start tangent") == pytest.approx(10.0)
    assert attnum(segs[0], "profil end tangent") == pytest.approx(-20.0)
    assert attstr(segs[0], "profil") == "spline"
    for seg in segs:
        assert not has_att(seg, "attnum", "grade")
        assert not has_att(seg, "attnum", "z start left")
        assert not has_att(seg, "attnum", "z end right")


def test_banking_sign_width_policy_and_clamp_are_characterized() -> None:
    source = apply_elevation.ProfileSource(
        "banking",
        [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(50.0, 80.0), apply_elevation.ProfileSample(100.0, 0.0)],
        1.0,
        100.0,
        (),
        (),
        0.0,
        True,
    )
    args = type(
        "Args",
        (),
        {
            "bank_source_sign": "auto",
            "bank_smooth_step": 10.0,
            "bank_median_window": 0.0,
            "bank_smooth_window": 0.0,
            "bank_smooth_iters": 0,
            "bank_max_abs_deg": 45.0,
            "bank_width_policy": "edge-delta",
        },
    )()

    assert apply_elevation.banking_sign_multiplier(source, args) == pytest.approx(-1.0)
    args.bank_source_sign = "preserve"
    assert apply_elevation.banking_sign_multiplier(source, args) == pytest.approx(1.0)
    args.bank_source_sign = "flip"
    assert apply_elevation.banking_sign_multiplier(source, args) == pytest.approx(-1.0)

    profile = apply_elevation.build_banking_profile([source], [], [50.0, 50.0], 100.0, args)
    assert profile is not None
    assert profile.raw_banking_deg == pytest.approx([0.0, -80.0])
    assert profile.banking_deg == pytest.approx([0.0, -45.0])

    # Disabling all filters must preserve values at boundaries that do not land
    # on the internal dense sampling grid.
    args.bank_max_abs_deg = 100.0
    profile = apply_elevation.build_banking_profile([source], [], [53.0, 47.0], 100.0, args)
    assert profile is not None
    assert profile.banking_deg == pytest.approx([0.0, -75.2])

    args.bank_source_sign = "preserve"
    with pytest.raises(SystemExit, match="edge-delta requires"):
        apply_elevation.scale_banking_for_width(30.0, 0.0, 10.0, args)
    assert apply_elevation.scale_banking_for_width(30.0, 5.0, 10.0, args) == pytest.approx(
        math.degrees(math.atan(math.tan(math.radians(30.0)) * 0.5))
    )


def test_eval_linear_wraps_before_first_and_after_last_sample() -> None:
    samples = [apply_elevation.ProfileSample(20.0, 20.0), apply_elevation.ProfileSample(80.0, 80.0)]

    assert apply_elevation.eval_linear(samples, 10.0, 100.0) == pytest.approx(35.0)
    assert apply_elevation.eval_linear(samples, 90.0, 100.0) == pytest.approx(65.0)
    assert apply_elevation.eval_linear(samples, 0.0, 0.0) == pytest.approx(20.0)


def test_update_terrain_xml_writes_and_removes_heightmap_metadata(tmp_path) -> None:
    root = ET.Element("params")
    track_xml = tmp_path / "unit.xml"
    terrain_map = apply_elevation.TerrainElevationMap(
        tmp_path / "unit-terrain-elevation.png",
        "unit-terrain-elevation.png",
        16,
        8,
        -2.0,
        5.0,
        1.25,
        (-10.0, -5.0, 10.0, 5.0),
        "profile.json",
        "terrain.asc",
        0,
    )

    relief_value = apply_elevation.update_terrain_xml(root, tmp_path / "unit-relief.ac", track_xml, terrain_map)
    terrain = child_section(child_section(root, "Graphic"), "Terrain Generation")

    assert relief_value == "unit-relief.ac"
    assert attstr(terrain, "relief file") == "unit-relief.ac"
    assert attstr(terrain, "elevation map") == "unit-terrain-elevation.png"
    assert attnum(terrain, "minimum altitude") == pytest.approx(-2.0)
    assert attnum(terrain, "maximum altitude") == pytest.approx(5.0)

    apply_elevation.update_terrain_xml(root, tmp_path / "unit-relief.ac", track_xml, None)
    assert not has_att(terrain, "attstr", "elevation map")
    assert not has_att(terrain, "attnum", "minimum altitude")
    assert not has_att(terrain, "attnum", "maximum altitude")


def test_terrain_map_path_resolution_and_profile_selection(tmp_path) -> None:
    profile = tmp_path / "profile.json"
    raster = tmp_path / "terrain.asc"
    raster.write_text("placeholder", encoding="utf-8")
    profile.write_text(
        json.dumps(
            {
                "raster": "terrain.asc",
                "zero_elevation_m": 12.5,
                "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 3.0, "offset_y": -4.0, "scale": 2.0},
                "samples": [{"station_m": 0.0, "elevation_m": 0.0}],
            }
        ),
        encoding="utf-8",
    )
    output_xml = tmp_path / "unit.xml"

    assert apply_elevation.resolve_existing_path(str(raster), profile) == raster
    assert apply_elevation.terrain_map_output_path("", output_xml) is None
    assert apply_elevation.terrain_map_output_path("auto", output_xml) == tmp_path / "unit-terrain-elevation.png"
    assert apply_elevation.terrain_map_output_path("maps/height.png", output_xml) == tmp_path / "maps" / "height.png"

    profile_path, data, fit, zero, raster_path = apply_elevation.terrain_profile_data([str(profile)], [], 100.0)
    assert profile_path == profile
    assert data["raster"] == "terrain.asc"
    assert fit == pytest.approx({"c": 1.0, "s": 0.0, "ox": 3.0, "oy": -4.0, "scale": 2.0})
    assert zero == pytest.approx(12.5)
    assert raster_path == raster

    missing = tmp_path / "missing.json"
    missing.write_text(
        json.dumps({"raster": "missing.asc", "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 0.0, "offset_y": 0.0}}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="Terrain elevation raster not found"):
        apply_elevation.terrain_profile_data([str(missing)], [], 100.0)


def test_profile_fit_for_terrain_falls_back_to_raster_sample_coordinates(tmp_path) -> None:
    profile = tmp_path / "legacy-profile.json"
    data = {
        "samples": [
            {"station_m": 0.0, "raster_x": 10.0, "raster_y": -5.0},
            {"station_m": 50.0, "raster_x": 60.0, "raster_y": -5.0},
        ]
    }
    segments = [apply_elevation.Segment("straight", "str", length=100.0)]

    fit = apply_elevation.profile_fit_for_terrain(data, profile, segments, 100.0)

    assert fit["c"] == pytest.approx(1.0)
    assert fit["s"] == pytest.approx(0.0)
    assert fit["ox"] == pytest.approx(10.0)
    assert fit["oy"] == pytest.approx(-5.0)

    with pytest.raises(SystemExit, match="without fit metadata"):
        apply_elevation.profile_fit_for_terrain({"samples": [{"station_m": 0.0}]}, profile, segments, 100.0)


def test_terrain_profile_data_uses_mapped_profile_zero(tmp_path) -> None:
    raster = tmp_path / "terrain.asc"
    write_ascii_grid(raster)
    profile = tmp_path / "road-surface-profile.json"
    profile.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "raster": str(raster),
                "source_total_length_m": 200.0,
                "zero_elevation_m": 100.0,
                "mapping": {"source_shift_m": 50.0, "source_reversed": False},
                "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 0.0, "offset_y": 0.0},
                "elevation_profile": {
                    "samples": [
                        {"source_station_m": 0.0, "elevation_m": 0.0},
                        {"source_station_m": 50.0, "elevation_m": 20.0},
                        {"source_station_m": 200.0, "elevation_m": 0.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    _, _, _, zero_elevation, _ = apply_elevation.terrain_profile_data(
        [str(profile)], [apply_elevation.Segment("straight", "str", length=200.0)], 200.0
    )

    assert zero_elevation == pytest.approx(120.0)


class ConstantRaster:
    def __init__(self, value: float | None) -> None:
        self.value = value

    def sample(self, _x: float, _y: float, _resampling: str) -> float | None:
        return self.value


def test_write_terrain_elevation_map_rejects_bad_width_and_missing_samples(monkeypatch, tmp_path) -> None:
    main_track = main_track_with_width(10.0)
    segs = [ET.Element("section", {"name": "straight"})]
    ET.SubElement(segs[0], "attstr", {"name": "type", "val": "str"})
    ET.SubElement(segs[0], "attnum", {"name": "lg", "unit": "m", "val": "20"})
    segments = [apply_elevation.Segment("straight", "str", length=20.0)]
    lengths = [20.0]

    with pytest.raises(SystemExit, match="width must be at least 2"):
        apply_elevation.write_terrain_elevation_map(
            tmp_path / "map.png", [], tmp_path / "unit.xml", None, main_track, segs, segments, lengths, 20.0, 1, "nearest", 0.0
        )

    monkeypatch.setattr(
        apply_elevation,
        "terrain_profile_data",
        lambda *_args: (tmp_path / "profile.json", {}, {"c": 1.0, "s": 0.0, "ox": 0.0, "oy": 0.0}, 0.0, tmp_path / "terrain.asc"),
    )
    monkeypatch.setattr(apply_elevation, "open_raster", lambda *_args: ConstantRaster(None))

    with pytest.raises(SystemExit, match="Raster has no elevation"):
        apply_elevation.write_terrain_elevation_map(
            tmp_path / "map.png",
            ["profile.json"],
            tmp_path / "unit.xml",
            None,
            main_track,
            segs,
            segments,
            lengths,
            20.0,
            4,
            "nearest",
            0.0,
        )


def test_write_terrain_elevation_map_expands_constant_altitude_range(monkeypatch, tmp_path) -> None:
    main_track = main_track_with_width(10.0)
    segs = [ET.Element("section", {"name": "straight"})]
    ET.SubElement(segs[0], "attstr", {"name": "type", "val": "str"})
    ET.SubElement(segs[0], "attnum", {"name": "lg", "unit": "m", "val": "20"})
    segments = [apply_elevation.Segment("straight", "str", length=20.0)]
    lengths = [20.0]
    profile = tmp_path / "profile.json"
    raster = tmp_path / "terrain.asc"
    monkeypatch.setattr(
        apply_elevation, "terrain_profile_data", lambda *_args: (profile, {}, {"c": 1.0, "s": 0.0, "ox": 0.0, "oy": 0.0}, 100.0, raster)
    )
    monkeypatch.setattr(apply_elevation, "open_raster", lambda *_args: ConstantRaster(100.0))

    result = apply_elevation.write_terrain_elevation_map(
        tmp_path / "map.png", [str(profile)], tmp_path / "unit.xml", None, main_track, segs, segments, lengths, 20.0, 4, "nearest", 3.0
    )

    assert result.path == tmp_path / "map.png"
    assert result.min_altitude == pytest.approx(3.0)
    assert result.max_altitude == pytest.approx(4.0)
    assert result.track_z_offset == pytest.approx(3.0)
    assert result.missing_sample_count == 0
    assert (tmp_path / "map.png").exists()


def test_apply_elevation_writes_profile_and_relief_only_terrain(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    report_json = tmp_path / "source" / "elevation-report.json"
    write_track(track_xml)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--point",
            "0:0",
            "--point",
            "100:10",
            "--point",
            "200:0",
            "--smooth-window",
            "0",
            "--relief-distances",
            "25,80,160",
            "--report",
            str(report_json),
        )
        == 0
    )

    root = ET.parse(track_xml).getroot()
    segs = track_segments(root)
    assert [seg.get("name") for seg in segs] == ["uphill", "downhill"]
    assert attnum(segs[0], "z start") == 0.0
    assert attnum(segs[0], "z end") == 10.0
    assert attnum(segs[1], "z start") == 10.0
    assert attnum(segs[1], "z end") == 0.0
    assert attstr(segs[0], "profil") == "spline"
    assert not has_att(segs[0], "attnum", "grade")

    terrain = child_section(child_section(root, "Graphic"), "Terrain Generation")
    assert attstr(terrain, "relief file") == "unit-relief.ac"
    assert not has_att(terrain, "attstr", "elevation map")
    assert not has_att(terrain, "attnum", "minimum altitude")
    assert not has_att(terrain, "attnum", "maximum altitude")

    relief = tmp_path / "unit-relief.ac"
    text = relief.read_text(encoding="utf-8")
    assert text.startswith("AC3Db\n")
    assert 'name "interior-relief-' in text
    assert 'name "exterior-relief-' in text
    assert "data 8\ninterior" in text
    assert "data 8\nexterior" in text

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["segment_count"] == 2
    assert report["relief_line_count"] == 4
    assert report["last_z_end_m"] == 0.0


def test_apply_elevation_writes_terrain_elevation_map(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    profile_json = tmp_path / "profile.json"
    raster = tmp_path / "terrain.asc"
    report_json = tmp_path / "elevation-report.json"
    write_track(track_xml)
    write_ascii_grid(raster)
    profile_json.write_text(
        json.dumps(
            {
                "raster": str(raster),
                "zero_elevation_m": 100.0,
                "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 0.0, "offset_y": 0.0},
                "samples": [
                    {"station_m": 0.0, "elevation_m": 0.0},
                    {"station_m": 100.0, "elevation_m": 10.0},
                    {"station_m": 200.0, "elevation_m": 0.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--smooth-window",
            "0",
            "--relief-distances",
            "none",
            "--terrain-elevation-map",
            "auto",
            "--terrain-elevation-width",
            "16",
            "--report",
            str(report_json),
        )
        == 0
    )

    root = ET.parse(track_xml).getroot()
    terrain = child_section(child_section(root, "Graphic"), "Terrain Generation")
    assert attstr(terrain, "elevation map") == "unit-terrain-elevation.png"
    assert attnum(terrain, "maximum altitude") > attnum(terrain, "minimum altitude")

    elevation_map = tmp_path / "unit-terrain-elevation.png"
    with Image.open(elevation_map) as image:
        assert image.size[0] == 16
        assert image.size[1] >= 2

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["terrain_elevation_map"]["xml_value"] == "unit-terrain-elevation.png"
    assert report["terrain_elevation_map"]["missing_sample_count"] == 0

    diff_report = tmp_path / "terrain-diff-report.json"
    assert (
        run_terrain_diff_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--output",
            str(tmp_path / "terrain-diff.png"),
            "--report",
            str(diff_report),
            "--color-range",
            "1",
        )
        == 0
    )
    assert json.loads(diff_report.read_text(encoding="utf-8"))["max_abs_difference_m"] < 0.2


def test_terrain_elevation_map_uses_trackgen_vertical_normalization(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    profile_json = tmp_path / "profile.json"
    raster = tmp_path / "terrain.asc"
    report_json = tmp_path / "elevation-report.json"
    write_track(track_xml)
    write_ascii_grid(raster)
    profile_json.write_text(
        json.dumps(
            {
                "raster": str(raster),
                "zero_elevation_m": 100.0,
                "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 0.0, "offset_y": 0.0},
                "samples": [
                    {"station_m": 0.0, "elevation_m": 0.0},
                    {"station_m": 100.0, "elevation_m": -10.0},
                    {"station_m": 200.0, "elevation_m": 0.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--smooth-window",
            "0",
            "--relief-distances",
            "none",
            "--terrain-elevation-map",
            "auto",
            "--terrain-elevation-width",
            "16",
            "--report",
            str(report_json),
        )
        == 0
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    terrain_map = report["terrain_elevation_map"]
    assert terrain_map["track_z_offset_m"] == pytest.approx(10.0)

    diff_report = tmp_path / "terrain-diff-report.json"
    assert (
        run_terrain_diff_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--output",
            str(tmp_path / "terrain-diff.png"),
            "--report",
            str(diff_report),
            "--color-range",
            "1",
        )
        == 0
    )
    diff = json.loads(diff_report.read_text(encoding="utf-8"))
    assert diff["track_z_offset_m"] == pytest.approx(10.0)
    assert diff["max_abs_difference_m"] < 0.2


def test_apply_elevation_dry_run_does_not_write_xml_or_relief(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    report_json = tmp_path / "elevation-report.json"
    write_track(track_xml)
    original = track_xml.read_text(encoding="utf-8")

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--point",
            "0,0",
            "--point",
            "100,5",
            "--point",
            "200,0",
            "--relief-distances",
            "25,80,160",
            "--dry-run",
            "--report",
            str(report_json),
        )
        == 0
    )

    assert track_xml.read_text(encoding="utf-8") == original
    assert not (tmp_path / "unit-relief.ac").exists()
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["dry_run"]
    assert report["relief_line_count"] == 4


def test_relief_interior_max_distance_can_keep_all_lines(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    report_json = tmp_path / "elevation-report.json"
    write_track(track_xml)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--point",
            "0,0",
            "--point",
            "100,5",
            "--point",
            "200,0",
            "--relief-distances",
            "25,80,160",
            "--relief-interior-max-distance",
            "200",
            "--dry-run",
            "--report",
            str(report_json),
        )
        == 0
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["relief_line_count"] == 6


def test_multiple_profile_sources_are_averaged_relative_to_start(tmp_path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"samples": [{"station_m": 0, "elevation_m": 100}, {"station_m": 50, "elevation_m": 110}]}), encoding="utf-8")
    b.write_text(json.dumps({"samples": [{"station_m": 0, "elevation_m": 40}, {"station_m": 50, "elevation_m": 60}]}), encoding="utf-8")

    sources = apply_elevation.normalized_sources([apply_elevation.read_profile(a), apply_elevation.read_profile(b)], 100.0)

    assert apply_elevation.eval_sources(sources, 50.0, 100.0) == pytest.approx(15.0)


def test_profile_csv_accepts_distance_header(tmp_path) -> None:
    profile = tmp_path / "profile.csv"
    profile.write_text("distance,elevation\n10,2\n20,4\n", encoding="utf-8")

    source = apply_elevation.read_profile(profile)

    assert source.samples[0].station == pytest.approx(10.0)
    assert source.samples[0].elevation == pytest.approx(2.0)


def test_road_surface_profile_supplies_elevation_and_banking_sources(tmp_path) -> None:
    profile = tmp_path / "road-surface.json"
    profile.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "weight": 0.2,
                "station_frame": "source",
                "source_total_length_m": 200.0,
                "mapping": {
                    "source_reversed": True,
                    "station_map": [
                        {"xml_station_m": 0.0, "source_station_m": 20.0},
                        {"xml_station_m": 100.0, "source_station_m": 120.0},
                    ],
                },
                "sampling": {"real_road_width_m": 8.0},
                "elevation_profile": {
                    "weight": 0.7,
                    "samples": [
                        {"source_station_m": 20.0, "elevation_m": 5.0},
                        {"source_station_m": 120.0, "elevation_m": 15.0},
                    ],
                },
                "banking_profile": {
                    "samples": [
                        {"source_station_m": 20.0, "banking_deg": 4.0},
                        {"source_station_m": 120.0, "banking_deg": 6.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    elevation = apply_elevation.read_profile(profile)
    banking = apply_elevation.read_banking_profiles(profile)[0]

    assert elevation.source_total == pytest.approx(200.0)
    assert elevation.weight == pytest.approx(0.7)
    assert elevation.station_map[0] == apply_elevation.StationMapPoint(0.0, 20.0)
    assert banking.weight == pytest.approx(0.2)
    assert banking.source_reversed is True
    assert banking.real_width_m == pytest.approx(8.0)
    assert banking.samples[1].elevation == pytest.approx(6.0)


def test_apply_banking_profile_only_writes_segment_banking(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    profile_json = tmp_path / "banking.json"
    report_json = tmp_path / "banking-report.json"
    write_track(track_xml)
    profile_json.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "station_frame": "source",
                "source_total_length_m": 200.0,
                "mapping": {"source_reversed": True},
                "banking_profile": {
                    "samples": [
                        {"source_station_m": 0.0, "banking_deg": 10.0},
                        {"source_station_m": 100.0, "banking_deg": 20.0},
                        {"source_station_m": 200.0, "banking_deg": 10.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--apply-banking",
            "--banking-profile-only",
            "--bank-smooth-window",
            "0",
            "--report",
            str(report_json),
        )
        == 0
    )

    root = ET.parse(track_xml).getroot()
    segs = track_segments(root)
    assert attnum(segs[0], "banking start") == pytest.approx(-10.0)
    assert attnum(segs[0], "banking end") == pytest.approx(-20.0)
    assert attnum(segs[1], "banking start") == pytest.approx(-20.0)
    assert attnum(segs[1], "banking end") == pytest.approx(-10.0)
    assert has_att(segs[0], "attnum", "grade")

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["banking_source_count"] == 1
    assert report["banking"]["min_deg"] == pytest.approx(-20.0)


def test_apply_banking_edge_delta_policy_scales_for_torcs_width(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    profile_json = tmp_path / "banking.json"
    write_track(track_xml)
    profile_json.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "station_frame": "xml",
                "sampling": {"real_road_width_m": 5.0},
                "banking_profile": {
                    "samples": [
                        {"station_m": 0.0, "banking_deg": 30.0},
                        {"station_m": 200.0, "banking_deg": 30.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile_json),
            "--apply-banking",
            "--banking-profile-only",
            "--bank-width-policy",
            "edge-delta",
            "--bank-smooth-window",
            "0",
        )
        == 0
    )

    expected = math.degrees(math.atan(math.tan(math.radians(30.0)) * 5.0 / 10.0))
    segs = track_segments(ET.parse(track_xml).getroot())
    assert attnum(segs[0], "banking start") == pytest.approx(expected)


def test_reserved_banking_rate_limit_is_rejected(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    write_track(track_xml)

    with pytest.raises(SystemExit, match="--bank-max-rate-deg-per-m"):
        run_tool(monkeypatch, "--track-xml", str(track_xml), "--point", "0:0", "--point", "200:0", "--bank-max-rate-deg-per-m", "1")


def test_reserved_pit_side_banking_policy_is_rejected(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    write_track(track_xml)

    with pytest.raises(SystemExit, match="--pit-side-banking"):
        run_tool(monkeypatch, "--track-xml", str(track_xml), "--point", "0:0", "--point", "200:0", "--pit-side-banking", "level")


def test_landmark_alignment_warps_xml_station_to_source_station() -> None:
    source = apply_elevation.ProfileSource(
        "source-cache",
        [
            apply_elevation.ProfileSample(0.0, 0.0),
            apply_elevation.ProfileSample(100.0, 10.0),
            apply_elevation.ProfileSample(160.0, 16.0),
            apply_elevation.ProfileSample(260.0, 26.0),
            apply_elevation.ProfileSample(300.0, 30.0),
            apply_elevation.ProfileSample(400.0, 0.0),
        ],
        1.0,
        400.0,
        (
            apply_elevation.LandmarkRange("Alpha", 100.0, 160.0),
            apply_elevation.LandmarkRange("Beta", 260.0, 300.0),
        ),
    )
    xml_ranges = (
        apply_elevation.LandmarkRange("Alpha", 10.0, 50.0),
        apply_elevation.LandmarkRange("Beta", 110.0, 150.0),
    )

    aligned, reports = apply_elevation.align_sources_to_xml_landmarks([source], xml_ranges, 200.0, True)

    assert reports[0]["matched_anchor_count"] == 4
    assert apply_elevation.map_profile_station(aligned[0], 10.0, 200.0) == pytest.approx(100.0)
    assert apply_elevation.map_profile_station(aligned[0], 50.0, 200.0) == pytest.approx(160.0)
    assert apply_elevation.map_profile_station(aligned[0], 80.0, 200.0) == pytest.approx(210.0)
    assert apply_elevation.eval_source(aligned[0], 110.0, 200.0) == pytest.approx(26.0)
    assert apply_elevation.map_profile_station(aligned[0], 175.0, 200.0) == pytest.approx(383.3333333333)
    assert apply_elevation.map_profile_station(aligned[0], 5.0, 200.0) == pytest.approx(83.3333333333)


def test_landmark_alignment_rejects_auto_warp_that_conflicts_with_plan_fit() -> None:
    source = apply_elevation.ProfileSource(
        "source-cache",
        [
            apply_elevation.ProfileSample(0.0, 0.0),
            apply_elevation.ProfileSample(100.0, 10.0),
            apply_elevation.ProfileSample(160.0, 16.0),
            apply_elevation.ProfileSample(260.0, 26.0),
            apply_elevation.ProfileSample(300.0, 30.0),
            apply_elevation.ProfileSample(400.0, 0.0),
        ],
        1.0,
        400.0,
        (
            apply_elevation.LandmarkRange("Alpha", 100.0, 160.0),
            apply_elevation.LandmarkRange("Beta", 260.0, 300.0),
        ),
        (),
        250.0,
        False,
        0.0,
        True,
    )
    xml_ranges = (
        apply_elevation.LandmarkRange("Alpha", 10.0, 50.0),
        apply_elevation.LandmarkRange("Beta", 110.0, 150.0),
    )

    aligned, reports = apply_elevation.align_sources_to_xml_landmarks([source], xml_ranges, 200.0, True)

    assert reports[0]["matched_anchor_count"] == 0
    assert reports[0]["alignment_rejected_reason"] == "station-map-conflicts-with-plan-fit"
    assert reports[0]["plan_fit_max_deviation_m"] > 25.0
    assert aligned[0].station_map == ()
    assert apply_elevation.map_profile_station(aligned[0], 10.0, 200.0) == pytest.approx(260.0)


def test_elevation_cache_reads_source_landmarks(tmp_path) -> None:
    polyline = tmp_path / "centerline.json"
    polyline.write_text(
        json.dumps(
            {
                "polyline": [
                    {"x": 0.0, "y": 0.0, "way_name": "Alpha"},
                    {"x": 10.0, "y": 0.0, "way_name": "Alpha"},
                    {"x": 20.0, "y": 0.0, "way_name": "Beta"},
                ]
            }
        ),
        encoding="utf-8",
    )
    cache = tmp_path / "elevation-cache.json"
    cache.write_text(
        json.dumps(
            {
                "source": {"polyline": str(polyline)},
                "total_length_m": 20.0,
                "road_profile": {
                    "samples": [
                        {"station_m": 0.0, "elevation_m": 100.0},
                        {"station_m": 20.0, "elevation_m": 105.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    source = apply_elevation.read_profile(cache)

    assert source.source_total == 20.0
    assert [(item.name, item.start, item.end) for item in source.landmarks] == [("Alpha", 0.0, 10.0), ("Beta", 20.0, 20.0)]


def test_raster_dem_profile_does_not_auto_warp_source_landmarks(tmp_path) -> None:
    polyline = tmp_path / "centerline.json"
    polyline.write_text(
        json.dumps(
            {
                "polyline": [
                    {"x": 0.0, "y": 0.0, "way_name": "Alpha"},
                    {"x": 50.0, "y": 0.0, "way_name": "Alpha"},
                    {"x": 100.0, "y": 0.0, "way_name": "Beta"},
                ]
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "raster-profile.json"
    profile.write_text(
        json.dumps(
            {
                "type": "raster-dem-profile",
                "polyline": str(polyline),
                "total_length_m": 100.0,
                "samples": [
                    {"station_m": 0.0, "elevation_m": 0.0},
                    {"station_m": 100.0, "elevation_m": 10.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    source = apply_elevation.read_profile(profile)
    aligned, reports = apply_elevation.align_sources_to_xml_landmarks(
        [source],
        (
            apply_elevation.LandmarkRange("Alpha", 20.0, 40.0),
            apply_elevation.LandmarkRange("Beta", 60.0, 80.0),
        ),
        100.0,
        True,
    )

    assert source.landmarks == ()
    assert reports[0]["source_landmark_count"] == 0
    assert reports[0]["matched_anchor_count"] == 0
    assert apply_elevation.map_profile_station(aligned[0], 50.0, 100.0) == pytest.approx(50.0)


def test_profile_start_uses_zero_station_when_total_station_is_also_present() -> None:
    samples = [
        apply_elevation.ProfileSample(0.0, 0.0),
        apply_elevation.ProfileSample(50.0, 10.0),
        apply_elevation.ProfileSample(100.0, 3.0),
    ]

    assert apply_elevation.eval_linear(samples, 0.0, 100.0) == 0.0


def test_elevation_cache_supplies_road_profile_and_terrain_lines(tmp_path) -> None:
    cache = tmp_path / "elevation-cache.json"
    cache.write_text(
        json.dumps(
            {
                "normalization": {"road_start_elevation_m": 100.0},
                "road_profile": {
                    "samples": [
                        {"station_m": 0.0, "elevation_m": 100.0},
                        {"station_m": 50.0, "elevation_m": 112.0},
                    ]
                },
                "terrain_lines": [
                    {
                        "side": "left",
                        "distance_m": 25.0,
                        "samples": [
                            {"station_m": 0.0, "elevation_m": 101.0},
                            {"station_m": 50.0, "elevation_m": 120.0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    source = apply_elevation.read_profile(cache)
    terrain = apply_elevation.read_terrain_lines(cache)

    assert source.samples[0].elevation == 100.0
    assert terrain[0].side == "left"
    assert terrain[0].samples[0].elevation == 1.0
    assert apply_elevation.eval_terrain_lines(terrain, "left", 25.0, 50.0, 100.0) == 20.0


def test_terrain_lines_follow_aligned_source_station_and_zero() -> None:
    terrain = [
        apply_elevation.TerrainLine(
            "left",
            25.0,
            apply_elevation.validate_profile_samples(
                [
                    apply_elevation.ProfileSample(0.0, 0.0),
                    apply_elevation.ProfileSample(50.0, 10.0),
                    apply_elevation.ProfileSample(100.0, 0.0),
                ]
            ),
            "cache.json",
            100.0,
        )
    ]
    sources = [
        apply_elevation.ProfileSource(
            "cache.json",
            [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(100.0, 0.0)],
            0.0,
            100.0,
            (),
            (apply_elevation.StationMapPoint(0.0, 50.0),),
        )
    ]

    aligned = apply_elevation.align_terrain_lines_to_sources(terrain, sources, 100.0)

    assert aligned[0].zero_offset == pytest.approx(10.0)
    assert apply_elevation.eval_terrain_lines(aligned, "left", 25.0, 0.0, 100.0) == pytest.approx(0.0)
    assert apply_elevation.eval_terrain_lines(aligned, "left", 25.0, 25.0, 100.0) == pytest.approx(-5.0)


def test_terrain_lines_follow_plan_fit_source_shift_and_zero() -> None:
    terrain = [
        apply_elevation.TerrainLine(
            "center",
            0.0,
            apply_elevation.validate_profile_samples(
                [
                    apply_elevation.ProfileSample(0.0, 0.0),
                    apply_elevation.ProfileSample(50.0, 10.0),
                    apply_elevation.ProfileSample(100.0, 0.0),
                ]
            ),
            "source-cache-terrainonly.json",
            100.0,
        ),
        apply_elevation.TerrainLine(
            "left",
            25.0,
            apply_elevation.validate_profile_samples(
                [
                    apply_elevation.ProfileSample(0.0, 2.0),
                    apply_elevation.ProfileSample(50.0, 12.0),
                    apply_elevation.ProfileSample(100.0, 2.0),
                ]
            ),
            "source-cache-terrainonly.json",
            100.0,
        ),
    ]

    aligned = apply_elevation.align_terrain_lines_to_sources(terrain, [], 100.0, [apply_elevation.TerrainFit("source-cache.json", 50.0)])

    assert aligned[0].zero_offset == pytest.approx(10.0)
    assert aligned[1].zero_offset == pytest.approx(10.0)
    assert apply_elevation.eval_terrain_lines(aligned, "left", 25.0, 0.0, 100.0) == pytest.approx(2.0)
    assert apply_elevation.eval_terrain_lines(aligned, "left", 25.0, 25.0, 100.0) == pytest.approx(-3.0)


def test_plan_fit_matches_absolute_terrain_cache_to_relative_profile_source(monkeypatch, tmp_path) -> None:
    profile = tmp_path / "profile.json"
    source = tmp_path / "source-cache.json"
    terrain_only = tmp_path / "source-cache-terrainonly.json"
    source.write_text("{}", encoding="utf-8")
    terrain_only.write_text("{}", encoding="utf-8")
    profile.write_text(
        json.dumps(
            {
                "elevation_source": "source-cache.json",
                "fit": {"source_shift_m": 50.0, "source_reversed": False},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path.parent)
    line = apply_elevation.TerrainLine(
        "left",
        25.0,
        [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(100.0, 0.0)],
        str(terrain_only.resolve()),
        100.0,
    )

    fits = apply_elevation.terrain_fits_from_profile_paths([profile.resolve()])
    fit = apply_elevation.terrain_fit_for_line(line, fits)

    assert fit is not None
    assert fit.source_shift_m == pytest.approx(50.0)


def test_plan_fit_rejects_ambiguous_relative_source(monkeypatch, tmp_path) -> None:
    profile_dir = tmp_path / "profile"
    cwd_dir = tmp_path / "cwd"
    profile_dir.mkdir()
    cwd_dir.mkdir()
    (profile_dir / "source-cache.json").write_text("{}", encoding="utf-8")
    (cwd_dir / "source-cache.json").write_text("{}", encoding="utf-8")
    profile = profile_dir / "profile.json"
    profile.write_text(
        json.dumps({"elevation_source": "source-cache.json", "fit": {"source_shift_m": 50.0}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(cwd_dir)

    with pytest.raises(SystemExit, match="Ambiguous elevation_source"):
        apply_elevation.terrain_fits_from_profile_paths([profile])


def test_reversed_plan_fit_swaps_terrain_sides() -> None:
    terrain = [
        apply_elevation.TerrainLine(
            side,
            20.0,
            [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(100.0, 0.0)],
            "source-cache-terrainonly.json",
            100.0,
        )
        for side in ("left", "right")
    ]

    aligned = apply_elevation.align_terrain_lines_to_sources(
        terrain, [], 100.0, [apply_elevation.TerrainFit("source-cache.json", 0.0, True)]
    )

    assert [line.side for line in aligned] == ["right", "left"]


def test_scaled_plan_fit_scales_station_and_lateral_distance() -> None:
    center_line = apply_elevation.TerrainLine(
        "center",
        0.0,
        [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(100.0, 0.0)],
        "source-cache-terrainonly.json",
        100.0,
    )
    terrain = [
        apply_elevation.TerrainLine(
            "left",
            distance,
            [
                apply_elevation.ProfileSample(0.0, elevation),
                apply_elevation.ProfileSample(20.0, elevation),
                apply_elevation.ProfileSample(100.0, elevation),
            ],
            "source-cache-terrainonly.json",
            100.0,
        )
        for distance, elevation in ((20.0, 0.0), (40.0, 100.0))
    ]
    station_line = apply_elevation.TerrainLine(
        "right",
        20.0,
        [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(20.0, 20.0), apply_elevation.ProfileSample(100.0, 0.0)],
        "source-cache-terrainonly.json",
        100.0,
    )

    aligned = apply_elevation.align_terrain_lines_to_sources(
        [center_line, *terrain, station_line], [], 100.0, [apply_elevation.TerrainFit("source-cache.json", 0.0, False, 2.0)]
    )

    assert apply_elevation.eval_terrain_lines(aligned, "left", 15.0, 0.0, 100.0) == pytest.approx(50.0)
    assert apply_elevation.eval_terrain_line(aligned[3], 10.0, 100.0) == pytest.approx(20.0)


def test_plan_fit_does_not_attach_to_unrelated_terrain_cache() -> None:
    terrain = [
        apply_elevation.TerrainLine(
            "left",
            25.0,
            apply_elevation.validate_profile_samples(
                [
                    apply_elevation.ProfileSample(0.0, 0.0),
                    apply_elevation.ProfileSample(50.0, 10.0),
                    apply_elevation.ProfileSample(100.0, 0.0),
                ]
            ),
            "other-cache.json",
            100.0,
        )
    ]

    aligned = apply_elevation.align_terrain_lines_to_sources(terrain, [], 100.0, [apply_elevation.TerrainFit("source-cache.json", 50.0)])

    assert aligned[0].source_shift_m is None
    assert apply_elevation.eval_terrain_lines(aligned, "left", 25.0, 0.0, 100.0) == pytest.approx(0.0)


def test_relief_validation_rejects_self_intersecting_line() -> None:
    bow_tie = [(0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0), (0.0, 0.0)]

    assert apply_elevation.polyline_has_self_intersection(bow_tie)
    assert not apply_elevation.relief_xy_is_valid(bow_tie, [])


def relief_issue_reasons(result: apply_elevation.ReliefValidationResult) -> set[str]:
    return {issue.reason for issue in result.issues}


def test_relief_breakline_contract_accepts_disjoint_open_lines() -> None:
    result = apply_elevation.validate_relief_breakline_set(
        [[(0.0, 0.0), (10.0, 0.0)], [(0.0, 2.0), (10.0, 2.0)]],
        [],
    )

    assert result.ok
    assert result.reason_counts() == {}


def test_relief_breakline_contract_rejects_invalid_single_lines() -> None:
    cases = [
        ([(0.0, 0.0)], "too_few_points"),
        ([(0.0, 0.0), (10.0, 0.0), (0.0, 0.0)], "closed_line"),
        ([(0.0, 0.0), (0.0001, 0.0), (10.0, 0.0)], "degenerate_segment"),
        ([(0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0)], "self_intersection"),
        ([(0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (15.0, 0.0)], "self_intersection"),
        ([(0.0, 0.0), (10.0, 0.0), (5.0, 5.0), (5.0, -5.0)], "self_intersection"),
        ([(0.0, 0.0), (10.0, 0.0), (12.0, 2.0), (5.0, 0.0), (5.0, 5.0)], "self_intersection"),
    ]

    for points, reason in cases:
        result = apply_elevation.validate_relief_breakline_set([points], [])

        assert not result.ok
        assert reason in relief_issue_reasons(result)


def test_relief_breakline_contract_rejects_boundary_and_line_contacts() -> None:
    result = apply_elevation.validate_relief_breakline_set(
        [[(0.0, -1.0), (0.0, 1.0)]],
        [[(-1.0, 0.0), (1.0, 0.0)]],
    )

    assert not result.ok
    assert "track_boundary_intersection" in relief_issue_reasons(result)

    result = apply_elevation.validate_relief_breakline_set(
        [[(0.0, 0.0), (0.0, 1.0)]],
        [[(0.0, 0.0), (1.0, 0.0)]],
    )

    assert not result.ok
    assert "track_boundary_intersection" in relief_issue_reasons(result)

    result = apply_elevation.validate_relief_breakline_set(
        [[(0.0, -1.0), (0.0, 1.0)], [(-1.0, 0.0), (1.0, 0.0)]],
        [],
    )

    assert not result.ok
    assert "relief_line_intersection" in relief_issue_reasons(result)

    result = apply_elevation.validate_relief_breakline_set(
        [[(0.0, 0.0), (10.0, 0.0)], [(0.0, 0.0), (10.0, 0.0)]],
        [],
    )

    assert not result.ok
    assert "relief_line_intersection" in relief_issue_reasons(result)


def test_relief_domain_validation_rejects_wrong_side_or_outside_border() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]

    assert (
        apply_elevation.relief_domain_rejection_reason([(2.0, 2.0), (8.0, 2.0)], "interior", square, square, (0.0, 0.0, 10.0, 10.0)) is None
    )
    assert (
        apply_elevation.relief_domain_rejection_reason([(12.0, 2.0), (13.0, 2.0)], "interior", square, square, (0.0, 0.0, 20.0, 20.0))
        == "outside_interior_domain"
    )
    assert (
        apply_elevation.relief_domain_rejection_reason([(2.0, 2.0), (8.0, 2.0)], "exterior", square, square, (0.0, 0.0, 10.0, 10.0))
        == "inside_track_domain"
    )
    assert (
        apply_elevation.relief_domain_rejection_reason([(12.0, 2.0), (13.0, 2.0)], "exterior", square, square, (0.0, 0.0, 10.0, 10.0))
        == "outside_border"
    )


def test_distance_relief_contours_are_simple_on_concave_loop() -> None:
    centerline = [
        (0.0, 0.0),
        (120.0, 0.0),
        (120.0, 80.0),
        (80.0, 80.0),
        (80.0, 30.0),
        (40.0, 30.0),
        (40.0, 80.0),
        (0.0, 80.0),
        (0.0, 0.0),
    ]
    samples, total = samples_from_xy(centerline, step=5.0)
    polygon = apply_elevation.centerline_loop_xy(samples, total)
    profile = apply_elevation.BoundaryProfile([0.0], [0.0], [0.0], [0.0], [])

    lines, info = apply_elevation.build_distance_relief_lines(
        main_track_with_width(8.0),
        [],
        samples,
        polygon,
        profile,
        total,
        [10.0, 20.0],
        40.0,
        0.0,
        [],
        30.0,
    )

    assert info["method"] == "distance-field"
    assert lines
    for line in lines:
        assert line["points"]
        assert not line["closed"]
        assert len(line["output_xy_points"]) < len(apply_elevation.strip_closed_duplicate(line["xy_points"]))
        assert line["points"][0][0] != pytest.approx(line["points"][-1][0]) or line["points"][0][2] != pytest.approx(line["points"][-1][2])
        assert not apply_elevation.polyline_has_self_intersection(line["xy_points"])
        area = apply_elevation.signed_area_xy(apply_elevation.strip_closed_duplicate(line["xy_points"]))
        assert area > 0.0 if line["data"] == "exterior" else area < 0.0
    for i, line in enumerate(lines):
        for other in lines[i + 1 :]:
            assert not apply_elevation.polylines_intersect(line["xy_points"], other["xy_points"])


def test_track_bounds_keep_local_side_widening_local() -> None:
    main_track = main_track_with_width(8.0)
    for name in ("Left Side", "Right Side"):
        section = ET.SubElement(main_track, "section", {"name": name})
        ET.SubElement(section, "attnum", {"name": "width", "unit": "m", "val": "2"})
    for name in ("Left Border", "Right Border"):
        section = ET.SubElement(main_track, "section", {"name": name})
        ET.SubElement(section, "attnum", {"name": "width", "unit": "m", "val": "1"})

    xml_segs = []
    for name, kind in (("entry", "str"), ("turn", "lft"), ("wide", "str")):
        seg = ET.Element("section", {"name": name})
        ET.SubElement(seg, "attstr", {"name": "type", "val": kind})
        if kind == "str":
            ET.SubElement(seg, "attnum", {"name": "lg", "unit": "m", "val": "100"})
        else:
            ET.SubElement(seg, "attnum", {"name": "radius", "unit": "m", "val": "10"})
            ET.SubElement(seg, "attnum", {"name": "arc", "unit": "deg", "val": "90"})
        xml_segs.append(seg)
    right_side = ET.SubElement(xml_segs[2], "section", {"name": "Right Side"})
    ET.SubElement(right_side, "attnum", {"name": "width", "unit": "m", "val": "10"})
    segments = [
        apply_elevation.Segment("entry", "str", length=100.0),
        apply_elevation.Segment("turn", "lft", radius=10.0, arc_deg=90.0),
        apply_elevation.Segment("wide", "str", length=100.0),
    ]
    lengths = [100.0, 5.0 * math.pi, 100.0]

    left_edge, right_edge = apply_elevation.track_outer_edge_points(main_track, xml_segs, segments, lengths, 2.0)
    bounds = apply_elevation.track_bounds_for_terrain(main_track, xml_segs, segments, lengths, 1.0)

    assert left_edge[0].center_distance == pytest.approx(7.0)
    assert right_edge[0].center_distance == pytest.approx(7.0)
    assert max(point.center_distance for point in right_edge) == pytest.approx(15.0)
    assert bounds[1] == pytest.approx(-7.0, abs=0.01)


def test_elevation_loaders_inherit_main_track_profile_step(tmp_path) -> None:
    track_xml = tmp_path / "profile-step.xml"
    write_track(track_xml)
    tree = ET.parse(track_xml)
    main_track = child_section(tree.getroot(), "Main Track")
    ET.SubElement(main_track, "attnum", {"name": "profil steps length", "unit": "m", "val": "2.5"})
    tree.write(track_xml, encoding="unicode")

    *_prefix, apply_segments, _lengths, _total = apply_elevation.load_track_elevation_context(track_xml)
    _main_track, _terrain, _xml_segments, render_segments, _lengths, _total = render_terrain_elevation_diff_png.load_track(track_xml)

    assert all(segment.profil_steps_length == pytest.approx(2.5) for segment in apply_segments)
    assert all(segment.profil_steps_length == pytest.approx(2.5) for segment in render_segments)


def test_track_edges_follow_variable_turn_steps_and_width_taper() -> None:
    main_track = main_track_with_width(8.0)
    for name in ("Left Side", "Right Side"):
        section = ET.SubElement(main_track, "section", {"name": name})
        ET.SubElement(section, "attnum", {"name": "width", "unit": "m", "val": "2"})
    for name in ("Left Border", "Right Border"):
        section = ET.SubElement(main_track, "section", {"name": name})
        ET.SubElement(section, "attnum", {"name": "width", "unit": "m", "val": "1"})
    xml_seg = ET.Element("section", {"name": "variable"})
    ET.SubElement(xml_seg, "attstr", {"name": "type", "val": "lft"})
    ET.SubElement(xml_seg, "attnum", {"name": "radius", "unit": "m", "val": "10"})
    ET.SubElement(xml_seg, "attnum", {"name": "end radius", "unit": "m", "val": "30"})
    ET.SubElement(xml_seg, "attnum", {"name": "arc", "unit": "deg", "val": "90"})
    right_side = ET.SubElement(xml_seg, "section", {"name": "Right Side"})
    ET.SubElement(right_side, "attnum", {"name": "end width", "unit": "m", "val": "10"})
    segment = apply_elevation.Segment("variable", "lft", radius=10.0, end_radius=30.0, arc_deg=90.0)
    nominal_length = 10.0 * math.pi
    _pose, samples = apply_elevation.sample_segment(apply_elevation.Pose(0.0, 0.0, 0.0), segment, 0.0, 6.0)

    _left_edge, right_edge = apply_elevation.track_outer_edge_points(main_track, [xml_seg], [segment], [nominal_length], 6.0)

    assert all(right_edge[index].station <= right_edge[index + 1].station for index in range(len(right_edge) - 1))
    assert samples[-1].s != pytest.approx(nominal_length)
    assert right_edge[-1].station == pytest.approx(nominal_length)
    assert right_edge[0].center_distance == pytest.approx(7.0)
    assert right_edge[-1].center_distance == pytest.approx(15.0)
    parsed_segment = apply_elevation.segment_from_element(xml_seg, 2.5)
    assert parsed_segment is not None
    assert parsed_segment.profil_steps_length == pytest.approx(2.5)


def test_distance_relief_uses_centerline_distance_and_trackgen_z_offset() -> None:
    profile = apply_elevation.BoundaryProfile([0.0], [0.0], [0.0], [0.0], [])
    terrain = [
        apply_elevation.TerrainLine(
            "left", 10.0, [apply_elevation.ProfileSample(0.0, 0.0), apply_elevation.ProfileSample(100.0, 0.0)], source_total=100.0
        ),
        apply_elevation.TerrainLine(
            "left", 20.0, [apply_elevation.ProfileSample(0.0, 100.0), apply_elevation.ProfileSample(100.0, 100.0)], source_total=100.0
        ),
    ]
    edge = [apply_elevation.ReliefEdgePoint(0.0, 0.0, 0.0, 5.0, 0.0, 1.0)]

    line = apply_elevation.build_distance_relief_line(
        [(0.0, 10.0), (10.0, 10.0)], edge, "left", 10.0, "exterior", profile, 100.0, 0.0, terrain, 10.0
    )

    assert line["terrain_distances_m"] == pytest.approx([15.0, 15.0])
    assert line["z_values"] == pytest.approx([60.0, 60.0])


def test_offset_relief_uses_trackgen_z_offset() -> None:
    profile = apply_elevation.BoundaryProfile([0.0, 100.0], [-5.0, -5.0], [0.0, 0.0], [-5.0, -5.0], [])
    edge = [
        apply_elevation.ReliefEdgePoint(0.0, 0.0, 0.0, 5.0, 0.0, 1.0),
        apply_elevation.ReliefEdgePoint(100.0, 0.0, 100.0, 5.0, 0.0, 1.0),
    ]

    line = apply_elevation.build_offset_relief_line(edge, 100.0, "left", 10.0, "exterior", profile, 0.0, [], 8.0, 0.0, 0.0)

    assert line["z_values"] == pytest.approx([3.0, 3.0])


def test_relief_ac_uses_open_ac3d_breakline_surface(tmp_path) -> None:
    relief = tmp_path / "relief.ac"

    apply_elevation.write_relief_ac(
        relief,
        [
            {
                "side": "left",
                "data": "exterior",
                "closed": False,
                "points": [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, -10.0), (0.0, 0.0, -10.0)],
            }
        ],
    )

    text = relief.read_text(encoding="utf-8")
    assert 'name "exterior-relief-left-0"' in text
    assert "SURF 0x22" in text
    assert "refs 4" in text
    assert "4 0 0" not in text


def test_relief_ac_refuses_closed_or_crossing_breaklines(tmp_path) -> None:
    relief = tmp_path / "relief.ac"

    with pytest.raises(ValueError, match="invalid_data"):
        apply_elevation.write_relief_ac(
            relief,
            [
                {
                    "side": "left",
                    "data": "outside",
                    "points": [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
                }
            ],
        )

    with pytest.raises(ValueError, match="closed_line"):
        apply_elevation.write_relief_ac(
            relief,
            [
                {
                    "side": "left",
                    "data": "exterior",
                    "closed": True,
                    "points": [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
                }
            ],
        )

    with pytest.raises(ValueError, match="relief_line_intersection"):
        apply_elevation.write_relief_ac(
            relief,
            [
                {"side": "left", "data": "exterior", "points": [(0.0, 0.0, 0.0), (10.0, 0.0, -10.0)]},
                {"side": "left", "data": "exterior", "points": [(0.0, 0.0, -10.0), (10.0, 0.0, 0.0)]},
            ],
        )


def test_relief_ac_validates_serialized_vertices_not_candidate_xy(tmp_path) -> None:
    relief = tmp_path / "relief.ac"

    with pytest.raises(ValueError, match="relief_line_intersection"):
        apply_elevation.write_relief_ac(
            relief,
            [
                {
                    "side": "left",
                    "data": "exterior",
                    "output_xy_points": [(0.0, 0.0), (10.0, 0.0)],
                    "points": [(0.0, 0.0, 0.0), (10.0, 0.0, -10.0)],
                },
                {
                    "side": "left",
                    "data": "exterior",
                    "output_xy_points": [(0.0, 2.0), (10.0, 2.0)],
                    "points": [(0.0, 0.0, -10.0), (10.0, 0.0, 0.0)],
                },
            ],
        )


def test_open_relief_breakline_leaves_deliberate_gap() -> None:
    contour = [(float(i), 0.0) for i in range(20)] + [(0.0, 0.0)]

    breakline = apply_elevation.open_relief_breakline_points(contour)

    assert breakline[0] == (3.0, 0.0)
    assert breakline[-1] == (19.0, 0.0)
    assert len(breakline) == 17


def test_open_relief_breakline_keeps_already_open_line() -> None:
    line = [(float(i), 0.0) for i in range(20)]

    assert apply_elevation.open_relief_breakline_points(line) == line


def test_offset_relief_fallback_writes_valid_open_breaklines() -> None:
    profile = apply_elevation.BoundaryProfile([0.0], [0.0], [0.0], [0.0], [])
    lines, info = apply_elevation.build_offset_relief_lines(
        main_track_with_width(8.0),
        [],
        [apply_elevation.Segment("straight", "str", length=100.0)],
        profile,
        100.0,
        [10.0],
        10.0,
        0.0,
        [],
        30.0,
    )

    assert info["method"] == "offset-fallback"
    assert info["rejected_line_count"] == 0
    assert lines
    for line in lines:
        assert line["points"]
        assert not line["closed"]
        assert not apply_elevation.xy_points_are_closed(line["output_xy_points"])
        assert not apply_elevation.polyline_has_self_intersection(line["output_xy_points"])


def test_relief_contour_spacing_uses_edge_spacing_then_coarsens() -> None:
    assert apply_elevation.contour_step_for_distance(6.0, 5.0, 50.0) == pytest.approx(5.0)
    assert apply_elevation.contour_step_for_distance(40.0, 5.0, 50.0) == pytest.approx(10.0)
    assert apply_elevation.contour_step_for_distance(240.0, 5.0, 50.0) == pytest.approx(50.0)


def test_relief_distances_can_be_disabled() -> None:
    assert apply_elevation.parse_distances("none") == []
