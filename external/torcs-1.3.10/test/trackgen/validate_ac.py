#!/usr/bin/env python3

##############################################################################
#
#    file                 : validate_ac.py
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

"""Validate structure and terrain geometry in generated trackgen AC files.

The parser intentionally supports the AC3D records emitted by trackgen. It
reports malformed objects, non-finite values, invalid references, duplicate
triangles, and surfaces whose area is too small for usable terrain geometry.
"""

import argparse
import json
import math
import pathlib
import sys


CROSSING_OBJECT_PREFIXES = ("TRKBRIDGE", "TRKSOCKET", "TRKFILLER", "TRKFLOOR")


class AcValidationError(RuntimeError):
    """Raised when an AC file violates the generated-terrain contract."""

    pass


class AcParser:
    """Parse and validate one trackgen-generated AC3D terrain file."""

    def __init__(self, path, minimum_area, validate_surface_geometry=True):
        self.path = path
        self.minimum_area = minimum_area
        self.validate_surface_geometry = validate_surface_geometry
        self.lines = path.read_text(encoding="latin-1").splitlines()
        self.index = 0
        self.metrics = {
            "objects": 0,
            "vertices": 0,
            "surfaces": 0,
        }
        self.triangles = []
        self.has_object_transforms = False

    def error(self, message):
        """Raise a validation error annotated with the current source line."""
        raise AcValidationError(f"line {self.index + 1}: {message}")

    def current(self):
        if self.index >= len(self.lines):
            self.error("unexpected end of file")
        return self.lines[self.index].strip()

    def consume(self, prefix=None):
        text = self.current()
        if prefix is not None and not text.startswith(prefix):
            self.error(f"expected {prefix!r}, found {text!r}")
        self.index += 1
        return text

    def parse_integer(self, text, field):
        try:
            value = int(text.split()[1])
        except (IndexError, ValueError):
            self.error(f"invalid {field}: {text!r}")
        if value < 0:
            self.error(f"negative {field}: {text!r}")
        return value

    def parse_vertex(self):
        text = self.consume()
        try:
            values = tuple(float(value) for value in text.split())
        except ValueError:
            self.error(f"invalid vertex: {text!r}")
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            self.error(f"invalid vertex: {text!r}")
        return values

    def parse_reference(self, vertex_count):
        text = self.consume()
        fields = text.split()
        try:
            vertex_index = int(fields[0])
            texture_coordinates = tuple(float(value) for value in fields[1:])
        except (IndexError, ValueError):
            self.error(f"invalid surface reference: {text!r}")
        if len(texture_coordinates) != 2:
            self.error(f"surface reference must have two texture coordinates: {text!r}")
        if not all(math.isfinite(value) for value in texture_coordinates):
            self.error(f"non-finite texture coordinate: {text!r}")
        if vertex_index < 0 or vertex_index >= vertex_count:
            self.error(f"vertex reference {vertex_index} outside 0..{vertex_count - 1}")
        return vertex_index

    def validate_triangle(self, references, vertices, seen_surfaces):
        """Validate triangle references, uniqueness, finiteness, and area."""
        if len(references) != 3:
            self.error(f"terrain surface has {len(references)} references instead of 3")
        if len(set(references)) != 3:
            self.error(f"terrain surface has repeated references {references}")
        canonical = tuple(sorted(references))
        if canonical in seen_surfaces:
            self.error(f"duplicate terrain surface {canonical}")
        seen_surfaces.add(canonical)

        first, second, third = (vertices[index] for index in references)
        first_edge = tuple(second[index] - first[index] for index in range(3))
        second_edge = tuple(third[index] - first[index] for index in range(3))
        cross_product = (
            first_edge[1] * second_edge[2] - first_edge[2] * second_edge[1],
            first_edge[2] * second_edge[0] - first_edge[0] * second_edge[2],
            first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0],
        )
        double_area = math.sqrt(sum(value * value for value in cross_product))
        if (self.validate_surface_geometry
                and (not math.isfinite(double_area) or double_area <= self.minimum_area)):
            self.error(f"terrain surface has zero area: {references}")
        return first, second, third

    def parse_surfaces(self, count, vertices):
        seen_surfaces = set()
        triangles = []
        for unused_surface in range(count):
            self.consume("SURF ")
            self.consume("mat ")
            reference_line = self.consume("refs ")
            reference_count = self.parse_integer(reference_line, "reference count")
            references = [
                self.parse_reference(len(vertices)) for unused_reference in range(reference_count)
            ]
            triangles.append(self.validate_triangle(references, vertices, seen_surfaces))
            self.metrics["surfaces"] += 1
        return triangles

    def parse_name(self, text):
        """Parse the quoted object names emitted by trackgen."""
        value = text[len("name ") :].strip()
        if len(value) < 2 or value[0] != '"' or value[-1] != '"':
            self.error(f"invalid object name: {text!r}")
        return value[1:-1]

    def parse_object(self, inherited_transform=False):
        """Parse one object and all recursively declared child objects."""
        self.consume("OBJECT ")
        object_index = self.metrics["objects"]
        self.metrics["objects"] += 1
        object_name = ""
        object_transformed = inherited_transform
        vertices = []
        triangles = []
        while True:
            text = self.current()
            if text.startswith("name "):
                object_name = self.parse_name(self.consume())
            elif text.startswith(("loc ", "rot ")):
                self.has_object_transforms = True
                object_transformed = True
                self.consume()
            elif text.startswith(("texture ", "texrep ", "crease ", "url ")):
                self.consume()
            elif text.startswith("numvert "):
                count = self.parse_integer(self.consume(), "vertex count")
                vertices = [self.parse_vertex() for unused_vertex in range(count)]
                self.metrics["vertices"] += count
            elif text.startswith("numsurf "):
                surface_count = self.parse_integer(self.consume(), "surface count")
                triangles.extend(self.parse_surfaces(surface_count, vertices))
            elif text.startswith("kids "):
                child_count = self.parse_integer(self.consume(), "child count")
                self.triangles.extend(
                    (object_index, object_name, triangle, object_transformed)
                    for triangle in triangles
                )
                for unused_child in range(child_count):
                    self.parse_object(object_transformed)
                return
            else:
                self.error(f"unexpected object record {text!r}")

    def parse(self):
        """Validate the complete file and return object and geometry counts."""
        if not self.lines or self.consume() != "AC3Db":
            self.error("missing AC3Db header")
        while self.index < len(self.lines) and self.current().startswith("MATERIAL "):
            self.consume()
        self.parse_object()
        while self.index < len(self.lines) and not self.current():
            self.consume()
        if self.index != len(self.lines):
            self.error(f"trailing record {self.current()!r}")
        return self.metrics


