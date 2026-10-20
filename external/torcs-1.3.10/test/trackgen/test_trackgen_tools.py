#!/usr/bin/env python3

##############################################################################
#
#    file                 : test_trackgen_tools.py
#    created              : Mon Jul 27 2026
#    copyright            : (C) 2026 by Bernhard Wymann
#    email                : berniw@bluewin.ch
#
##############################################################################

##############################################################################
#                                                                            #
#   This program is free software; you can redistribute it and/or modify     #
#   it under the terms of the GNU General Public License as published by     #
#   the Free Software Foundation; either version 2 of the License, or        #
#   (at your option) any later version.                                      #
#                                                                            #
##############################################################################

import argparse
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import compare_ac
import run_regression
import validate_ac
import validate_crossing_seams


def make_ac(vertices, surfaces):
    lines = ["AC3Db", "OBJECT world", "kids 1", "OBJECT poly", "numvert " + str(len(vertices))]
    lines.extend(" ".join(str(value) for value in vertex) for vertex in vertices)
    lines.append("numsurf " + str(len(surfaces)))
    for surface in surfaces:
        lines.extend(("SURF 0x10", "mat 0", "refs " + str(len(surface))))
        lines.extend(f"{reference} 0 0" for reference in surface)
    lines.append("kids 0")
    return "\n".join(lines) + "\n"


def make_named_ac(objects):
    lines = ["AC3Db", "OBJECT world", "kids " + str(len(objects))]
    for name, vertices, surfaces in objects:
        lines.extend(("OBJECT poly", f'name "{name}"', "numvert " + str(len(vertices))))
        lines.extend(" ".join(str(value) for value in vertex) for vertex in vertices)
        lines.append("numsurf " + str(len(surfaces)))
        for surface in surfaces:
            lines.extend(("SURF 0x10", "mat 0", "refs " + str(len(surface))))
            lines.extend(f"{reference} 0 0" for reference in surface)
        lines.append("kids 0")
    return "\n".join(lines) + "\n"


class CrossingSeamTest(unittest.TestCase):
    def test_accepts_subdivided_and_reversed_edges(self):
        first, second = (0, 0, 0), (4, 4, 4)
        intervals = [validate_crossing_seams.edge_interval(
            first, second, start, end, 1e-4
        ) for start, end in (((0, 0, 0), (1, 1, 1)),
                             ((3, 3, 3), (1, 1, 1)),
                             ((3, 3, 3), (5, 5, 5)))]
        self.assertAlmostEqual(0.0, validate_crossing_seams.uncovered_fraction(intervals))

    def test_detects_internal_gap_despite_matching_endpoints(self):
        self.assertAlmostEqual(0.2, validate_crossing_seams.uncovered_fraction(
            [(0.0, 0.4), (0.6, 1.0)]))

    def test_does_not_match_edge_at_wrong_height(self):
        self.assertIsNone(validate_crossing_seams.edge_interval(
            (0, 0, 0), (4, 0, 0), (0, 1, 0), (4, 1, 0), 1e-4))

    def test_detects_missing_face_in_exported_socket(self):
        vertices = [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2)]
        with tempfile.TemporaryDirectory() as temporary_directory:
            track_path = pathlib.Path(temporary_directory) / 'unit-trk.ac'
            mesh_path = track_path.with_name('unit-msh.ac')
            track_path.write_text(make_named_ac([
                ('TRKSOCKET_R0', vertices, [(0, 1, 2)]),
                ('TRKBRIDGE0', vertices, [(0, 3, 1)]),
            ]), encoding='ascii')
            mesh_path.write_text(make_named_ac([
                ('TERR0', vertices, [(1, 3, 2), (2, 3, 0)]),
            ]), encoding='ascii')
            self.assertTrue(validate_crossing_seams.validate_crossing_seams(track_path)['passed'])
            mesh_path.write_text(make_named_ac([
                ('TERR0', vertices, [(1, 3, 2)]),
            ]), encoding='ascii')
            result = validate_crossing_seams.validate_crossing_seams(track_path)
            self.assertFalse(result['passed'])
            self.assertEqual(2, len(result['openEdges']))

    def test_rejects_duplicate_socket_geometry_with_distinct_vertex_indices(self):
        vertices = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'unit-trk.ac'
            path.write_text(make_named_ac([
                ('TRKSOCKET_R0', vertices + vertices, [(0, 1, 2), (5, 4, 3)]),
            ]), encoding='ascii')
            path.with_name('unit-msh.ac').write_text(make_named_ac([
                ('TERR0', [(0, 0, 0), (0, 0, 2), (2, 0, 0)], [(0, 1, 2)]),
            ]), encoding='ascii')
            with self.assertRaisesRegex(validate_ac.AcValidationError, 'duplicate crossing triangle'):
                validate_crossing_seams.validate_crossing_seams(path)

    def test_rejects_collapsed_socket_triangle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'unit-trk.ac'
            path.write_text(make_named_ac([
                ('TRKSOCKET_R0', [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)]),
            ]), encoding='ascii')
            path.with_name('unit-msh.ac').write_text(make_named_ac([
                ('TERR0', [(0, 0, 0), (0, 0, 2), (2, 0, 0)], [(0, 1, 2)]),
            ]), encoding='ascii')
            with self.assertRaisesRegex(validate_ac.AcValidationError, 'collapsed crossing triangle'):
                validate_crossing_seams.validate_crossing_seams(path)


