# /***************************************************************************
#
#     file                 : test_render_labeled_segments_svg.py
#     created              : 09 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import re
import xml.etree.ElementTree as ET

import pytest

import torcs_track_tools.cli.render_labeled_segments_svg as labeled_svg


def write_track(path) -> None:
    path.write_text(
        """
<params name="Unit Track">
  <section name="Main Track">
    <section name="Track Segments">
      <section name="operator-map-aligned-straightened-30">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
        <section name="Left Border">
          <attstr name="style" val="curb"/>
          <attstr name="surface" val="curb-5cm-l"/>
        </section>
      </section>
      <section name="operator-map-aligned-straightened-31-curb">
        <attstr name="type" val="lft"/>
        <attnum name="radius" unit="m" val="50"/>
        <attnum name="arc" unit="deg" val="45"/>
      </section>
      <section name="Closure X Terminal-31">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="10"/>
      </section>
      <section name="plain-name">
        <attstr name="type" val="rgt"/>
        <attnum name="radius" unit="m" val="80"/>
        <attnum name="arc" unit="deg" val="30"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-labeled-segments-svg", *args])
    return labeled_svg.main()


def legend_rect_height(svg: str) -> float:
    match = re.search(r'<rect x="0" y="0" width="[0-9.]+" height="([0-9.]+)"', svg)
    assert match is not None
    return float(match.group(1))


def legend_suffix_y(svg: str) -> float:
    match = re.search(r'<text x="14" y="([0-9.]+)" class="legend-text">Label suffixes:', svg)
    assert match is not None
    return float(match.group(1))


def test_display_label_uses_source_number_and_split_suffix() -> None:
    prefix = "operator-map-aligned-straightened"
    assert labeled_svg.display_label("operator-map-aligned-straightened-31-curb", 7, "auto", prefix) == "31:c"
    assert labeled_svg.display_label("operator-map-aligned-straightened", 0, "auto", prefix) == "0"
    assert labeled_svg.display_label("Closure X Terminal-31", 8, "auto", prefix) == "Closure X Terminal-31"
    assert labeled_svg.display_label("operator-map-aligned-straightened", 0, "auto") == "operator-map-aligned-straightened"
    assert labeled_svg.display_label("plain-name", 2, "auto") == "plain-name"
    assert labeled_svg.display_label("plain-name", 2, "index") == "3"
    assert labeled_svg.display_label("plain-name", 2, "name") == "plain-name"


def test_parse_label_filter_supports_ranges() -> None:
    assert labeled_svg.parse_label_filter("30-32,40") == {30, 31, 32, 40}


def test_source_name_prefix_uses_dominant_numbered_family() -> None:
    names = [
        "image-centerline",
        "image-centerline-1",
        "image-centerline-2-curb",
        "Pit Straight-2",
        "Closure X Terminal-2",
    ]
    assert labeled_svg.source_name_prefix(names) == "image-centerline"


def test_source_name_prefix_rejects_tied_numbered_families() -> None:
    assert labeled_svg.source_name_prefix(["source-1", "source-2", "generated-1", "generated-2"]) is None


def test_render_labeled_segments_svg_marks_curbs_and_labels(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / "segments.svg"
    write_track(track_xml)

    assert run_tool(monkeypatch, "--track-xml", str(track_xml), "--output", str(out_svg)) == 0

    svg = out_svg.read_text(encoding="utf-8")
    ET.fromstring(svg)
    assert ">30</text>" in svg
    assert ">31:c</text>" in svg
    assert "#f0abfc" in svg
    assert "operator-map-aligned-straightened-30 type=str" in svg
    assert 'id="legend"' in svg
    assert "straight segment" in svg
    assert "Labels: source numbers when available; compact names otherwise" in svg
    assert "Label suffixes: :p pre, :c curb, :o post" in svg
    assert ">Closure X Terminal-31</text>" in svg
    assert legend_rect_height(svg) >= legend_suffix_y(svg) + 12.0


def test_render_labeled_segments_svg_can_zoom_to_labels(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / "zoom.svg"
    write_track(track_xml)

    assert run_tool(monkeypatch, "--track-xml", str(track_xml), "--output", str(out_svg), "--zoom-labels", "31") == 0

    svg = out_svg.read_text(encoding="utf-8")
    assert ">31:c</text>" in svg
    assert ">Closure X Terminal-31</text>" not in svg
    assert "operator-map-aligned-straightened-30 type=str" not in svg
    assert "<title>start</title>" not in svg


def test_no_curb_marker_title_and_legend_are_consistent(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / "no-curbs.svg"
    write_track(track_xml)

    assert run_tool(monkeypatch, "--track-xml", str(track_xml), "--output", str(out_svg), "--no-curb-markers") == 0

    svg = out_svg.read_text(encoding="utf-8")
    assert "magenta rings" not in svg
    assert "magenta ring = direct curb" not in svg
    assert legend_rect_height(svg) >= legend_suffix_y(svg) + 12.0


def test_label_font_size_is_configurable(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / "small-labels.svg"
    write_track(track_xml)

    assert run_tool(
        monkeypatch,
        "--track-xml",
        str(track_xml),
        "--output",
        str(out_svg),
        "--label-font-size",
        "3.5",
    ) == 0

    svg = out_svg.read_text(encoding="utf-8")
    assert "font-size: 3.50px" in svg


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
def test_label_font_size_must_be_positive_and_finite(monkeypatch, tmp_path, value: str) -> None:
    track_xml = tmp_path / "unit-track.xml"
    write_track(track_xml)

    with pytest.raises(SystemExit):
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--output",
            str(tmp_path / "invalid.svg"),
            "--label-font-size",
            value,
        )


@pytest.mark.parametrize(
    ("mode", "legend"),
    [("index", "Labels: 1-based XML segment indices"), ("name", "Labels: full XML segment names")],
)
def test_explicit_label_modes_have_consistent_legends(monkeypatch, tmp_path, mode: str, legend: str) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / f"{mode}.svg"
    write_track(track_xml)

    assert run_tool(monkeypatch, "--track-xml", str(track_xml), "--output", str(out_svg), "--label-mode", mode) == 0

    svg = out_svg.read_text(encoding="utf-8")
    assert legend in svg
    assert "Label suffixes:" not in svg


def test_index_mode_zoom_uses_displayed_index(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    out_svg = tmp_path / "index-zoom.svg"
    write_track(track_xml)

    assert run_tool(
        monkeypatch,
        "--track-xml",
        str(track_xml),
        "--output",
        str(out_svg),
        "--label-mode",
        "index",
        "--zoom-labels",
        "1",
    ) == 0

    svg = out_svg.read_text(encoding="utf-8")
    assert ">1</text>" in svg
    assert "operator-map-aligned-straightened-30 type=str" in svg
    assert "operator-map-aligned-straightened-31-curb type=lft" not in svg


def test_name_mode_rejects_numeric_zoom(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    write_track(track_xml)

    with pytest.raises(SystemExit, match="not available with --label-mode name"):
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--output",
            str(tmp_path / "name-zoom.svg"),
            "--label-mode",
            "name",
            "--zoom-labels",
            "31",
        )


def test_auto_labels_disambiguate_equivalent_numeric_names() -> None:
    rendered = [
        labeled_svg.RenderedSegment(
            index=index,
            segment=labeled_svg.Segment(kind="str", name=name, length=10.0),
            display_label=label,
            points=[(0.0, 0.0), (10.0, 0.0)],
            midpoint=(5.0, 0.0),
            has_curb=False,
            turn_deg=0.0,
        )
        for index, (name, label) in enumerate(
            [("source", "0"), ("source-0", "0"), ("source-1", "1"), ("source-01", "1")]
        )
    ]

    labeled_svg.disambiguate_auto_labels(rendered)

    labels = [item.display_label for item in rendered]
    assert labels == ["source", "source-0", "source-1", "source-01"]
    assert len(labels) == len(set(labels))


def test_auto_label_disambiguation_avoids_existing_fallback_suffix() -> None:
    rendered = [
        labeled_svg.RenderedSegment(
            index=index,
            segment=labeled_svg.Segment(kind="str", name=name, length=10.0),
            display_label=label,
            points=[(0.0, 0.0), (10.0, 0.0)],
            midpoint=(5.0, 0.0),
            has_curb=False,
            turn_deg=0.0,
        )
        for index, (name, label) in enumerate([("foo-pre", "foo:p"), ("foo:p", "foo:p"), ("foo:p#1", "foo:p#1")])
    ]

    labeled_svg.disambiguate_auto_labels(rendered)

    labels = [item.display_label for item in rendered]
    assert labels == ["foo:p#1.2", "foo:p#2", "foo:p#1"]
    assert len(labels) == len(set(labels))