def cross_2d(first, second, third):
    """Return the signed 2D cross product of AB and AC."""
    return ((second[0] - first[0]) * (third[1] - first[1])
            - (second[1] - first[1]) * (third[0] - first[0]))


def polygon_area(points):
    """Return the absolute area of one ordered 2D polygon."""
    if len(points) < 3:
        return 0.0
    origin = points[0]
    return abs(sum(
        (points[index][0] - origin[0]) * (points[index + 1][1] - origin[1])
        - (points[index + 1][0] - origin[0]) * (points[index][1] - origin[1])
        for index in range(1, len(points) - 1)
    )) / 2.0


def line_intersection(start, end, clip_start, clip_end, epsilon=1e-15):
    """Intersect a polygon edge with an infinite clipping line."""
    edge_x = end[0] - start[0]
    edge_y = end[1] - start[1]
    clip_x = clip_end[0] - clip_start[0]
    clip_y = clip_end[1] - clip_start[1]
    denominator = edge_x * clip_y - edge_y * clip_x
    if abs(denominator) <= epsilon:
        return end
    offset_x = clip_start[0] - start[0]
    offset_y = clip_start[1] - start[1]
    parameter = (offset_x * clip_y - offset_y * clip_x) / denominator
    return start[0] + parameter * edge_x, start[1] + parameter * edge_y


def clip_triangle(subject, clip, epsilon=1e-12):
    """Clip one 2D triangle against another convex 2D triangle."""
    output = list(subject)
    orientation = 1.0 if cross_2d(clip[0], clip[1], clip[2]) >= 0.0 else -1.0
    for edge_index in range(3):
        clip_start = clip[edge_index]
        clip_end = clip[(edge_index + 1) % 3]
        input_points = output
        output = []
        if not input_points:
            break
        start = input_points[-1]
        start_inside = orientation * cross_2d(clip_start, clip_end, start) >= -epsilon
        for end in input_points:
            end_inside = orientation * cross_2d(clip_start, clip_end, end) >= -epsilon
            if end_inside:
                if not start_inside:
                    output.append(line_intersection(
                        start, end, clip_start, clip_end,
                        0.0 if epsilon == 0.0 else 1e-15,
                    ))
                output.append(end)
            elif start_inside:
                output.append(line_intersection(
                    start, end, clip_start, clip_end,
                    0.0 if epsilon == 0.0 else 1e-15,
                ))
            start = end
            start_inside = end_inside
    return output