class AcParserTest(unittest.TestCase):
    def test_accepts_valid_triangle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "valid-msh.ac"
            path.write_text(make_ac([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]), encoding="ascii")

            metrics = validate_ac.AcParser(path, 1e-10).parse()

            self.assertEqual({"objects": 2, "vertices": 3, "surfaces": 1}, metrics)

    def test_rejects_zero_area_triangle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "invalid-msh.ac"
            path.write_text(make_ac([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)]), encoding="ascii")

            with self.assertRaisesRegex(validate_ac.AcValidationError, "zero area"):
                validate_ac.AcParser(path, 1e-10).parse()

    def test_rejects_negative_record_count(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "invalid-msh.ac"
            path.write_text("AC3Db\nOBJECT world\nkids -1\n", encoding="ascii")

            with self.assertRaisesRegex(validate_ac.AcValidationError, "negative child count"):
                validate_ac.AcParser(path, 1e-10).parse()

    def test_main_creates_report_parent_directories(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            mesh_directory = test_root / "generated" / "road" / "unit"
            mesh_directory.mkdir(parents=True)
            mesh_path = mesh_directory / "unit-msh.ac"
            mesh_path.write_text(make_ac([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]), encoding="ascii")
            report_path = pathlib.Path(temporary_directory) / "reports" / "nested" / "validation.json"
            arguments = [
                "validate_ac.py",
                "--test-root",
                str(test_root),
                "--report",
                str(report_path),
            ]

            with mock.patch.object(sys, "argv", arguments), contextlib.redirect_stdout(io.StringIO()):
                result = validate_ac.main()

            self.assertEqual(0, result)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(1, report["summary"]["passed"])
            self.assertFalse(report["results"][0]["crossingOverlapValidated"])

    def test_main_rejects_missing_generated_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            test_root.mkdir()
            arguments = ["validate_ac.py", "--test-root", str(test_root)]

            with mock.patch.object(sys, "argv", arguments):
                with self.assertRaisesRegex(RuntimeError, "Generated directory not found"):
                    validate_ac.main()

    def test_main_rejects_empty_generated_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            (test_root / "generated").mkdir(parents=True)
            arguments = ["validate_ac.py", "--test-root", str(test_root)]

            with mock.patch.object(sys, "argv", arguments):
                with self.assertRaisesRegex(RuntimeError, "No generated terrain AC files found"):
                    validate_ac.main()

    def test_rejects_invalid_minimum_area(self):
        for value in ("-1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    validate_ac.nonnegative_finite_float(value)

    def test_crossing_overlap_accepts_shared_boundary(self):
        objects = [
            ("TERR0", [(0, 0, 0.1), (10, 0, 0.1), (5, 0, 5)], [(0, 1, 2)]),
            ("TRKFLOOR_R0", [(2, 0, 0.1), (8, 0, 0.1), (2, 0, -5)], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "shared.ac"
            path.write_text(make_named_ac(objects), encoding="ascii")
            parser = validate_ac.AcParser(path, 1e-10)
            parser.parse()

            metrics = validate_ac.validate_crossing_terrain_overlap(
                parser, parser, 0.0
            )

            self.assertEqual(0.0, metrics["maximumCrossingTerrainOverlap"])

    def test_crossing_overlap_rejects_positive_area(self):
        for name in ("TRKBRIDGE0", "TRKBRIDGE_UNDERSIDE0", "TRKFILLER_RR0"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                objects = [
                    ("TERR0", [(0, 0, 0), (2, 0, 0), (0, 0, 2)], [(0, 1, 2)]),
                    (name, [(0.25, 1, 0.25), (1, 1, 0.25), (0.25, 1, 1)], [(0, 1, 2)]),
                ]
                path = pathlib.Path(temporary_directory) / "overlap.ac"
                path.write_text(make_named_ac(objects), encoding="ascii")
                self.assertTrue(validate_ac.combined_has_crossing_objects(path))
                parser = validate_ac.AcParser(path, 1e-10)
                parser.parse()

                with self.assertRaisesRegex(validate_ac.AcValidationError, "overlaps crossing"):
                    validate_ac.validate_crossing_terrain_overlap(parser, parser, 1e-8)

    def test_zero_crossing_overlap_limit_rejects_tiny_overlap(self):
        objects = [
            ("TERR0", [(0, 0, 0), (1, 0, 0), (0, 0, 1)], [(0, 1, 2)]),
            ("TRKBRIDGE0", [(0, 1, 0), (1e-8, 1, 0), (0, 1, 1e-8)], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "tiny-overlap.ac"
            path.write_text(make_named_ac(objects), encoding="ascii")
            parser = validate_ac.AcParser(path, 0.0)
            parser.parse()

            with self.assertRaisesRegex(validate_ac.AcValidationError, "overlaps crossing"):
                validate_ac.validate_crossing_terrain_overlap(parser, parser, 0.0)

    def test_shared_edge_same_side_does_not_underflow_to_contact(self):
        first = ((0.0, 0.0), (1.0, 0.0), (0.0, 1e-200))
        second = ((0.0, 0.0), (1.0, 0.0), (0.0, 2e-200))

        overlap = validate_ac.triangle_overlap_area(first, second, 0.0)

        self.assertGreater(overlap, 0.0)

    def test_zero_tolerance_intersects_near_parallel_lines(self):
        intersection = validate_ac.line_intersection(
            (0.0, 0.0), (1.0, 1e-16),
            (0.0, 5e-17), (1.0, 5e-17),
            0.0,
        )

        self.assertAlmostEqual(0.5, intersection[0])
        self.assertAlmostEqual(5e-17, intersection[1])

    def test_crossing_overlap_aggregates_each_object_pair(self):
        side = (12e-6) ** 0.5
        terrain = [(0, 0, 0), (10, 0, 0), (0, 0, 10)]
        crossing = [
            (1, 1, 1), (1 + side, 1, 1), (1, 1, 1 + side),
            (2, 1, 2), (2 + side, 1, 2), (2, 1, 2 + side),
        ]
        objects = [
            ("TERR0", terrain, [(0, 1, 2)]),
            ("TRKBRIDGE0", crossing, [(0, 1, 2), (3, 4, 5)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "aggregate.ac"
            path.write_text(make_named_ac(objects), encoding="ascii")
            parser = validate_ac.AcParser(path, 0.0)
            parser.parse()

            with self.assertRaisesRegex(validate_ac.AcValidationError, "overlaps crossing"):
                validate_ac.validate_crossing_terrain_overlap(parser, parser, 1e-5)

    def test_crossing_overlap_aggregates_below_positive_limit(self):
        side = (1.5e-12) ** 0.5
        terrain = [(0, 0, 0), (10, 0, 0), (0, 0, 10)]
        crossing = [
            (1, 1, 1), (1 + side, 1, 1), (1, 1, 1 + side),
            (2, 1, 2), (2 + side, 1, 2), (2, 1, 2 + side),
        ]
        objects = [
            ("TERR0", terrain, [(0, 1, 2)]),
            ("TRKBRIDGE0", crossing, [(0, 1, 2), (3, 4, 5)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "small-aggregate.ac"
            path.write_text(make_named_ac(objects), encoding="ascii")
            parser = validate_ac.AcParser(path, 0.0)
            parser.parse()

            with self.assertRaisesRegex(validate_ac.AcValidationError, "overlaps crossing"):
                validate_ac.validate_crossing_terrain_overlap(parser, parser, 1e-12)

    def test_crossing_overlap_keeps_duplicate_names_as_separate_objects(self):
        side = (15e-6) ** 0.5
        objects = [
            ("TERR0", [(0, 0, 0), (2, 0, 0), (0, 0, 2)], [(0, 1, 2)]),
            ("TRKBRIDGE0", [
                (0.25, 1, 0.25), (0.25 + side, 1, 0.25),
                (0.25, 1, 0.25 + side),
            ], [(0, 1, 2)]),
            ("TERR0", [(10, 0, 10), (12, 0, 10), (10, 0, 12)], [(0, 1, 2)]),
            ("TRKBRIDGE0", [
                (10.25, 1, 10.25), (10.25 + side, 1, 10.25),
                (10.25, 1, 10.25 + side),
            ], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "duplicate-names.ac"
            path.write_text(make_named_ac(objects), encoding="ascii")
            parser = validate_ac.AcParser(path, 0.0)
            parser.parse()

            metrics = validate_ac.validate_crossing_terrain_overlap(
                parser, parser, 1e-5
            )

            self.assertLessEqual(metrics["maximumCrossingTerrainOverlap"], 1e-5)

    def test_crossing_overlap_uses_requested_mesh_terrain(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            generated = test_root / "generated" / "road" / "unit"
            generated.mkdir(parents=True)
            terrain = [(0, 0, 0), (2, 0, 0), (0, 0, 2)]
            crossing = [(0.25, 1, 0.25), (1, 1, 0.25), (0.25, 1, 1)]
            (generated / "unit-msh.ac").write_text(
                make_named_ac([("TERR0", terrain, [(0, 1, 2)])]),
                encoding="ascii",
            )
            (generated / "unit.ac").write_text(
                make_named_ac([
                    ("TERR0", [(10, 0, 10), (12, 0, 10), (10, 0, 12)], [(0, 1, 2)]),
                    ("TRKBRIDGE0", crossing, [(0, 1, 2)]),
                ]),
                encoding="ascii",
            )
            arguments = ["validate_ac.py", "--test-root", str(test_root)]

            with mock.patch.object(sys, "argv", arguments), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = validate_ac.main()

            self.assertEqual(1, result)

    def test_crossing_overlap_uses_split_track_geometry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            generated = test_root / "generated" / "road" / "unit"
            generated.mkdir(parents=True)
            terrain = [(0, 0, 0), (2, 0, 0), (0, 0, 2)]
            crossing = [(0.25, 1, 0.25), (1, 1, 0.25), (0.25, 1, 1)]
            (generated / "unit-msh.ac").write_text(
                make_named_ac([("TERR0", terrain, [(0, 1, 2)])]),
                encoding="ascii",
            )
            (generated / "unit-trk.ac").write_text(
                make_named_ac([("TRKBRIDGE0", crossing, [(0, 1, 2)])]),
                encoding="ascii",
            )
            report_path = pathlib.Path(temporary_directory) / "validation.json"
            arguments = [
                "validate_ac.py", "--test-root", str(test_root),
                "--report", str(report_path),
            ]

            with mock.patch.object(sys, "argv", arguments), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = validate_ac.main()

            self.assertEqual(1, result)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["results"][0]["crossingOverlapValidated"])

    def test_split_track_without_crossing_ignores_stale_combined_crossing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            generated = test_root / "generated" / "road" / "unit"
            generated.mkdir(parents=True)
            terrain = [(0, 0, 0), (2, 0, 0), (0, 0, 2)]
            crossing = [(0.25, 1, 0.25), (1, 1, 0.25), (0.25, 1, 1)]
            (generated / "unit-msh.ac").write_text(
                make_named_ac([("TERR0", terrain, [(0, 1, 2)])]),
                encoding="ascii",
            )
            (generated / "unit-trk.ac").write_text(
                make_named_ac([("tkMn0", terrain, [(0, 1, 2)])]),
                encoding="ascii",
            )
            (generated / "unit.ac").write_text(
                make_named_ac([("TRKBRIDGE0", crossing, [(0, 1, 2)])]),
                encoding="ascii",
            )
            arguments = ["validate_ac.py", "--test-root", str(test_root)]

            with mock.patch.object(sys, "argv", arguments), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = validate_ac.main()

            self.assertEqual(0, result)

    def test_malformed_split_track_does_not_report_completed_overlap_check(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = pathlib.Path(temporary_directory) / "trackgen"
            generated = test_root / "generated" / "road" / "unit"
            generated.mkdir(parents=True)
            terrain = [(0, 0, 0), (2, 0, 0), (0, 0, 2)]
            (generated / "unit-msh.ac").write_text(
                make_named_ac([("TERR0", terrain, [(0, 1, 2)])]),
                encoding="ascii",
            )
            (generated / "unit-trk.ac").write_text(
                'AC3Db\nOBJECT world\nkids 1\nOBJECT poly\nname "TRKBRIDGE0"\n',
                encoding="ascii",
            )
            report_path = pathlib.Path(temporary_directory) / "validation.json"
            arguments = [
                "validate_ac.py", "--test-root", str(test_root),
                "--report", str(report_path),
            ]

            with mock.patch.object(sys, "argv", arguments), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = validate_ac.main()

            self.assertEqual(1, result)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["results"][0]["crossingOverlapValidated"])

    def test_polygon_area_handles_skinny_and_translated_triangles(self):
        self.assertAlmostEqual(
            5e-5, validate_ac.polygon_area([(0, 0), (100, 0), (0, 1e-6)])
        )
        self.assertAlmostEqual(
            1.25e-5,
            validate_ac.polygon_area([
                (1e6, 1e6), (1e6 + 0.005, 1e6), (1e6, 1e6 + 0.005)
            ]),
            places=10,
        )

    def test_crossing_overlap_rejects_object_transforms(self):
        objects = [
            ("TERR0", [(0, 0, 0), (2, 0, 0), (0, 0, 2)], [(0, 1, 2)]),
            ("TRKBRIDGE0", [(0.25, 1, 0.25), (1, 1, 0.25), (0.25, 1, 1)], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "transform.ac"
            contents = make_named_ac(objects).replace(
                'name "TRKBRIDGE0"\n', 'name "TRKBRIDGE0"\nloc 10 0 0\n'
            )
            path.write_text(contents, encoding="ascii")
            parser = validate_ac.AcParser(path, 1e-10)
            parser.parse()

            with self.assertRaisesRegex(validate_ac.AcValidationError, "flattened"):
                validate_ac.validate_crossing_terrain_overlap(parser, parser, 1e-8)

    def test_crossing_overlap_rejects_transformed_vertical_object(self):
        objects = [
            ("TERR0", [(0, 0, 0), (2, 0, 0), (0, 0, 2)], [(0, 1, 2)]),
            ("TRKSOCKET_R0", [(1, 0, 0), (1, 2, 0), (1, 1, 1)], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "vertical-transform.ac"
            contents = make_named_ac(objects).replace(
                'name "TRKSOCKET_R0"\n',
                'name "TRKSOCKET_R0"\nrot 1 0 0 0 0 -1 0 1 0\n',
            )
            path.write_text(contents, encoding="ascii")
            parser = validate_ac.AcParser(path, 0.0)
            parser.parse()

            with self.assertRaisesRegex(validate_ac.AcValidationError, "flattened"):
                validate_ac.validate_crossing_terrain_overlap(parser, parser, 0.0)

    def test_crossing_overlap_ignores_unrelated_object_transforms(self):
        objects = [
            ("TERR0", [(0, 0, 0), (2, 0, 0), (0, 0, 2)], [(0, 1, 2)]),
            ("TRKBRIDGE0", [(2, 1, 0), (2, 1, 2), (0, 1, 2)], [(0, 1, 2)]),
            ("TREE0", [(10, 0, 10), (11, 0, 10), (10, 1, 10)], [(0, 1, 2)]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = pathlib.Path(temporary_directory) / "scenery-transform.ac"
            contents = make_named_ac(objects).replace(
                'name "TREE0"\n', 'name "TREE0"\nloc 10 0 0\n'
            )
            path.write_text(contents, encoding="ascii")
            parser = validate_ac.AcParser(path, 1e-10)
            parser.parse()

            metrics = validate_ac.validate_crossing_terrain_overlap(
                parser, parser, 1e-8
            )

            self.assertLessEqual(metrics["maximumCrossingTerrainOverlap"], 1e-8)


class RegressionRunnerTest(unittest.TestCase):
    def test_main_creates_track_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            test_root = root / "trackgen"
            input_directory = test_root / "source" / "road" / "unit"
            input_directory.mkdir(parents=True)
            (input_directory / "unit.xml").write_text("", encoding="ascii")
            (test_root / "generated").mkdir()
            trackgen = root / "trackgen.exe"
            trackgen.write_text("", encoding="ascii")
            arguments = [
                "run_regression.py",
                "--trackgen",
                str(trackgen),
                "--test-root",
                str(test_root),
                "--report-dir",
                str(root / "report"),
            ]

            def run_trackgen(command, **unused_arguments):
                output_directory = pathlib.Path(command[command.index("-o") + 1])
                self.assertTrue(output_directory.is_dir())
                return mock.Mock(returncode=0)

            with mock.patch.object(sys, "argv", arguments), \
                    mock.patch.object(run_regression.subprocess, "run",
                                      side_effect=run_trackgen), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = run_regression.main()

            self.assertEqual(0, result)
            self.assertTrue((test_root / "generated" / "road" / "unit").is_dir())

    def test_find_tracks_filters_requested_track(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = pathlib.Path(temporary_directory)
            first = source_root / "road" / "first"
            second = source_root / "road" / "second"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "first.xml").write_text("", encoding="ascii")
            (second / "second.xml").write_text("", encoding="ascii")

            tracks = run_regression.find_tracks(source_root, ["road/second"])

            self.assertEqual([("road/second", second)], tracks)

    def test_find_tracks_rejects_unknown_track(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(RuntimeError, "Unknown tracks: road/missing"):
                run_regression.find_tracks(pathlib.Path(temporary_directory), ["road/missing"])

    def test_write_report_replaces_existing_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = pathlib.Path(temporary_directory) / "report.json"
            report_path.write_text("old", encoding="ascii")

            run_regression.write_report(report_path, {"status": "passed"})

            self.assertEqual({"status": "passed"}, json.loads(report_path.read_text(encoding="utf-8")))
            self.assertFalse(report_path.with_suffix(".tmp").exists())


class AcComparisonTest(unittest.TestCase):
    def make_fixture(self, root, relative_path, reference, generated=None):
        source_path = root / "source" / relative_path
        generated_path = root / "generated" / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(reference)
        if generated is not None:
            generated_path.write_bytes(generated)

    def test_reports_equal_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            self.make_fixture(root, pathlib.Path("road/unit/unit.ac"), b"same\n", b"same\n")

            results = compare_ac.compare_files(root / "source", root / "generated", [])

            self.assertEqual("equal", results[0]["status"])
            self.assertEqual(results[0]["referenceSha256"], results[0]["generatedSha256"])

    def test_reports_changed_missing_and_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            self.make_fixture(root, pathlib.Path("road/unit/changed.ac"), b"old", b"new")
            self.make_fixture(root, pathlib.Path("road/unit/missing.ac"), b"missing")
            extra_path = root / "generated" / "road" / "unit" / "extra.ac"
            extra_path.write_bytes(b"extra")

            results = compare_ac.compare_files(root / "source", root / "generated", [])

            self.assertEqual(
                {"changed", "missing", "extra"},
                {result["status"] for result in results},
            )

    def test_accepts_only_crlf_lf_differences_without_rewriting_files(self):
        for reference, generated in ((b"AC3Db\nOBJECT world\n", b"AC3Db\r\nOBJECT world\r\n"),
                                     (b"AC3Db\r\nOBJECT world\n", b"AC3Db\nOBJECT world\r\n")):
            with self.subTest(reference=reference, generated=generated), \
                    tempfile.TemporaryDirectory() as temporary_directory:
                root = pathlib.Path(temporary_directory)
                relative = pathlib.Path("road/unit/unit.ac")
                self.make_fixture(root, relative, reference, generated)
                result = compare_ac.compare_files(root / "source", root / "generated", [])[0]
                self.assertEqual("equal", result["status"])
                self.assertTrue(result["lineEndingsOnly"])
                self.assertNotEqual(result["referenceSha256"], result["generatedSha256"])
                self.assertEqual(reference, (root / "source" / relative).read_bytes())
                self.assertEqual(generated, (root / "generated" / relative).read_bytes())
                strict = compare_ac.compare_files(root / "source", root / "generated", [], strict=True)
                self.assertEqual("changed", strict[0]["status"])

    def test_normalization_preserves_content_whitespace_and_eof_differences(self):
        for generated in (b"1.000001\r\n", b"1.000000 \r\n", b"1.000000",
                          b"1.000000\r", b"1.000000\r\n\r\n", b""):
            with self.subTest(generated=generated), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                self.make_fixture(root, pathlib.Path("road/unit/unit.ac"), b"1.000000\n", generated)
                result = compare_ac.compare_files(root / "source", root / "generated", [])[0]
                self.assertEqual("changed", result["status"])
                self.assertFalse(result["lineEndingsOnly"])

    def test_main_reports_line_ending_only_matches_and_supports_strict_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.make_fixture(root, pathlib.Path("road/unit/unit.ac"), b"same\n", b"same\r\n")
            report_path = root / "comparison.json"
            arguments = ["compare_ac.py", "--test-root", str(root), "--report", str(report_path)]
            with mock.patch.object(sys, "argv", arguments), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, compare_ac.main())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("crlf-to-lf", report["comparison"])
            self.assertEqual(1, report["lineEndingOnlyFiles"])
            with mock.patch.object(sys, "argv", arguments + ["--strict"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(1, compare_ac.main())
            self.assertEqual("binary", json.loads(report_path.read_text(encoding="utf-8"))["comparison"])

    def test_filters_requested_tracks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            self.make_fixture(root, pathlib.Path("road/first/first.ac"), b"one", b"one")
            self.make_fixture(root, pathlib.Path("road/second/second.ac"), b"two", b"two")

            results = compare_ac.compare_files(
                root / "source", root / "generated", ["road/second"]
            )

            self.assertEqual(["road/second/second.ac"], [result["file"] for result in results])

    def test_strict_comparison_rechecks_content_with_unchanged_size_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            relative = pathlib.Path("road/unit/unit.ac")
            self.make_fixture(root, relative, b"old\n", b"old\n")
            generated = root / "generated" / relative
            timestamp = generated.stat()
            self.assertEqual("equal", compare_ac.compare_files(
                root / "source", root / "generated", [], strict=True)[0]["status"])
            generated.write_bytes(b"new\n")
            os.utime(generated, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
            self.assertEqual("changed", compare_ac.compare_files(
                root / "source", root / "generated", [], strict=True)[0]["status"])

    def test_rejects_unknown_track(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            self.make_fixture(root, pathlib.Path("road/unit/unit.ac"), b"same", b"same")

            with self.assertRaisesRegex(RuntimeError, "Unknown tracks: road/missing"):
                compare_ac.compare_files(
                    root / "source", root / "generated", ["road/missing"]
                )

    def test_main_writes_report_and_fails_for_difference(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            self.make_fixture(root, pathlib.Path("road/unit/unit.ac"), b"old", b"new")
            report_path = root / "reports" / "comparison.json"
            arguments = [
                "compare_ac.py", "--test-root", str(root), "--report", str(report_path)
            ]

            with mock.patch.object(sys, "argv", arguments), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = compare_ac.main()

            self.assertEqual(1, result)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(1, report["summary"]["changed"])


if __name__ == "__main__":
    unittest.main()
