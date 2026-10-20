# /***************************************************************************
#
#     file                 : test_apply_segments.py
#     created              : 27 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import xml.etree.ElementTree as ET

import torcs_track_tools.cli.apply_segments as apply_segments


def attstr(section: ET.Element, name: str) -> str:
    for child in section:
        if child.tag == "attstr" and child.get("name") == name:
            return child.get("val", "")
    return ""


def child_section(parent: ET.Element, name: str) -> ET.Element:
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    raise AssertionError(f"missing section: {name}")


def test_apply_segments_replaces_mainline_and_updates_metadata(monkeypatch, tmp_path) -> None:
    template_xml = tmp_path / "template.xml"
    segments_xml = tmp_path / "segments.xml"
    output_xml = tmp_path / "out" / "unit-track.xml"
    template_xml.write_text(
        """
<params name="Old Track">
  <section name="Header">
    <attstr name="name" val="Old Track"/>
    <attstr name="category" val="old"/>
  </section>
  <section name="Graphic">
    <attstr name="3d description" val="old.ac"/>
  </section>
  <section name="Main Track">
    <section name="Track Segments">
      <section name="Old Segment">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="10"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    segments_xml.write_text(
        """
<section name="First Straight">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="40"/>
</section>
<section name="Forced Start">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="60"/>
</section>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-apply-segments",
            "--template-xml",
            str(template_xml),
            "--segments-xml",
            str(segments_xml),
            "--output-xml",
            str(output_xml),
            "--track-name",
            "Unit Track",
            "--author",
            "Test Author",
            "--category",
            "road",
            "--description",
            "Generated for tests",
            "--graphic-description",
            "unit-track.ac",
            "--start-segment",
            "Forced Start",
        ],
    )

    assert apply_segments.main() == 0

    root = ET.parse(output_xml).getroot()
    header = child_section(root, "Header")
    graphic = child_section(root, "Graphic")
    main_track = child_section(root, "Main Track")
    track_segments = child_section(main_track, "Track Segments")
    segment_names = [child.get("name") for child in track_segments if child.tag == "section"]

    assert root.get("name") == "Unit Track"
    assert attstr(header, "name") == "Unit Track"
    assert attstr(header, "author") == "Test Author"
    assert attstr(header, "category") == "road"
    assert attstr(header, "description") == "Generated for tests"
    assert attstr(graphic, "3d description") == "unit-track.ac"
    assert segment_names == ["Forced Start", "First Straight"]
    assert "Old Segment" not in segment_names
    text = output_xml.read_text(encoding="utf-8")
    assert "file                 : unit-track.xml" in text
    assert "copyright            : (C)" in text
    assert "by Test Author" in text
    assert "license              : GNU General Public License version 2 or later" in text
    assert "This program is free software; you can redistribute it and/or modify" in text
    assert "either version 2 of the License, or" in text


def test_apply_segments_preserves_default_surfaces_entity(monkeypatch, tmp_path) -> None:
    template_xml = tmp_path / "template.xml"
    segments_xml = tmp_path / "segments.xml"
    output_xml = tmp_path / "unit-track.xml"
    template_xml.write_text(
        """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE params SYSTEM "../../../src/libs/tgf/params.dtd" [
  <!ENTITY default-surfaces SYSTEM "../../../data/tracks/surfaces.xml">
]>
<params>
  &default-surfaces;
  <section name="Main Track">
    <section name="Track Segments"/>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    segments_xml.write_text(
        """
<section name="Main Straight">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="40"/>
</section>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-apply-segments",
            "--template-xml",
            str(template_xml),
            "--segments-xml",
            str(segments_xml),
            "--output-xml",
            str(output_xml),
            "--author",
            "Test Author",
        ],
    )

    assert apply_segments.main() == 0

    assert "&default-surfaces;" in output_xml.read_text(encoding="utf-8")


def test_apply_segments_can_write_generic_segment_names(monkeypatch, tmp_path) -> None:
    template_xml = tmp_path / "template.xml"
    segments_xml = tmp_path / "segments.xml"
    output_xml = tmp_path / "unit-track.xml"
    template_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Track Segments"/>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    segments_xml.write_text(
        """
<section name="Original Venue Name">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="40"/>
</section>
<section name="Original Venue Name-2">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="50"/>
</section>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-apply-segments",
            "--template-xml",
            str(template_xml),
            "--segments-xml",
            str(segments_xml),
            "--output-xml",
            str(output_xml),
            "--author",
            "Test Author",
            "--segment-name-prefix",
            "segment",
        ],
    )

    assert apply_segments.main() == 0

    text = output_xml.read_text(encoding="utf-8")
    assert 'section name="segment-001"' in text
    assert 'section name="segment-002"' in text
    assert "Original Venue Name" not in text


def test_apply_segments_rejects_placeholder_author(monkeypatch, tmp_path) -> None:
    template_xml = tmp_path / "template.xml"
    segments_xml = tmp_path / "segments.xml"
    output_xml = tmp_path / "unit-track.xml"
    template_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Track Segments"/>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    segments_xml.write_text(
        """
<section name="Main Straight">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="40"/>
</section>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-apply-segments",
            "--template-xml",
            str(template_xml),
            "--segments-xml",
            str(segments_xml),
            "--output-xml",
            str(output_xml),
            "--author",
            "OpenCode",
        ],
    )

    try:
        apply_segments.main()
    except SystemExit as exc:
        assert "placeholder authors" in str(exc)
    else:
        raise AssertionError("placeholder author was accepted")
