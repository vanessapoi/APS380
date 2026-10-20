#!/usr/bin/env python3

##############################################################################
#
#    file                 : validate_crossing_seams.py
#    created              : Tue Sep 15 2026
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

"""Check crossing-part perimeters against the exported track and terrain edges.

Unlike triangle-count checks, this detects missing portal faces and cracks at
their terrain seams. Edge coverage is measured in 3D and accepts subdivisions
on either side. Inputs are explicit *-trk.ac paths; no track data is modified.
"""

import argparse
from collections import defaultdict
import json
import math
import pathlib

from validate_ac import AcParser, AcValidationError, CROSSING_OBJECT_PREFIXES


def edge_interval(first, second, start, end, tolerance):
    """Return the interval covered by a collinear edge on AB, or None."""
    direction = tuple(b - a for a, b in zip(first, second))
    length_squared = sum(value * value for value in direction)
    if length_squared <= tolerance * tolerance:
        return None
    parameters = []
    for point in (start, end):
        offset = tuple(p - a for p, a in zip(point, first))
        parameter = sum(a * b for a, b in zip(offset, direction)) / length_squared
        distance_squared = sum((a - parameter * b) ** 2
                               for a, b in zip(offset, direction))
        if distance_squared > tolerance * tolerance:
            return None
        parameters.append(parameter)
    low, high = max(0.0, min(parameters)), min(1.0, max(parameters))
    return (low, high) if high > low else None


def uncovered_fraction(intervals):
    """Measure the union's complement in [0, 1], retaining internal gaps."""
    covered_end = 0.0
    missing = 0.0
    for low, high in sorted(intervals):
        missing += max(0.0, low - covered_end)
        covered_end = max(covered_end, high)
    return missing + max(0.0, 1.0 - covered_end)


def edge_cells(first, second, tolerance, cell_size=20.0):
    """Index AC's horizontal X/Z plane; heights are checked by edge_interval."""
    for x in range(math.floor((min(first[0], second[0]) - tolerance) / cell_size),
                   math.floor((max(first[0], second[0]) + tolerance) / cell_size) + 1):
        for z in range(math.floor((min(first[2], second[2]) - tolerance) / cell_size),
                       math.floor((max(first[2], second[2]) + tolerance) / cell_size) + 1):
            yield x, z


def validate_crossing_seams(track_path, tolerance=1e-4):
    """Check underside, fascia, socket, filler and floor boundaries in 3D."""
    mesh_path = track_path.with_name(track_path.name[:-len('-trk.ac')] + '-msh.ac')
    track = AcParser(track_path, 1e-10, validate_surface_geometry=False)
    terrain = AcParser(mesh_path, 1e-10)
    track.parse()
    terrain.parse()
    edges = []
    grid = defaultdict(list)
    part_edges = defaultdict(list)
    socket_names = set()
    part_names = set()
    part_triangles = set()
    for source, parser in enumerate((track, terrain)):
        for object_index, name, triangle, transformed in parser.triangles:
            if transformed:
                raise AcValidationError('seam validation requires flattened objects')
            a, b, c = triangle
            ab = tuple(y - x for x, y in zip(a, b))
            ac = tuple(y - x for x, y in zip(a, c))
            normal = (ab[1] * ac[2] - ab[2] * ac[1],
                      ab[2] * ac[0] - ab[0] * ac[2],
                      ab[0] * ac[1] - ab[1] * ac[0])
            collapsed = sum(value * value for value in normal) <= 1e-20
            if name.startswith('TRKSOCKET'):
                socket_names.add((source, object_index))
            crossing_part = name.startswith(CROSSING_OBJECT_PREFIXES)
            if crossing_part:
                part_names.add((source, object_index))
                if collapsed:
                    raise AcValidationError(f'{name}: collapsed crossing triangle')
                key = (source, object_index, tuple(sorted(triangle)))
                if key in part_triangles:
                    raise AcValidationError(f'{name}: duplicate crossing triangle')
                part_triangles.add(key)
            # Degenerate road-strip triangles cannot provide visible closure.
            if collapsed:
                continue
            for index in range(3):
                first, second = triangle[index], triangle[(index + 1) % 3]
                if first == second:
                    continue
                edge_index = len(edges)
                edges.append((first, second, name))
                for cell in edge_cells(first, second, tolerance):
                    grid[cell].append(edge_index)
                if crossing_part:
                    key = (source, object_index, tuple(sorted((first, second))))
                    part_edges[key].append(edge_index)
    if not part_names:
        raise AcValidationError('no crossing triangles found')
    failures = []
    boundary_count = 0
    for indices in part_edges.values():
        if len(indices) > 2:
            raise AcValidationError('non-manifold crossing-part edge')
        if len(indices) == 2:
            continue
        boundary_count += 1
        edge_index = indices[0]
        first, second, name = edges[edge_index]
        candidates = set()
        for cell in edge_cells(first, second, tolerance):
            candidates.update(grid[cell])
        intervals = []
        for candidate in candidates:
            if candidate == edge_index:
                continue
            start, end, unused_name = edges[candidate]
            interval = edge_interval(first, second, start, end, tolerance)
            if interval is not None:
                intervals.append(interval)
        missing_length = uncovered_fraction(intervals) * math.dist(first, second)
        if missing_length > tolerance:
            failures.append({'object': name, 'edge': (first, second),
                             'uncoveredMetres': missing_length})
    return {'track': str(track_path), 'sockets': len(socket_names),
            'crossingObjects': len(part_names),
            'boundaryEdges': boundary_count, 'openEdges': failures,
            'passed': not failures, 'toleranceMetres': tolerance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tracks', nargs='+', type=pathlib.Path, metavar='TRACK-trk.ac')
    parser.add_argument('--report', type=pathlib.Path)
    args = parser.parse_args()
    results = []
    for path in args.tracks:
        try:
            if not path.name.endswith('-trk.ac'):
                raise AcValidationError('input must be a *-trk.ac file')
            result = validate_crossing_seams(path)
        except (OSError, AcValidationError) as error:
            result = {'track': str(path), 'passed': False, 'error': str(error)}
        results.append(result)
        print(json.dumps(result))
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
