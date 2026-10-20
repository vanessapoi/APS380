# /***************************************************************************
#
#     file                 : svg_geometry.py
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

"""SVG geometry extraction helpers for closed TORCS layout sources."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element  # nosec B405

Point = tuple[float, float]
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
NUMBER_PATTERN = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
TOKEN_RE = re.compile(rf"[A-Za-z]|{NUMBER_PATTERN}")
TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
NUMBER_RE = re.compile(NUMBER_PATTERN)
SEPARATOR_RE = re.compile(r"^[\s,]*$")
NON_RENDERED_CONTAINERS = {"clipPath", "defs", "mask", "symbol"}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
MAX_CURVE_POINTS = 4096
MAX_PATH_TOKENS = 2_000_000
MAX_GEOMETRY_POINTS = 1_000_000
MAX_CANDIDATES = 100_000
MAX_ELEMENT_VISITS = 200_000
MAX_TREE_DEPTH = 512


@dataclass(frozen=True)
class SvgSubpath:
    points: tuple[Point, ...]
    closed: bool


@dataclass(frozen=True)
class SvgCandidate:
    points: tuple[Point, ...]
    closed: bool
    tag: str
    element_id: str
    element_class: str
    element_index: int
    subpath_index: int

    @property
    def length(self) -> float:
        if len(self.points) < 2:
            return 0.0
        total = sum(distance(a, b) for a, b in zip(self.points, self.points[1:], strict=False))
        if self.closed:
            total += distance(self.points[-1], self.points[0])
        return total


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def matrix_multiply(left: Matrix, right: Matrix) -> Matrix:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def apply_matrix(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return a * x + c * y + e, b * x + d * y + f


def transform_matrix(name: str, values: list[float]) -> Matrix:  # noqa: CCR001 - SVG transform grammar dispatch
    lowered = name.lower()
    if lowered == "matrix" and len(values) == 6:
        return tuple(values)  # type: ignore[return-value]
    if lowered == "translate" and len(values) in (1, 2):
        return 1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) == 2 else 0.0
    if lowered == "scale" and len(values) in (1, 2):
        return values[0], 0.0, 0.0, values[-1], 0.0, 0.0
    if lowered == "rotate" and len(values) in (1, 3):
        angle = math.radians(values[0])
        rotation = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0.0, 0.0)
        if len(values) == 1:
            return rotation
        cx, cy = values[1], values[2]
        return matrix_multiply(
            matrix_multiply((1.0, 0.0, 0.0, 1.0, cx, cy), rotation),
            (1.0, 0.0, 0.0, 1.0, -cx, -cy),
        )
    if lowered == "skewx" and len(values) == 1:
        return 1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0
    if lowered == "skewy" and len(values) == 1:
        return 1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0
    raise ValueError(f"Unsupported or malformed SVG transform: {name}({', '.join(str(value) for value in values)})")


def parse_transform(value: str) -> Matrix:
    if not value.strip():
        return IDENTITY
    matrix = IDENTITY
    end = 0
    for match in TRANSFORM_RE.finditer(value):
        if value[end : match.start()].strip(" ,\t\r\n"):
            raise ValueError(f"Malformed SVG transform list: {value}")
        values = parse_number_list(match.group(2), "SVG transform")
        matrix = matrix_multiply(matrix, transform_matrix(match.group(1), values))
        end = match.end()
    if end == 0 or value[end:].strip(" ,\t\r\n"):
        raise ValueError(f"Malformed SVG transform list: {value}")
    return matrix


def scan_tokens(value: str, pattern: re.Pattern[str], context: str) -> list[str]:
    tokens = []
    end = 0
    for match in pattern.finditer(value):
        if not SEPARATOR_RE.match(value[end : match.start()]):
            raise ValueError(f"Malformed {context} near '{value[end:match.start() + 12]}'")
        tokens.append(match.group(0))
        if len(tokens) > MAX_PATH_TOKENS:
            raise ValueError(f"{context} exceeds the {MAX_PATH_TOKENS}-token limit")
        end = match.end()
    if not SEPARATOR_RE.match(value[end:]):
        raise ValueError(f"Malformed {context} near '{value[end:]}'")
    return tokens


def parse_number_list(value: str, context: str) -> list[float]:
    return [float(token) for token in scan_tokens(value, NUMBER_RE, context)]


def point_line_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return distance(point, start)
    amount = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    projected = (start[0] + amount * dx, start[1] + amount * dy)
    return distance(point, projected)


def flatten_cubic(start: Point, control1: Point, control2: Point, end: Point, tolerance: float, depth: int = 0) -> list[Point]:
    deviation = max(point_line_distance(control1, start, end), point_line_distance(control2, start, end))
    excess_length = distance(start, control1) + distance(control1, control2) + distance(control2, end) - distance(start, end)
    if deviation <= tolerance and excess_length <= tolerance:
        return [end]
    if depth >= 16:
        raise ValueError("SVG cubic curve exceeds flattening depth limit")
    p01 = midpoint(start, control1)
    p12 = midpoint(control1, control2)
    p23 = midpoint(control2, end)
    p012 = midpoint(p01, p12)
    p123 = midpoint(p12, p23)
    center = midpoint(p012, p123)
    return flatten_cubic(start, p01, p012, center, tolerance, depth + 1) + flatten_cubic(center, p123, p23, end, tolerance, depth + 1)


def flatten_quadratic(start: Point, control: Point, end: Point, tolerance: float, depth: int = 0) -> list[Point]:
    deviation = point_line_distance(control, start, end)
    excess_length = distance(start, control) + distance(control, end) - distance(start, end)
    if deviation <= tolerance and excess_length <= tolerance:
        return [end]
    if depth >= 16:
        raise ValueError("SVG quadratic curve exceeds flattening depth limit")
    p01 = midpoint(start, control)
    p12 = midpoint(control, end)
    center = midpoint(p01, p12)
    return flatten_quadratic(start, p01, center, tolerance, depth + 1) + flatten_quadratic(center, p12, end, tolerance, depth + 1)


def midpoint(a: Point, b: Point) -> Point:
    return (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5


def completed_subpath(points: list[Point], closed: bool) -> list[SvgSubpath]:
    if not points:
        return []
    endpoint_closed = len(points) > 2 and distance(points[0], points[-1]) <= 1e-9
    cleaned = points[:-1] if endpoint_closed else points
    return [SvgSubpath(tuple(cleaned), closed or endpoint_closed)]


def enforce_point_limit(point_count: int, point_limit: int) -> None:
    if point_count > point_limit:
        raise ValueError(f"SVG path exceeds the {point_limit}-point remaining geometry limit")


def vector_angle(ux: float, uy: float, vx: float, vy: float) -> float:
    dot = ux * vx + uy * vy
    determinant = ux * vy - uy * vx
    return math.atan2(determinant, dot)


def flatten_arc(start: Point, rx: float, ry: float, rotation_deg: float, large_arc: bool, sweep: bool, end: Point, tolerance: float) -> list[Point]:
    if distance(start, end) <= 1e-12:
        return []
    rx = abs(rx)
    ry = abs(ry)
    if rx <= 1e-12 or ry <= 1e-12:
        return [end]
    rotation = math.radians(rotation_deg % 360.0)
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    dx = (start[0] - end[0]) * 0.5
    dy = (start[1] - end[1]) * 0.5
    x1 = cosine * dx + sine * dy
    y1 = -sine * dx + cosine * dy
    radii = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if radii > 1.0:
        factor = math.sqrt(radii)
        rx *= factor
        ry *= factor
    numerator = max(0.0, rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1)
    denominator = max(1e-30, rx * rx * y1 * y1 + ry * ry * x1 * x1)
    coefficient = (-1.0 if large_arc == sweep else 1.0) * math.sqrt(numerator / denominator)
    cx1 = coefficient * rx * y1 / ry
    cy1 = coefficient * -ry * x1 / rx
    center = (
        cosine * cx1 - sine * cy1 + (start[0] + end[0]) * 0.5,
        sine * cx1 + cosine * cy1 + (start[1] + end[1]) * 0.5,
    )
    ux = (x1 - cx1) / rx
    uy = (y1 - cy1) / ry
    vx = (-x1 - cx1) / rx
    vy = (-y1 - cy1) / ry
    start_angle = vector_angle(1.0, 0.0, ux, uy)
    delta = vector_angle(ux, uy, vx, vy)
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi
    radius = max(rx, ry)
    if tolerance >= radius:
        maximum_angle = math.pi / 4.0
    else:
        maximum_angle = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tolerance / radius)))
    count = max(1, math.ceil(abs(delta) / max(maximum_angle, 1e-12)))
    if count > MAX_CURVE_POINTS:
        raise ValueError(f"SVG arc needs {count} points at the requested tolerance; limit is {MAX_CURVE_POINTS}")
    points = []
    for index in range(1, count + 1):
        angle = start_angle + delta * index / count
        x = rx * math.cos(angle)
        y = ry * math.sin(angle)
        points.append((cosine * x - sine * y + center[0], sine * x + cosine * y + center[1]))
    points[-1] = end
    return points


def parse_path(  # noqa: CCR001 - SVG path grammar dispatch
    data: str, tolerance: float, point_limit: int = MAX_GEOMETRY_POINTS
) -> list[SvgSubpath]:
    tokens = scan_tokens(data, TOKEN_RE, "SVG path")
    index = 0
    command = ""
    current: Point = (0.0, 0.0)
    start: Point | None = None
    points: list[Point] = []
    subpaths: list[SvgSubpath] = []
    cubic_control: Point | None = None
    quadratic_control: Point | None = None
    completed_point_count = 0

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise ValueError(f"Malformed SVG path near command {command}")
        value = float(tokens[index])
        index += 1
        return value

    def flag() -> bool:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise ValueError(f"Malformed SVG arc near command {command}")
        token = tokens[index]
        if token in ("0", "1"):
            index += 1
            return token == "1"  # nosec B105
        if token[0] in "01" and token.isdigit():
            tokens[index] = token[1:]
            return token[0] == "1"
        raise ValueError(f"SVG arc flag must be 0 or 1, got '{token}'")

    def pair(relative: bool) -> Point:
        x, y = number(), number()
        return (current[0] + x, current[1] + y) if relative else (x, y)

    def finish(closed: bool) -> None:
        nonlocal points, completed_point_count
        finished = completed_subpath(points, closed)
        completed_point_count += sum(len(subpath.points) for subpath in finished)
        enforce_point_limit(completed_point_count, point_limit)
        subpaths.extend(finished)
        points = []

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if not command:
            raise ValueError("SVG path starts without a command")
        relative = command.islower()
        operation = command.upper()
        previous = current
        if operation == "M":
            finish(False)
            current = pair(relative)
            start = current
            points = [current]
            command = "l" if relative else "L"
            cubic_control = quadratic_control = None
        elif operation == "L":
            current = pair(relative)
            points.append(current)
            cubic_control = quadratic_control = None
        elif operation == "H":
            value = number()
            current = (current[0] + value if relative else value, current[1])
            points.append(current)
            cubic_control = quadratic_control = None
        elif operation == "V":
            value = number()
            current = (current[0], current[1] + value if relative else value)
            points.append(current)
            cubic_control = quadratic_control = None
        elif operation == "C":
            control1 = pair(relative)
            control2 = pair(relative)
            current = pair(relative)
            points.extend(flatten_cubic(previous, control1, control2, current, tolerance))
            cubic_control = control2
            quadratic_control = None
        elif operation == "S":
            control1 = (2.0 * previous[0] - cubic_control[0], 2.0 * previous[1] - cubic_control[1]) if cubic_control is not None else previous
            control2 = pair(relative)
            current = pair(relative)
            points.extend(flatten_cubic(previous, control1, control2, current, tolerance))
            cubic_control = control2
            quadratic_control = None
        elif operation == "Q":
            control = pair(relative)
            current = pair(relative)
            points.extend(flatten_quadratic(previous, control, current, tolerance))
            quadratic_control = control
            cubic_control = None
        elif operation == "T":
            control = (2.0 * previous[0] - quadratic_control[0], 2.0 * previous[1] - quadratic_control[1]) if quadratic_control is not None else previous
            current = pair(relative)
            points.extend(flatten_quadratic(previous, control, current, tolerance))
            quadratic_control = control
            cubic_control = None
        elif operation == "A":
            rx, ry, rotation = number(), number(), number()
            large_arc = flag()
            sweep = flag()
            current = pair(relative)
            points.extend(flatten_arc(previous, rx, ry, rotation, large_arc, sweep, current, tolerance))
            cubic_control = quadratic_control = None
        elif operation == "Z":
            if start is None:
                raise ValueError("SVG path closes before a move command")
            current = start
            finish(True)
            start = None
            command = ""
            cubic_control = quadratic_control = None
        else:
            raise ValueError(f"Unsupported SVG path command: {command}")
        enforce_point_limit(completed_point_count + len(points), point_limit)
    finish(False)
    return subpaths


def parse_points(value: str) -> list[Point]:
    values = parse_number_list(value, "SVG points attribute")
    if len(values) < 4 or len(values) % 2:
        raise ValueError("SVG polyline/polygon has an invalid points attribute")
    return list(zip(values[::2], values[1::2], strict=True))


def parse_length(value: str, default: float = 0.0, percentage_base: float | None = None) -> float:
    if not value:
        return default
    percentage = re.fullmatch(rf"\s*({NUMBER_PATTERN})%\s*", value)
    if percentage is not None:
        if percentage_base is None:
            raise ValueError(f"SVG percentage length requires a known parent viewport: {value}")
        return percentage_base * float(percentage.group(1)) / 100.0
    match = re.fullmatch(rf"\s*({NUMBER_PATTERN})(px|in|cm|mm|q|pt|pc)?\s*", value, re.IGNORECASE)
    if match is None:
        raise ValueError(f"Unsupported SVG viewport length: {value}")
    unit_scale = {
        None: 1.0,
        "px": 1.0,
        "in": 96.0,
        "cm": 96.0 / 2.54,
        "mm": 96.0 / 25.4,
        "q": 96.0 / 101.6,
        "pt": 96.0 / 72.0,
        "pc": 16.0,
    }
    return float(match.group(1)) * unit_scale[match.group(2).lower() if match.group(2) else None]


def viewbox_matrix(view_box: list[float], width: float, height: float, preserve: str, x: float = 0.0, y: float = 0.0) -> Matrix:
    if len(view_box) != 4 or view_box[2] <= 0.0 or view_box[3] <= 0.0:
        raise ValueError("SVG viewBox must contain min-x, min-y, positive width, and positive height")
    min_x, min_y, box_width, box_height = view_box
    scale_x = width / box_width
    scale_y = height / box_height
    if preserve == "none":
        return scale_x, 0.0, 0.0, scale_y, x - min_x * scale_x, y - min_y * scale_y
    parts = preserve.split()
    align = parts[0] if parts else "xMidYMid"
    mode = parts[1] if len(parts) > 1 else "meet"
    if align not in {f"x{x}Y{y}" for x in ("Min", "Mid", "Max") for y in ("Min", "Mid", "Max")} or mode not in ("meet", "slice"):
        raise ValueError(f"Unsupported preserveAspectRatio: {preserve}")
    scale = min(scale_x, scale_y) if mode == "meet" else max(scale_x, scale_y)
    extra_x = width - box_width * scale
    extra_y = height - box_height * scale
    x_factor = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}[align[1:4]]
    y_factor = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}[align[5:8]]
    return scale, 0.0, 0.0, scale, x + extra_x * x_factor - min_x * scale, y + extra_y * y_factor - min_y * scale


def viewport_matrix(element: Element, root: bool) -> Matrix:
    if local_name(element.tag) != "svg":
        return IDENTITY
    x = 0.0 if root else parse_length(element.get("x", ""), 0.0)
    y = 0.0 if root else parse_length(element.get("y", ""), 0.0)
    view_box = parse_number_list(element.get("viewBox", ""), "SVG viewBox") if element.get("viewBox") else []
    if not view_box:
        return 1.0, 0.0, 0.0, 1.0, x, y
    if len(view_box) != 4:
        raise ValueError("SVG viewBox must contain four numbers")
    box_width, box_height = view_box[2], view_box[3]
    width = parse_length(element.get("width", ""), box_width, box_width if root else None)
    height = parse_length(element.get("height", ""), box_height, box_height if root else None)
    return viewbox_matrix(view_box, width, height, element.get("preserveAspectRatio", "xMidYMid meet").strip(), x, y)


def symbol_use_matrix(symbol: Element, use: Element) -> Matrix:
    view_box = parse_number_list(symbol.get("viewBox", ""), "SVG symbol viewBox") if symbol.get("viewBox") else []
    if not view_box:
        return IDENTITY
    if len(view_box) != 4:
        raise ValueError("SVG symbol viewBox must contain four numbers")
    box_width, box_height = view_box[2], view_box[3]
    width = parse_length(use.get("width", ""), box_width)
    height = parse_length(use.get("height", ""), box_height)
    preserve = use.get("preserveAspectRatio", symbol.get("preserveAspectRatio", "xMidYMid meet")).strip()
    return viewbox_matrix(view_box, width, height, preserve)


def maximum_scale(matrix: Matrix) -> float:
    a, b, c, d, _e, _f = matrix
    trace = a * a + b * b + c * c + d * d
    determinant = (a * d - b * c) ** 2
    return math.sqrt(max(0.0, 0.5 * (trace + math.sqrt(max(0.0, trace * trace - 4.0 * determinant)))))


def hidden_classes(root: Element) -> set[str]:
    hidden = set()
    for element in root.iter():
        if local_name(element.tag) != "style" or not element.text:
            continue
        for selector, body in re.findall(r"\.([\w-]+)\s*\{([^}]+)\}", element.text):
            if re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:;|$)", body, re.IGNORECASE):
                hidden.add(selector)
    return hidden


def element_hidden(element: Element, css_hidden: set[str]) -> bool:
    style = element.get("style", "")
    if element.get("display", "").strip().lower() == "none" or element.get("visibility", "").strip().lower() == "hidden":
        return True
    if re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:;|$)", style, re.IGNORECASE):
        return True
    return any(name in css_hidden for name in element.get("class", "").split())


def find_scope(root: Element, element_id: str) -> tuple[Element, Matrix]:
    visited = 0

    def visit(element: Element, parent_matrix: Matrix, depth: int = 0) -> tuple[Element, Matrix] | None:
        nonlocal visited
        visited += 1
        if depth > MAX_TREE_DEPTH or visited > MAX_ELEMENT_VISITS:
            raise ValueError("SVG tree exceeds the traversal limit")
        if element.get("id") == element_id:
            return element, parent_matrix
        local = matrix_multiply(parse_transform(element.get("transform", "")), viewport_matrix(element, element is root))
        matrix = matrix_multiply(parent_matrix, local)
        for child in element:
            found = visit(child, matrix, depth + 1)
            if found is not None:
                return found
        return None

    result = visit(root, IDENTITY)
    if result is None:
        raise SystemExit(f"SVG element/group id not found: {element_id}")
    return result


def extract_candidates(root: Element, scope_id: str = "", tolerance: float = 0.5) -> list[SvgCandidate]:  # noqa: CCR001 - recursive SVG tree traversal
    scope, parent_matrix = find_scope(root, scope_id) if scope_id else (root, IDENTITY)
    candidates: list[SvgCandidate] = []
    element_index = 0
    ids = {element.get("id", ""): element for element in root.iter() if element.get("id")}
    css_hidden = hidden_classes(root)
    geometry_point_count = 0
    element_visit_count = 0

    def visit(  # noqa: CCR001 - recursive SVG tree traversal
        element: Element,
        inherited: Matrix,
        active_uses: frozenset[str] = frozenset(),
        explicit: bool = False,
        depth: int = 0,
    ) -> None:
        nonlocal element_index, geometry_point_count, element_visit_count
        element_visit_count += 1
        if depth > MAX_TREE_DEPTH or element_visit_count > MAX_ELEMENT_VISITS:
            raise ValueError("SVG tree or use expansion exceeds the traversal limit")
        tag = local_name(element.tag)
        if not explicit and element_hidden(element, css_hidden):
            return
        if tag in NON_RENDERED_CONTAINERS and not explicit:
            return
        local = matrix_multiply(parse_transform(element.get("transform", "")), viewport_matrix(element, element is root))
        matrix = matrix_multiply(inherited, local)
        if tag == "use":
            reference = element.get("href", element.get(XLINK_HREF, ""))
            if not reference.startswith("#") or reference[1:] not in ids:
                raise ValueError(f"SVG use has an unresolved local reference: {reference}")
            reference_id = reference[1:]
            if reference_id in active_uses:
                raise ValueError(f"Cyclic SVG use reference: {reference}")
            translation = (1.0, 0.0, 0.0, 1.0, parse_length(element.get("x", ""), 0.0), parse_length(element.get("y", ""), 0.0))
            instance = symbol_use_matrix(ids[reference_id], element) if local_name(ids[reference_id].tag) == "symbol" else IDENTITY
            visit(
                ids[reference_id],
                matrix_multiply(matrix_multiply(matrix, translation), instance),
                active_uses | {reference_id},
                True,
                depth + 1,
            )
            return
        subpaths: list[SvgSubpath] = []
        if tag == "path" and element.get("d"):
            scale = maximum_scale(matrix)
            if scale <= 1e-12:
                raise ValueError("SVG geometry transform collapses the selected element")
            subpaths = parse_path(element.get("d", ""), tolerance / scale, MAX_GEOMETRY_POINTS - geometry_point_count)
        elif tag in ("polyline", "polygon") and element.get("points"):
            points = parse_points(element.get("points", ""))
            closed = tag == "polygon" or distance(points[0], points[-1]) <= 1e-9
            if closed and distance(points[0], points[-1]) <= 1e-9:
                points = points[:-1]
            subpaths = [SvgSubpath(tuple(points), closed)]
        if subpaths:
            current_index = element_index
            element_index += 1
            for subpath_index, subpath in enumerate(subpaths):
                if geometry_point_count + len(subpath.points) > MAX_GEOMETRY_POINTS:
                    raise ValueError(f"SVG extraction exceeds the {MAX_GEOMETRY_POINTS}-point geometry limit")
                transformed = tuple(apply_matrix(matrix, point) for point in subpath.points)
                if len(transformed) >= 2:
                    geometry_point_count += len(transformed)
                    if len(candidates) >= MAX_CANDIDATES:
                        raise ValueError(f"SVG extraction exceeds the {MAX_CANDIDATES}-candidate limit")
                    candidates.append(
                        SvgCandidate(
                            points=transformed,
                            closed=subpath.closed,
                            tag=tag,
                            element_id=element.get("id", ""),
                            element_class=element.get("class", ""),
                            element_index=current_index,
                            subpath_index=subpath_index,
                        )
                    )
        for child in element:
            visit(child, matrix, active_uses, depth=depth + 1)

    visit(scope, parent_matrix, explicit=True)
    return candidates