def triangle_overlap_area(first, second, epsilon=1e-12):
    """Return overlap area, treating a shared opposite-side edge as contact."""
    for first_index in range(3):
        first_start = first[first_index]
        first_end = first[(first_index + 1) % 3]
        first_other = first[(first_index + 2) % 3]
        for second_index in range(3):
            second_start = second[second_index]
            second_end = second[(second_index + 1) % 3]
            second_other = second[(second_index + 2) % 3]
            if (cross_2d(first_start, first_end, second_start) != 0.0
                    or cross_2d(first_start, first_end, second_end) != 0.0):
                continue
            coordinate = 0 if abs(first_end[0] - first_start[0]) >= abs(
                first_end[1] - first_start[1]
            ) else 1
            overlap = min(
                max(first_start[coordinate], first_end[coordinate]),
                max(second_start[coordinate], second_end[coordinate]),
            ) - max(
                min(first_start[coordinate], first_end[coordinate]),
                min(second_start[coordinate], second_end[coordinate]),
            )
            first_side = cross_2d(first_start, first_end, first_other)
            second_side = cross_2d(first_start, first_end, second_other)
            opposite_sides = (
                first_side == 0.0 or second_side == 0.0
                or (first_side < 0.0) != (second_side < 0.0)
            )
            if overlap > 0.0 and opposite_sides:
                return 0.0
    intersection = clip_triangle(first, second, epsilon)
    return polygon_area(intersection) if len(intersection) >= 3 else 0.0


def projected_triangle(triangle):
    """Project trackgen AC coordinates onto their horizontal X/Z plane."""
    return tuple((vertex[0], vertex[2]) for vertex in triangle)


def triangle_bounds(triangle):
    """Return a projected triangle's minimum and maximum coordinates."""
    return (
        min(point[0] for point in triangle),
        min(point[1] for point in triangle),
        max(point[0] for point in triangle),
        max(point[1] for point in triangle),
    )


def bounds_overlap(first, second):
    """Test whether two closed 2D bounding boxes overlap."""
    return not (first[2] < second[0] or second[2] < first[0]
                or first[3] < second[1] or second[3] < first[1])


def validate_crossing_terrain_overlap(terrain_parser, crossing_parser, maximum_overlap):
    """Reject positive-area terrain intersections with generated crossings."""
    terrain = []
    crossings = []
    geometry_epsilon = 0.0
    for object_index, object_name, triangle, transformed in terrain_parser.triangles:
        if object_name.startswith("TERR"):
            if transformed:
                raise AcValidationError(
                    "crossing overlap validation requires flattened TERR objects without loc/rot"
                )
            projected = projected_triangle(triangle)
            if polygon_area(projected) > geometry_epsilon:
                terrain.append((
                    object_index, object_name, projected, triangle_bounds(projected)
                ))
    for object_index, object_name, triangle, transformed in crossing_parser.triangles:
        if object_name.startswith(CROSSING_OBJECT_PREFIXES):
            if transformed:
                raise AcValidationError(
                    "crossing overlap validation requires flattened crossing objects without loc/rot"
                )
            projected = projected_triangle(triangle)
            if polygon_area(projected) > geometry_epsilon:
                crossings.append((
                    object_index, object_name, projected, triangle_bounds(projected)
                ))
    if not terrain:
        raise AcValidationError("crossing overlap validation found no projected terrain surfaces")
    if not crossings:
        raise AcValidationError("crossing overlap validation found no projected crossing surfaces")

    overlap_by_object_pair = {}
    overlapping_triangle_pairs = 0
    for terrain_index, terrain_name, terrain_triangle, terrain_bounds in terrain:
        for crossing_index, crossing_name, crossing_triangle, crossing_bounds in crossings:
            if not bounds_overlap(terrain_bounds, crossing_bounds):
                continue
            overlap = triangle_overlap_area(
                terrain_triangle, crossing_triangle, geometry_epsilon
            )
            if overlap > 0.0:
                object_pair = (
                    terrain_index, terrain_name, crossing_index, crossing_name
                )
                overlap_by_object_pair[object_pair] = (
                    overlap_by_object_pair.get(object_pair, 0.0) + overlap
                )
                overlapping_triangle_pairs += 1
    if overlap_by_object_pair:
        maximum_pair, maximum_found = max(
            overlap_by_object_pair.items(), key=lambda item: item[1]
        )
    else:
        maximum_pair = (-1, "", -1, "")
        maximum_found = 0.0
    if maximum_found > maximum_overlap:
        raise AcValidationError(
            f"terrain object {maximum_pair[1]!r} overlaps crossing object "
            f"{maximum_pair[3]!r} "
            f"by {maximum_found:.12g} square metres (limit {maximum_overlap:.12g})"
        )
    return {
        "terrainProjectedSurfaces": len(terrain),
        "crossingProjectedSurfaces": len(crossings),
        "maximumCrossingTerrainOverlap": maximum_found,
        "overlappingTrianglePairs": overlapping_triangle_pairs,
    }


