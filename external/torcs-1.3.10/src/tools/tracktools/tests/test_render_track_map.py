# /***************************************************************************
#
#     file                 : test_render_track_map.py
#     created              : 14 Aug 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

from __future__ import annotations

import os
import stat
import xml.etree.ElementTree as ET

import pytest  # type: ignore[import-not-found]
from PIL import Image  # type: ignore[import-not-found]

import torcs_track_tools.cli.render_track_map as render_track_map
import torcs_track_tools.cli.render_track_maps as render_track_maps
from torcs_track_tools.core.geometry import Pose, Segment, advance_segment
from torcs_track_tools.core.track_map import build_scene, fit_map, render_png, sample_map_segments, scene_from_xml, track_segments


def write_track(path) -> None:
    path.write_text(
        """
<params name="Rounded Square">
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Track Segments">
      <section name="straight-1"><attstr name="type" val="str"/><attnum name="lg" unit="m" val="100"/></section>
      <section name="turn-1"><attstr name="type" val="lft"/><attnum name="radius" unit="m" val="30"/><attnum name="arc" unit="deg" val="90"/></section>
      <section name="straight-2"><attstr name="type" val="str"/><attnum name="lg" unit="m" val="100"/></section>
      <section name="turn-2"><attstr name="type" val="lft"/><attnum name="radius" unit="m" val="30"/><attnum name="arc" unit="deg" val="90"/></section>
      <section name="straight-3"><attstr name="type" val="str"/><attnum name="lg" unit="m" val="100"/></section>
      <section name="turn-3"><attstr name="type" val="lft"/><attnum name="radius" unit="m" val="30"/><attnum name="arc" unit="deg" val="90"/></section>
      <section name="straight-4"><attstr name="type" val="str"/><attnum name="lg" unit="m" val="100"/></section>
      <section name="turn-4"><attstr name="type" val="lft"/><attnum name="radius" unit="m" val="30"/><attnum name="arc" unit="deg" val="90"/></section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-track-map", *args])
    return render_track_map.main()


def test_scene_marks_start_and_xml_direction() -> None:
    root = ET.fromstring(
        """
<params><section name="Main Track"><section name="Track Segments">
  <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="100"/></section>
  <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="180"/></section>
  <section name="return"><attstr name="type" val="str"/><attnum name="lg" val="100"/></section>
  <section name="close"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="180"/></section>
</section></section></params>
""".strip()
    )

    scene = build_scene(root, size=512, margin=32, sample_step=2)

    bottom_left, bottom_right, inner_elbow, _, left_base, tip, right_base, _, outer_elbow = scene.start_marker
    start_x, start_y = scene.track[0]
    assert bottom_left[0] < start_x < bottom_right[0]
    assert inner_elbow[1] < start_y < bottom_right[1]
    assert outer_elbow[0] == pytest.approx(bottom_left[0])
    assert tip[1] < start_y - scene.road_width * 0.5
    assert tip[0] > left_base[0]
    assert tip[0] > right_base[0]


def test_cli_writes_transparent_png_and_marker_svg(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    track_xml = tmp_path / "rounded-square.xml"
    output_png = tmp_path / "rounded-square.png"
    output_svg = tmp_path / "rounded-square.svg"
    write_track(track_xml)

    assert run_tool(
        monkeypatch,
        "--track-xml",
        str(track_xml),
        "--output",
        str(output_png),
        "--svg-output",
        str(output_svg),
        "--size",
        "256",
        "--margin",
        "20",
    ) == 0

    with Image.open(output_png) as image:
        assert image.size == (256, 256)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        alpha_bounds = image.getchannel("A").getbbox()
        assert alpha_bounds is not None
        assert alpha_bounds[0] >= 10
        assert alpha_bounds[1] >= 10
        assert alpha_bounds[2] <= 246
        assert alpha_bounds[3] <= 246
        scene = scene_from_xml(track_xml, size=256, margin=20)
        assert all(image.getpixel((round(x), round(y)))[3] >= 245 for x, y in scene.track[60:-20])

    svg = output_svg.read_text(encoding="utf-8")
    ET.fromstring(svg)
    assert 'id="track"' in svg
    assert 'id="start-marker"' in svg
    assert '<polygon' in svg
    assert 'id="background"' in svg
    assert 'stroke="#ffffff"' in svg


@pytest.mark.parametrize(
    ("size", "margin", "sample_step", "message"),
    [
        (32, 4.0, 2.0, "--size must be a power of two"),
        (300, 20.0, 2.0, "--size must be a power of two"),
        (2048, 20.0, 2.0, "--size must be a power of two"),
        (256, 128.0, 2.0, "--margin must be non-negative"),
        (256, 20.0, 0.0, "--sample-step must be positive"),
    ],
)
def test_scene_rejects_invalid_render_settings(size: int, margin: float, sample_step: float, message: str) -> None:
    root = ET.fromstring(
        "<params><section name='Main Track'><section name='Track Segments'><section name='a'><attstr name='type' val='str'/><attnum name='lg' val='10'/></section></section></section></params>"
    )
    with pytest.raises(SystemExit, match=message):
        build_scene(root, size=size, margin=margin, sample_step=sample_step)


def test_scene_rejects_track_without_drawable_segments() -> None:
    root = ET.fromstring("<params><section name='Main Track'><section name='Track Segments'/></section></params>")
    with pytest.raises(SystemExit, match="no drawable"):
        build_scene(root)


def test_scene_rejects_open_track_instead_of_drawing_closing_chord() -> None:
    root = ET.fromstring(
        "<params><section name='Main Track'><section name='Track Segments'><section name='a'><attstr name='type' val='str'/><attnum name='lg' val='100'/></section></section></section></params>"
    )
    with pytest.raises(SystemExit, match="centerline is not closed"):
        build_scene(root)


def test_track_segments_convert_torcs_distance_units_to_meters() -> None:
    root = ET.fromstring(
        """
<params><section name="Main Track"><section name="Track Segments">
  <section name="straight"><attstr name="type" val="str"/><attnum name="lg" unit="feet" val="100"/></section>
  <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" unit="ft" val="200"/><attnum name="end radius" unit="in" val="1200"/><attnum name="arc" unit="deg" val="30"/></section>
</section></section></params>
""".strip()
    )

    straight, turn = track_segments(root)

    assert straight.length == pytest.approx(30.4801)
    assert turn.radius == pytest.approx(60.9602)
    assert turn.end_radius == pytest.approx(30.48)


def test_readonly_parser_ignores_external_torcs_entities(tmp_path) -> None:
    track_xml = tmp_path / "entities.xml"
    track_xml.write_text(
        """
<!DOCTYPE params [
<!ENTITY default-surfaces SYSTEM "surfaces.xml">
<!ENTITY default-objects SYSTEM "objects.xml">
]>
<params>
  <section name="Surfaces">&default-surfaces;</section>
  <section name="Objects">&default-objects;</section>
  <section name="Main Track"><section name="Track Segments">
    <section name="first"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="180"/></section>
    <section name="second"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="180"/></section>
  </section></section>
</params>
""".strip(),
        encoding="utf-8",
    )

    assert scene_from_xml(track_xml, size=256, margin=20).track


def test_fine_map_sampling_preserves_variable_radius_endpoint() -> None:
    segment = Segment("variable", "lft", radius=80.0, end_radius=160.0, arc_deg=70.0, profil_steps_length=35.0)
    expected = advance_segment(Pose(0.0, 0.0, 0.0), segment)

    samples = sample_map_segments([segment], step=1.0)

    assert len(samples) > 100
    assert samples[-1].x == pytest.approx(expected.x, abs=1e-9)
    assert samples[-1].y == pytest.approx(expected.y, abs=1e-9)
    assert samples[-1].heading == pytest.approx(expected.heading, abs=1e-12)


@pytest.mark.parametrize("size", [64, 128, 256, 512, 1024])
@pytest.mark.parametrize("turn", ["lft", "rgt"])
@pytest.mark.parametrize("margin", [None, 0.0, 8.0])
def test_fitted_artwork_is_unclipped_and_uses_image(size, turn, margin, tmp_path) -> None:
    root = ET.fromstring(
        '<params><section name="Main Track"><section name="Track Segments">'
        f'<section name="circle"><attstr name="type" val="{turn}"/>'
        '<attnum name="radius" val="50"/><attnum name="arc" val="360"/>'
        '</section></section></section></params>'
    )
    scene = build_scene(root, size=size, margin=margin)
    output = tmp_path / "map.png"
    render_png(scene, output)
    expected_margin = max(2.0, size / 128.0) if margin is None else margin
    with Image.open(output) as image:
        bounds = image.getchannel("A").getbbox()
        assert bounds is not None
        left, top, right, bottom = bounds
        assert min(left, top, size - right, size - bottom) >= expected_margin
        # At least one axis nearly fills the available space (allow filter guard).
        assert max(right - left, bottom - top) >= size - 2 * expected_margin - 8
        assert all(image.getpixel(point)[3] == 0 for point in [(0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)])


def test_fitting_preserves_aspect_ratio_and_accounts_for_protruding_marker() -> None:
    points = [(0.0, 0.0), (100.0, 0.0), (100.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    marker = ((-20.0, -30.0), (-20.0, 20.0), (5.0, 0.0))
    track, fitted_marker = fit_map(points, marker, 256, 2, 4, 2)
    width = track[1][0] - track[0][0]
    height = track[0][1] - track[3][1]
    assert width / height == pytest.approx(10.0)
    assert fitted_marker[0][0] - 1 == pytest.approx(5.0)
    assert track[1][0] + 2 == pytest.approx(251.0)
    assert fitted_marker[0][0] - track[0][0] == pytest.approx(-20.0)


def test_legacy_map_matches_modern_without_modifying_xml(tmp_path) -> None:
    xml = tmp_path / "track.xml"
    write_track(xml)
    modern = scene_from_xml(xml)
    legacy = xml.read_text(encoding="utf-8").replace('name="Track Segments"', 'name="segments"')
    xml.write_text(legacy, encoding="utf-8")
    before = xml.read_bytes()
    assert scene_from_xml(xml) == modern
    assert xml.read_bytes() == before


def test_batch_creates_overwrites_and_continues_after_failure(monkeypatch, tmp_path, capsys) -> None:
    before = {}
    for name in ("a-bad", "b-existing", "c-legacy", "d-missing"):
        directory = tmp_path / "road" / name
        directory.mkdir(parents=True)
        xml = directory / f"{name}.xml"
        if name == "d-missing":
            continue
        write_track(xml)
        if name == "a-bad":
            xml.write_text("not XML", encoding="utf-8")
        elif name == "c-legacy":
            xml.write_text(xml.read_text(encoding="utf-8").replace('name="Track Segments"', 'name="segments"'), encoding="utf-8")
        before[xml] = xml.read_bytes()
        if name != "c-legacy":
            (directory / f"{name}.png").write_bytes(b"previous map")
    monkeypatch.setattr("sys.argv", ["torcs-render-track-maps", "--tracks-root", str(tmp_path), "--size", "128"])
    assert render_track_maps.main() == 1
    assert "Summary: 1 created, 1 overwritten, 2 failed" in capsys.readouterr().out
    assert (tmp_path / "road/a-bad/a-bad.png").read_bytes() == b"previous map"
    for name in ("b-existing", "c-legacy"):
        with Image.open(tmp_path / "road" / name / f"{name}.png") as image:
            assert image.size == (128, 128)
            assert image.mode == "RGBA"
            image.verify()
    assert all(xml.read_bytes() == content for xml, content in before.items())
    assert not list(tmp_path.glob("*/*/.*"))


def test_batch_success_exit_status(monkeypatch, tmp_path, capsys) -> None:
    directory = tmp_path / "oval" / "test"
    directory.mkdir(parents=True)
    write_track(directory / "test.xml")
    monkeypatch.setattr("sys.argv", ["torcs-render-track-maps", "--tracks-root", str(tmp_path)])
    assert render_track_maps.main() == 0
    assert "Summary: 1 created, 0 overwritten, 0 failed" in capsys.readouterr().out


@pytest.mark.parametrize("exists", [False, True])
def test_batch_rejects_missing_or_empty_root(monkeypatch, tmp_path, exists) -> None:
    root = tmp_path / "tracks"
    if exists:
        root.mkdir()
    monkeypatch.setattr("sys.argv", ["torcs-render-track-maps", "--tracks-root", str(root)])
    with pytest.raises(SystemExit, match="No track directories|not a directory"):
        render_track_maps.main()


def test_failed_render_preserves_existing_map_and_cleans_temporary(monkeypatch, tmp_path) -> None:
    xml = tmp_path / "track.xml"
    write_track(xml)
    output = tmp_path / "track.png"
    output.write_bytes(b"previous map")

    def fail_render(scene, temporary):
        temporary.write_bytes(b"partial PNG")
        raise OSError("simulated write failure")

    monkeypatch.setattr(render_track_maps, "render_png", fail_render)
    with pytest.raises(OSError, match="simulated write failure"):
        render_track_maps.replace_png(scene_from_xml(xml), output)
    assert output.read_bytes() == b"previous map"
    assert not list(tmp_path.glob(".track-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes and umask")
@pytest.mark.parametrize("existing_mode", [None, 0o644, 0o640, 0o600, 0o444])
@pytest.mark.parametrize("mask", [0o022, 0o027, 0o077])
def test_batch_map_permissions(tmp_path, existing_mode, mask) -> None:
    xml = tmp_path / "track.xml"
    write_track(xml)
    scene = scene_from_xml(xml, size=64)
    output = tmp_path / "track.png"
    if existing_mode is not None:
        output.write_bytes(b"previous map")
        output.chmod(existing_mode)
    previous_mask = os.umask(mask)
    try:
        render_track_maps.replace_png(scene, output)
    finally:
        os.umask(previous_mask)
    expected_mode = (0o666 & ~mask) if existing_mode is None else existing_mode
    assert stat.S_IMODE(output.stat().st_mode) == expected_mode
    with Image.open(output) as image:
        image.verify()
    assert not list(tmp_path.glob(".track-*"))


def test_permission_copy_failure_preserves_existing_map(monkeypatch, tmp_path) -> None:
    xml = tmp_path / "track.xml"
    write_track(xml)
    output = tmp_path / "track.png"
    output.write_bytes(b"previous map")

    def fail_copymode(source, destination):
        assert source == output
        assert destination.is_file()
        raise PermissionError("simulated permission-copy failure")

    monkeypatch.setattr(render_track_maps.shutil, "copymode", fail_copymode)
    with pytest.raises(PermissionError, match="simulated permission-copy failure"):
        render_track_maps.replace_png(scene_from_xml(xml, size=64), output)
    assert output.read_bytes() == b"previous map"
    assert not list(tmp_path.glob(".track-*"))