def combined_has_crossing_objects(path):
    """Return whether an AC file contains generated crossing geometry."""
    prefixes = tuple(f'name "{prefix}' for prefix in CROSSING_OBJECT_PREFIXES)
    with path.open("r", encoding="latin-1") as combined_file:
        return any(
            line.lstrip().startswith(prefixes)
            for line in combined_file
        )


def find_crossing_geometry_path(mesh_path):
    """Find split or combined crossing geometry paired with a terrain mesh."""
    base_name = mesh_path.name[: -len("-msh.ac")]
    split_path = mesh_path.with_name(base_name + "-trk.ac")
    if split_path.is_file():
        return split_path if combined_has_crossing_objects(split_path) else None
    combined_path = mesh_path.with_name(base_name + ".ac")
    if (combined_path.is_file()
            and combined_has_crossing_objects(combined_path)):
        return combined_path
    return None


def nonnegative_finite_float(value):
    """Parse a finite, non-negative floating-point command-line value."""
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(parsed) or parsed < 0.0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return parsed


def parse_arguments():
    """Parse command-line options for AC terrain validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate generated trackgen *-msh.ac terrain files for AC3D "
            "structure and usable triangle geometry."
        ),
        epilog="""examples:
  %(prog)s
  %(prog)s --track road/brondehach --track road/wheel-2
  %(prog)s --minimum-area 1e-8 --report trackgen-report/validation.json
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--test-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent,
        help="fixture root containing generated/ (default: script directory)",
    )
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        metavar="CATEGORY/NAME",
        help="validate one fixture; repeat to select multiple fixtures (default: all)",
    )
    parser.add_argument(
        "--minimum-area",
        type=nonnegative_finite_float,
        default=1e-10,
        help="finite, non-negative minimum doubled triangle area (default: %(default)s)",
    )
    parser.add_argument(
        "--maximum-crossing-overlap",
        type=nonnegative_finite_float,
        default=1e-5,
        help=(
            "maximum projected terrain/crossing object-pair overlap in square metres "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--report",
        type=pathlib.Path,
        metavar="PATH",
        help="write a JSON validation report, creating parent directories",
    )
    return parser.parse_args()


def main():
    """Validate requested terrain meshes and return a process exit status."""
    args = parse_arguments()
    test_root = args.test_root.resolve()
    generated_root = test_root / "generated"
    if not generated_root.is_dir():
        raise RuntimeError(f"Generated directory not found: {generated_root}")
    requested = set(args.track)
    paths = []
    for path in sorted(generated_root.rglob("*-msh.ac")):
        label = path.parent.relative_to(generated_root).as_posix()
        if not requested or label in requested:
            paths.append((label, path))
    if not paths and not requested:
        raise RuntimeError(f"No generated terrain AC files found in: {generated_root}")
    found = {label for label, unused_path in paths}
    missing = sorted(requested - found)
    results = []
    for label in missing:
        results.append({
            "track": label,
            "status": "missing",
            "path": None,
            "error": "missing file",
            "crossingOverlapValidated": False,
        })

    totals = {"objects": 0, "vertices": 0, "surfaces": 0}
    for label, path in paths:
        result = {
            "track": label,
            "path": str(path),
            "status": "passed",
            "error": None,
            "crossingOverlapValidated": False,
        }
        try:
            if path.stat().st_size == 0:
                raise AcValidationError("file is empty")
            mesh_parser = AcParser(path, args.minimum_area)
            metrics = mesh_parser.parse()
            result.update(metrics)
            for key in totals:
                totals[key] += metrics[key]
            crossing_path = find_crossing_geometry_path(path)
            if crossing_path is not None:
                result["crossingPath"] = str(crossing_path)
                crossing_parser = AcParser(
                    crossing_path, args.minimum_area, validate_surface_geometry=False
                )
                crossing_parser.parse()
                result["crossingOverlapValidated"] = True
                result.update(validate_crossing_terrain_overlap(
                    mesh_parser, crossing_parser, args.maximum_crossing_overlap
                ))
        except (AcValidationError, OSError) as error:
            result["status"] = "failed"
            result["error"] = str(error)
        results.append(result)
        print(f"{result['status'].upper():6s} {label} {result['error'] or ''}".rstrip())

    report = {
        "testRoot": str(test_root),
        "minimumArea": args.minimum_area,
        "maximumCrossingOverlap": args.maximum_crossing_overlap,
        "summary": {
            "passed": sum(result["status"] == "passed" for result in results),
            "failed": sum(result["status"] != "passed" for result in results),
        },
        "totals": totals,
        "results": results,
    }
    if args.report:
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"SUMMARY passed={report['summary']['passed']} failed={report['summary']['failed']} "
        f"objects={totals['objects']} vertices={totals['vertices']} surfaces={totals['surfaces']}"
    )
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
