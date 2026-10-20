# /***************************************************************************
#     file                 : radius_repair.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Local, loaded-pose fitting preserved from the Mogyorod radius-repair pilot.

Supports explicit spline curves, proven zero-height defaults, and bounded local
overrides with validated pit entry/exit references. Candidate generation never deploys.
"""

import math
from html import escape
from xml.parsers import expat

import numpy as np
from defusedxml import ElementTree as ET

from torcs_track_tools.core.defaults import (
    DEFAULT_RADIUS_FIT_SEED,
    DEFAULT_REPAIR_CURVE_RADIUS_M,
    DEFAULT_TARGET_ANG_DEG,
    DEFAULT_TARGET_DX_M,
    DEFAULT_TARGET_DY_M,
    DEFAULT_TARGET_DZ_M,
    RADIUS_LOCAL_CENTER_TOLERANCE_M,
    RADIUS_LOCAL_EDGE_TOLERANCE_M,
    RADIUS_LOCAL_HEIGHT_TOLERANCE_M,
    RADIUS_PROFILE_SAMPLE_COUNT,
    RADIUS_UNTOUCHED_TOLERANCE_M,
)
from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.radius_pits import (
    configure_pit_markers,
    constrain_pit_bounds,
    pit_labels,
    pit_references,
    remap_exit_reference,
    split_pit_geometry,
    validate_pit_markers,
)
from torcs_track_tools.core.radius_profiles import (
    BANK_FIELDS,
    EDGE_TANGENTS,
    is_implicit_flat_track,
    materialize_flat_profile,
    normalize_profile_values,
    profile_fields,
    tangent_attributes,
    validate_banking,
)
from torcs_track_tools.core.radius_sampling import configure_sampling, distributed_labels, scs_geometry
from torcs_track_tools.core.radius_sides import side_states, split_side, validate_side_split
from torcs_track_tools.core.track_xml import child_section

SUFFIX = ":radius-out"
TURN_SUFFIX = ":radius-turn"
IN_SUFFIX = ":radius-in"
# Keep a 2.5% radius reserve when initializing the quantized two-arc fit.
FIT_RADIUS_RESERVE = 0.975
FIT_DIAMETER_M = 2 * MAX_TORCS_RADIUS_M * FIT_RADIUS_RESERVE
PADDED_ARC_FRACTION = 1 / 8
MAX_LOCAL_TURN_RAD = 0.15
# Finite differences and optimizer scales for (length m, peak rad, turn rad).
# Steps must clear the loader's float quantization to produce useful gradients.
TWO_ARC_JACOBIAN_STEPS = (.01, .0004, .000004)
TWO_ARC_PARAMETER_SCALES = (14, .02, .00002)
RESUME_ENDPOINT_TOLERANCE_M = .00075
RESUME_WEIGHTED_HEADING_TOLERANCE = .0001  # radians multiplied by heading_weight, not closure degrees
FIELDS = {"type", "radius", "arc", "z start", "z end", "profil start tangent", "profil end tangent", "profil"}
STRAIGHT_FIELDS = (FIELDS - {"radius", "arc"}) | {"lg"}
NUMERIC_UNITS = {"radius": "m", "arc": "deg", "lg": "m", "z start": "m", "z end": "m",
                 "profil start tangent": "%", "profil end tangent": "%"}
NUMERIC_UNITS.update(dict.fromkeys(BANK_FIELDS, "deg"))
NUMERIC_UNITS.update(dict.fromkeys(EDGE_TANGENTS, "%"))


def reject_internal_entity(name, is_parameter, value, *_):
    if is_parameter or value is not None:
        raise ValueError(f"Internal/parameter entities are unsupported: {name}")


def section_blocks(text, depth, parents):
    """Byte spans preserve prolog, entities, comments, indentation and CRLF."""
    data = text.encode("utf-8")
    parser = expat.ParserCreate()
    stack, spans, starts = [], {}, {}

    def start(tag, attrs):
        stack.append(attrs.get("name", tag))
        if len(stack) == depth and stack[1:-1] == parents and tag == "section":
            name = stack[-1]
            if name in starts:
                raise ValueError(f"Duplicate section name: {name}")
            starts[name] = parser.CurrentByteIndex

    def end(tag):
        if len(stack) == depth and stack[1:-1] == parents and tag == "section":
            stop = data.index(b">", parser.CurrentByteIndex) + 1
            spans[stack[-1]] = (starts[stack[-1]], stop)
        stack.pop()

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.EntityDeclHandler = reject_internal_entity
    parser.ExternalEntityRefHandler = lambda *_: 1  # no external file reads needed for spans
    parser.Parse(data, True)
    return {name: data[a:b].decode("utf-8") for name, (a, b) in spans.items()}


def segment_blocks(text):
    return section_blocks(text, 4, ["Main Track", "Track Segments"])


def border_blocks(block):
    return section_blocks(block, 2, [])


def repair_tree(text):
    # External surface declarations belong to the native loader. Only the
    # parameter tree is needed here; internal references remain undefined.
    root = ET.fromstring(text[text.index("<params"):].replace("&default-surfaces;", ""))
    main = child_section(root, "Main Track")
    segments = child_section(main, "Track Segments")
    if segments is None:
        raise ValueError("Repair requires version-4 Track Segments")
    header = child_section(root, "Header")
    if header is None:
        raise ValueError("Missing track Header")
    version = header.find("attnum[@name='version']")
    if version is None or float(version.get("val", "nan")) != 4:
        raise ValueError("Repair supports explicit version 4 only")
    return root, segments


def planar_border_values(border):
    name = border.get("name")
    if name not in ("Left Border", "Right Border"):
        raise ValueError(f"{name}: only constant planar border resets are supported")
    attributes = {a.get("name"): a for a in border}
    if not {"width", "style", "surface"} <= attributes.keys() <= {"width", "style", "surface", "height"}:
        raise ValueError(f"{name}: explicit constant width, plan style and surface are required")
    style = attributes["style"].get("val")
    if len(attributes) != len(border) or style not in ("plan", "curb"):
        raise ValueError(f"{name}: duplicate attributes and walls require manual handling")
    if style == "curb" and "height" not in attributes:
        raise ValueError(f"{name}: curbs without explicit height require manual handling")
    validate_border_attributes(attributes, name)
    return attributes


def side_values(side):
    name = side.get("name")
    attributes = {a.get("name"): a for a in side}
    if name not in ("Left Side", "Right Side") or len(attributes) != len(side):
        raise ValueError(f"{name}: unsupported side override")
    if not attributes.keys() <= {"width", "start width", "end width", "surface", "banking type"}:
        raise ValueError(f"{name}: unsupported side attributes")
    validate_side_attributes(attributes, name)
    return attributes


def validate_side_attributes(attributes, name):
    strings = {key: att for key, att in attributes.items() if key in ("surface", "banking type")}
    if any(att.tag != "attstr" or not att.get("val") for att in strings.values()):
        raise ValueError(f"{name}: invalid side surface/banking type")
    if "banking type" in strings and strings["banking type"].get("val") not in ("level", "tangent"):
        raise ValueError(f"{name}: unsupported banking type")
    validate_border_attributes({key: att for key, att in attributes.items() if key not in strings}, name)


def validate_local_override(section):
    if section.get("name") in ("Left Side", "Right Side"):
        return side_values(section)
    return planar_border_values(section)


def validate_border_attributes(attributes, name):
    for key, att in attributes.items():
        if key in ("style", "surface"):
            if att.tag != "attstr" or not att.get("val"):
                raise ValueError(f"{name}: invalid {key}")
            continue
        value = float(att.get("val", "nan"))
        if att.tag != "attnum" or att.get("unit", "m") != "m" or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name}: finite, nonnegative metre values are required")


def section_values(section, name, allow_straight=False, allow_edge_tangents=False):
    for border in section.findall("section"):
        validate_local_override(border)
    attributes = [a for a in section if a.tag != "section"]
    fields = STRAIGHT_FIELDS if allow_straight and section.find("attstr[@name='type'][@val='str']") is not None else FIELDS
    fields = profile_fields(fields, {a.get("name") for a in attributes}, allow_edge_tangents)
    if allow_edge_tangents and any(a.get("name") == "profil steps" for a in attributes):
        fields = fields | {"profil steps"}
    if any(a.tag not in ("attstr", "attnum") or a.get("name") not in fields for a in attributes):
        raise ValueError(f"{name}: local overrides/extra fields require a manual repair")
    values = {a.get("name"): a.get("val") for a in attributes}
    if set(values) != fields or len(attributes) != len(fields):
        raise ValueError(f"{name}: explicit spline heights, tangents and constant radius are required")
    types = ("str", "lft", "rgt") if allow_straight else ("lft", "rgt")
    if values["type"] not in types or values["profil"] != "spline":
        raise ValueError(f"{name}: expected a spline-profiled curve")
    validate_numeric_fields(attributes, name)
    return normalize_profile_values(values)


def validate_numeric_fields(section, name):
    for att in section:
        key = att.get("name")
        if key == "profil steps":
            validate_step_count(att)
            continue
        expected = NUMERIC_UNITS.get(key)
        if expected is None:
            if att.tag != "attstr":
                raise ValueError(f"{name}: expected string attribute {key}")
            continue
        if att.tag != "attnum" or att.get("unit") != expected or not math.isfinite(float(att.get("val", "nan"))):
            raise ValueError(f"{name}: finite explicit {expected} units required for {key}")


def validate_step_count(att):
    value = float(att.get("val", "nan"))
    if att.tag != "attnum" or not math.isfinite(value) or not 1 <= value <= 1000000 or value != int(value):
        raise ValueError("Profile step count must be a positive bounded integer")


def selected_sections(text, names, method="biarc", curve_radius=DEFAULT_REPAIR_CURVE_RADIUS_M):
    if method not in ("biarc", "scs", "sbbs", "auto") or not math.isfinite(curve_radius) or not 0 < curve_radius <= MAX_TORCS_RADIUS_M:
        raise ValueError(f"Expected method biarc/scs/sbbs/auto and a curve radius in (0, {MAX_TORCS_RADIUS_M:g}] metres")
    if not names or len(set(names)) != len(names):
        raise ValueError("Select one or more distinct segment names")
    root, segments = repair_tree(text)
    blocks = segment_blocks(text)
    implicit_flat = is_implicit_flat_track(segments)
    elements = profile_elements(segments, implicit_flat)
    width = track_width(root)
    sides = side_states(child_section(root, "Main Track"), segments)
    result = {}
    for name in names:
        if name not in blocks or any(label.startswith(name+":radius-") for label in blocks):
            raise ValueError(f"Missing segment or replacement-name collision: {name}")
        values = section_values(elements[name], name)
        if float(values["radius"]) <= MAX_TORCS_RADIUS_M or float(values["arc"]) <= 0:
            raise ValueError(f"{name}: expected a positive curve with radius above {MAX_TORCS_RADIUS_M:g} m")
        result[name] = {"values": values, "block": blocks[name], "borders": border_blocks(blocks[name]),
                        "method": method, "curve_radius": curve_radius, "width": width,
                        "requested_method": method,
                        "implicit_flat": implicit_flat,
                        "pit_roles": pit_references(root, name),
                        "side_profiles": sides[name],
                        "heading_weight": 1000.0 if method == "auto" else 30.0}
    return result


def profile_elements(segments, implicit_flat):
    return {s.get("name"): materialize_flat_profile(s) if implicit_flat else s for s in segments}


def track_width(root):
    main = child_section(root, "Main Track")
    att = main.find("attnum[@name='width']")
    if att is None:
        return 15.0
    value = float(att.get("val", "nan"))
    if att.get("unit", "m") != "m" or not math.isfinite(value) or value <= 0:
        raise ValueError("Radius repair requires a finite, positive track width in metres")
    return value


def group(model, name):
    return [r for r in model["rows"] if r["name"] == name or r["name"].startswith(name+":radius-")]


def profile(values, length, t):
    z0, z1 = float(values["z start"]), float(values["z end"])
    m0, m1 = float(values["profil start tangent"])/100, float(values["profil end tangent"])/100
    z = (2*t**3-3*t*t+1)*z0 + (t**3-2*t*t+t)*length*m0 + (-2*t**3+3*t*t)*z1 + (t**3-t*t)*length*m1
    slope = ((6*t*t-6*t)*z0 + (3*t*t-4*t+1)*length*m0 + (-6*t*t+6*t)*z1 + (3*t*t-2*t)*length*m1)/length
    return z, slope*100


def replacement_labels(name, method, cells=1):
    if method == "sbbs":
        return [name, name+IN_SUFFIX, name+TURN_SUFFIX, name+SUFFIX]
    if method == "scs":
        if cells > 1:
            return distributed_labels(name, cells)
        return [name, name+TURN_SUFFIX, name+SUFFIX]
    return [name, name+SUFFIX]


def replacement_parts(values, parameters, method, curve_radius, cells=1, native_steps=None):
    if not all(math.isfinite(v) for v in parameters):
        raise ValueError("Nonfinite fitted geometry")
    if method == "scs":
        return scs_geometry(values["type"], parameters, curve_radius, cells, native_steps)
    length, peak, turn = parameters
    if length <= 0 or min(abs(peak), abs(turn-peak)) == 0:
        raise ValueError("Degenerate fitted curve")
    active = length*PADDED_ARC_FRACTION if method == "sbbs" else length
    arcs = [("lft" if a > 0 else "rgt", active/2, active/2/abs(a), abs(a)) for a in (peak, turn-peak)]
    if native_steps is not None:
        count = max(1, math.ceil(native_steps/2))
        arcs = [(*arc, count+i) for i, arc in enumerate(arcs)]
    if method == "sbbs":
        straight = ("str", (length-active)/2, 0, 0)
        return [straight, *arcs, straight]
    return arcs


def geometry_attributes(kind, length, radius, angle, steps=None):
    sampling = f'\n\t\t\t\t<attnum name="profil steps" val="{steps}" />' if steps is not None else ""
    if kind == "str":
        return f'''<attstr name="type" val="str" />
\t\t\t\t<attnum name="lg" unit="m" val="{length:.10f}" />{sampling}'''
    return f'''<attstr name="type" val="{kind}" />
\t\t\t\t<attnum name="radius" unit="m" val="{radius:.10f}" />
\t\t\t\t<attnum name="arc" unit="deg" val="{math.degrees(angle):.12f}" />{sampling}'''


def replacement(name, values, parameters, borders=None, method="biarc", curve_radius=DEFAULT_REPAIR_CURVE_RADIUS_M, width=15.0, sides=None, cells=1, native_steps=None, pit_lengths=None):
    geometry = replacement_parts(values, parameters, method, curve_radius, cells, native_steps)
    geometry = split_pit_geometry(geometry, pit_lengths or {})
    labels = pit_labels(replacement_labels(name, method, cells), pit_lengths or {})
    length = sum(part[1] for part in geometry)
    stations = np.r_[0, np.cumsum([part[1] for part in geometry])]/length
    parts = []
    for i, (label, shape) in enumerate(zip(labels, geometry, strict=True)):
        z0, _ = profile(values, length, float(stations[i]))
        z1, _ = profile(values, length, float(stations[i+1]))
        tangents = tangent_attributes(values, width, length, float(stations[i]), float(stations[i+1]), profile)
        border_text = part_overrides(borders or {}, sides or {}, float(stations[i]), float(stations[i+1]))
        parts.append(f'''<section name="{escape(label, quote=True)}">
\t\t\t\t{geometry_attributes(*shape)}
\t\t\t\t<attnum name="z end" unit="m" val="{z1:.10f}" />{border_text}
\t\t\t\t<attnum name="z start" unit="m" val="{z0:.10f}" />
\t\t\t\t{tangents}
\t\t\t\t<attstr name="profil" val="spline" />
\t\t\t</section>''')
    return "\n\t\t\t".join(parts)


def part_overrides(blocks, sides, start, end):
    result = []
    for name, block in blocks.items():
        if name in sides:
            block = split_side(block, sides[name], start, end)
        result.append("\n\t\t\t\t"+block.replace("\r\n", "\n"))
    return "".join(result)


def apply_parameters(text, sections, parameters):
    for name, parameters_for_segment in parameters.items():
        meta = sections[name]
        block = replacement(name, meta["values"], parameters_for_segment, meta.get("borders"),
                            meta.get("method", "biarc"), meta.get("curve_radius", DEFAULT_REPAIR_CURVE_RADIUS_M), meta.get("width", 15.0), meta.get("side_profiles"),
                            meta.get("cells", 1), meta.get("curve_steps"), meta.get("pit_lengths"))
        if "\r\n" in text:
            block = block.replace("\n", "\r\n")
        text = text.replace(sections[name]["block"], block, 1)
        text = update_pit_reference(text, name, meta)
    return text


def update_pit_reference(text, name, meta, restore=False):
    if "exit" not in meta.get("pit_roles", []):
        return text
    block = section_blocks(text, 3, ["Main Track"])["Pits"]
    old, new = (name+SUFFIX, name) if restore else (name, name+SUFFIX)
    return text.replace(block, remap_exit_reference(block, old, new), 1)


def selected_labels(name, meta):
    return pit_labels(replacement_labels(name, meta.get("method", "biarc"), meta.get("cells", 1)), meta.get("pit_roles", []))


def fit_bounds(first, last, name):
    delta = last["end"][:2]-first["start"][:2]
    heading = first["angle"]
    x = delta[0]*math.cos(heading)+delta[1]*math.sin(heading)
    y = -delta[0]*math.sin(heading)+delta[1]*math.cos(heading)
    turn = last["end_angle"]-heading
    if x <= 0 or abs(y) < 1e-5:
        raise ValueError(f"{name}: two-arc pilot is unsuitable for this loaded pose")
    initial = np.array([math.hypot(x, y), 4*y/x, turn])
    minimum_peak = initial[0]/FIT_DIAMETER_M
    if minimum_peak >= MAX_LOCAL_TURN_RAD:
        raise ValueError(f"{name}: section is too long for this local pilot")
    peak_bounds = (minimum_peak, MAX_LOCAL_TURN_RAD) if y > 0 else (-MAX_LOCAL_TURN_RAD, -minimum_peak)
    lower = np.array([max(.01, initial[0]-.25), peak_bounds[0], turn-.00003])
    upper = np.array([initial[0]+.25, peak_bounds[1], turn+.00003])
    return np.clip(initial, lower + 1e-10, upper - 1e-10), lower, upper


def scs_fit_bounds(first, last, name, values, radius):
    sign = 1 if values["type"] == "lft" else -1
    delta = last["end"][:2]-first["start"][:2]
    heading = first["angle"]
    x = delta[0]*math.cos(heading)+delta[1]*math.sin(heading)
    y = sign*(-delta[0]*math.sin(heading)+delta[1]*math.cos(heading))
    turn = sign*(last["end_angle"]-heading)
    if x <= 0 or not .00002 < turn < MAX_LOCAL_TURN_RAD:
        raise ValueError(f"{name}: loaded turn is unsuitable for straight–curve–straight fitting")
    after = (y-radius*(1-math.cos(turn)))/math.sin(turn)
    before = x-radius*math.sin(turn)-after*math.cos(turn)
    if min(before, after) <= .1:
        raise ValueError(f"{name}: target pose requires a degenerate/negative straight; try a smaller curve radius")
    initial = np.array([before, turn, after])
    lower = np.array([.1, max(turn-.00003, turn/2), .1])
    upper = np.array([max(x, before)+.25, turn+.00003, max(x, after)+.25])
    return initial, lower, upper


def difference_jacobian(evaluate, values, steps=TWO_ARC_JACOBIAN_STEPS):
    columns = []
    for i, step in enumerate(steps):
        delta = np.zeros(len(values))
        delta[i] = step
        columns.append((evaluate(values+delta)-evaluate(values-delta))/(2*step))
    return np.array(columns).T


def least_squares_fit(residual, initial, lower, upper, steps=TWO_ARC_JACOBIAN_STEPS, scales=TWO_ARC_PARAMETER_SCALES):
    from scipy.optimize import least_squares

    best, best_norm = initial, np.linalg.norm(residual(initial))
    for _ in range(8):
        result = least_squares(residual, best, jac=lambda v: difference_jacobian(residual, v, steps),
                               bounds=(lower, upper), x_scale=scales,
                               max_nfev=100, xtol=1e-13, ftol=1e-13, gtol=1e-12)
        score = np.linalg.norm(residual(result.x))
        if score >= best_norm:
            break
        best, best_norm = result.x, score
    return best, best_norm


def fit_perturbation(rng, method):
    if method == "scs":
        transfer, extension, angle = rng.normal(size=3)*np.array([.04, .0004, .0000002])
        return np.array([transfer+extension, angle, -transfer])
    return rng.normal(size=3)*np.array([.002, .0003, .000001])


def refine_quantized_fit(residual, best, best_norm, lower, upper, seed, method="biarc"):
    rng = np.random.default_rng(seed)
    for scale in (1.0, .2, .05):
        for _ in range(150):
            values = best + fit_perturbation(rng, method)*scale
            if np.any(values < lower) or np.any(values > upper):
                continue
            score = np.linalg.norm(residual(values))
            if score < best_norm:
                best, best_norm = values, score
    return best


def fit(text, sections, loader, seed=DEFAULT_RADIUS_FIT_SEED, resume=None, progress=None, polish=False):
    baseline = loader.load(text)
    if any(meta.get("implicit_flat") for meta in sections.values()):
        if any(np.max(abs(row["vertices"][:, 2])) > 1e-6 for row in baseline["rows"]):
            raise ValueError("Native loader contradicts the inferred flat profile")
    parameters = restore_parameters(sections, resume)
    for number, name in enumerate(sections):
        a, b = group(baseline, name)[0], group(baseline, name)[-1]
        meta = sections[name]
        if meta.get("method") == "auto":
            choose_method(a, b, name, meta)
        configure_sampling(meta, group(baseline, name))
        configure_pit_markers(meta, group(baseline, name))
        initial, lower, upper, steps, scales = fit_settings(a, b, name, meta)
        method = meta.get("method", "biarc")
        heading_weight = meta.get("heading_weight", 30.0)
        print(f"Fitting {name} ({method})", flush=True)

        def residual(v, selected_name=name, target=b, weight=heading_weight):
            trial = apply_parameters(text, sections, dict(parameters, **{selected_name: v}))
            end = fitted_endpoint(loader, trial, selected_name)
            return np.r_[end["end"][:2]-target["end"][:2], (end["end_angle"]-target["end_angle"])*weight]

        initial = np.clip(np.array(parameters.get(name, initial)), lower+1e-12, upper-1e-12)
        best = fit_or_reuse(residual, initial, lower, upper, steps, scales, seed+number*43, method, name in parameters)
        if needs_padded_fit(meta, residual(best)):
            meta["method"] = "sbbs"
            print(f"Refining {name} (sbbs)", flush=True)
            initial, lower, upper, steps, scales = fit_settings(a, b, name, meta)
            best = fit_or_reuse(residual, initial, lower, upper, steps, scales, seed+number*43, "sbbs", False)
        parameters[name] = best.tolist()
        if progress is not None:
            progress(parameters, sections)
    if polish:
        parameters = polish_closure(text, sections, parameters, baseline, loader)
        if progress is not None:
            progress(parameters, sections)
    return apply_parameters(text, sections, parameters), parameters, baseline


def polish_closure(text, sections, parameters, baseline, loader):
    """Quantized last-turn polish, restricted to the already selected repairs."""
    # First try translations without changing headings. Angle changes can move
    # a long unselected run even when the final seam itself improves.
    straight = polish_terminal_straights(text, sections, parameters, baseline, loader)
    if acceptable_polish(text, sections, straight, baseline, loader):
        return straight
    distributed = polish_distributed_straights(text, sections, straight, baseline, loader)
    if acceptable_polish(text, sections, distributed, baseline, loader):
        return distributed
    target = closure_target(baseline)

    def score(values):
        end = fitted_endpoint(loader, apply_parameters(text, sections, values), target["name"])
        residual = np.r_[end["end"][:2]-target["end"][:2], (end["end_angle"]-target["end_angle"])*2000]
        return float(np.linalg.norm(residual))

    best = dict(parameters)
    best_score = score(best)
    for name in list(parameters)[-8:]:
        index = 1 if sections[name]["method"] == "scs" else 2
        origin = list(best[name])
        for step in range(-8, 9):
            values = list(origin)
            values[index] += step*1e-7
            if sections[name]["method"] == "scs" and values[index] <= 0:
                continue
            candidate = dict(best, **{name: values})
            loss = score(candidate)
            if loss < best_score:
                best, best_score = candidate, loss
    best = polish_terminal_straights(text, sections, best, baseline, loader)
    return polish_distributed_straights(text, sections, best, baseline, loader)


def acceptable_polish(text, sections, parameters, baseline, loader):
    model = loader.load(apply_parameters(text, sections, parameters))
    failures = []
    validate_untouched_geometry(sections, baseline, model, failures)
    validate_track_state(baseline, model, failures, sections)
    return not failures


def polish_distributed_straights(text, sections, parameters, baseline, loader):
    """Use differently oriented repaired straights to correct both seam axes."""
    names = [name for name in parameters if sections[name]["method"] == "scs"][-12:]
    if len(names) < 2:
        return parameters
    target = closure_target(baseline)
    original = dict(parameters)

    def updated(offsets):
        return dict(original, **{name: [original[name][0], original[name][1], original[name][2]+float(delta)]
                                 for name, delta in zip(names, offsets, strict=True)})

    def residual(offsets):
        end = fitted_endpoint(loader, apply_parameters(text, sections, updated(offsets)), target["name"])
        return end["end"][:2]-target["end"][:2]

    offsets = np.zeros(len(names))
    score = float(np.linalg.norm(residual(offsets)))
    for _ in range(6):
        jac = difference_jacobian(residual, offsets, [.01]*len(names))
        correction = np.linalg.lstsq(jac, -residual(offsets), rcond=None)[0]
        proposed = np.clip(offsets+correction, -.0015, .0015)
        loss = float(np.linalg.norm(residual(proposed)))
        if loss >= score:
            break
        offsets, score = proposed, loss
    return updated(offsets)


def polish_terminal_straights(text, sections, parameters, baseline, loader):
    names = [name for name in parameters if sections[name]["method"] == "scs"]
    if not names:
        return parameters
    name = names[-1]
    original = parameters[name]
    target = closure_target(baseline)

    def residual(values):
        updated = [float(values[0]), original[1], float(values[1])]
        candidate = dict(parameters, **{name: updated})
        end = fitted_endpoint(loader, apply_parameters(text, sections, candidate), target["name"])
        return end["end"][:2]-target["end"][:2]

    initial = np.array([original[0], original[2]])
    lower, upper = np.maximum(.1, initial-.25), initial+.25
    best, score = least_squares_fit(residual, initial, lower, upper, (.1, .1), (10, 10))
    rng = np.random.default_rng(0)
    for scale in (1., .2):
        for _ in range(100):
            transfer, extension = rng.normal(size=2)*np.array([.02, .0004])*scale
            trial = best + np.array([transfer+extension, -transfer])
            if np.any(trial < lower) or np.any(trial > upper):
                continue
            loss = float(np.linalg.norm(residual(trial)))
            if loss < score:
                best, score = trial, loss
    return dict(parameters, **{name: [float(best[0]), original[1], float(best[1])]})


def closure_target(baseline):
    """Preserve valid seams; move pre-existing gaps inside the acceptance box."""
    target = dict(baseline["rows"][-1])
    target["end"] = np.array(target["end"], copy=True)
    for axis, limit in ((0, DEFAULT_TARGET_DX_M), (1, DEFAULT_TARGET_DY_M)):
        if abs(target["end"][axis]) > limit:
            # Leave rounding room while avoiding unnecessary movement of an
            # otherwise preserved layout to an exactly-zero seam.
            target["end"][axis] = math.copysign(limit*.75, target["end"][axis])
    first_angle = baseline["rows"][0].get("angle", 0.)
    error = math.remainder(target["end_angle"]-first_angle, 2*math.pi)
    if abs(math.degrees(error)) > DEFAULT_TARGET_ANG_DEG:
        target["end_angle"] = float(np.float32(target["end_angle"]-error))
    return target


def restore_parameters(sections, resume):
    if resume is None:
        return {}
    parameters = resume["parameters"]
    for name in parameters:
        sections[name]["method"] = resume["methods"][name]
    return dict(parameters)


def fit_or_reuse(residual, initial, lower, upper, steps, scales, seed, method, reusable):
    error = residual(initial)
    if reusable and np.linalg.norm(error[:2]) <= RESUME_ENDPOINT_TOLERANCE_M and abs(error[2]) <= RESUME_WEIGHTED_HEADING_TOLERANCE:
        return initial
    best, best_norm = least_squares_fit(residual, initial, lower, upper, steps, scales)
    return refine_quantized_fit(residual, best, best_norm, lower, upper, seed, method)


def needs_padded_fit(meta, error):
    return (meta.get("requested_method") == "auto" and meta["method"] == "biarc"
            and np.linalg.norm(error[:2]) > .001)


def fitted_endpoint(loader, text, name):
    if hasattr(loader, "endpoint"):
        return loader.endpoint(text, name)
    return group(loader.load(text), name)[-1]


def fit_settings(first, last, name, meta):
    if meta.get("method") == "auto":
        choose_method(first, last, name, meta)
    if meta.get("method", "biarc") == "scs":
        bounds = scs_fit_bounds(first, last, name, meta["values"], meta["curve_radius"])
        bounds = constrain_pit_bounds(bounds, meta.get("pit_lengths", {}))
        # Smaller-than-boundary finite differences keep all trial parts positive.
        angle_step = min(.00001, bounds[1][1]/2)
        return *bounds, (.05, angle_step, .05), (10, .003, 10)
    if meta.get("method") == "sbbs":
        bounds = padded_fit_bounds(first, last, name)
    else:
        bounds = fit_bounds(first, last, name)
    return *bounds, TWO_ARC_JACOBIAN_STEPS, TWO_ARC_PARAMETER_SCALES


def padded_fit_bounds(first, last, name):
    delta = last["end"][:2]-first["start"][:2]
    heading = first["angle"]
    x = delta[0]*math.cos(heading)+delta[1]*math.sin(heading)
    y = -delta[0]*math.sin(heading)+delta[1]*math.cos(heading)
    turn = last["end_angle"]-heading
    if x <= 0:
        raise ValueError(f"{name}: padded fit requires a forward endpoint")
    length = math.hypot(x, y)
    # Short lobes reach shallower lateral offsets without requiring >4 km
    # radii. The remaining length is carried by the two straight pads.
    active = length*PADDED_ARC_FRACTION
    peak = (2*y-(length-active/2)*turn)/active
    minimum = active/FIT_DIAMETER_M+abs(turn)
    peak_bounds = (minimum, MAX_LOCAL_TURN_RAD) if peak >= 0 else (-MAX_LOCAL_TURN_RAD, -minimum)
    if minimum >= MAX_LOCAL_TURN_RAD:
        raise ValueError(f"{name}: padded fit is too long")
    lower = np.array([max(.01, length-.25), peak_bounds[0], turn-.00003])
    upper = np.array([length+.25, peak_bounds[1], turn+.00003])
    return np.clip(np.array([length, peak, turn]), lower+1e-10, upper-1e-10), lower, upper


def choose_method(first, last, name, meta):
    try:
        scs_fit_bounds(first, last, name, meta["values"], meta["curve_radius"])
    except ValueError:
        meta["method"] = "biarc"
    else:
        meta["method"] = "scs"


def sampled_profile(parts):
    lengths = np.array([r["length"] for r in parts])
    station = np.r_[0, np.cumsum(lengths)]/sum(lengths)
    points = np.vstack([parts[0]["start"], *[r["end"] for r in parts]])
    return sample_points(station, points)


def sampled_edge(parts, side):
    lengths = np.array([r["length"] for r in parts])
    station = np.r_[0, np.cumsum(lengths)]/sum(lengths)
    points = np.vstack([parts[0]["vertices"][side], *[r["vertices"][side+2] for r in parts]])
    return sample_points(station, points)


def sampled_outer_edge(parts, side):
    lengths = np.array([r["length"] for r in parts])
    station = np.r_[0, np.cumsum(lengths)]/sum(lengths)
    points = np.vstack([parts[0]["outer_edges"][side, 0], *[r["outer_edges"][side, 1] for r in parts]])
    return sample_points(station, points)


def sample_points(station, points):
    samples = np.linspace(0, 1, RADIUS_PROFILE_SAMPLE_COUNT)
    return np.array([np.interp(samples, station, points[:, i]) for i in range(3)]).T


def restore_selected_blocks(candidate, sections, blocks):
    restored = candidate
    for name, meta in sections.items():
        start = restored.index(blocks[name])
        end = restored.index(blocks[name+SUFFIX], start)+len(blocks[name+SUFFIX])
        restored = restored[:start]+meta["block"]+restored[end:]
        restored = update_pit_reference(restored, name, meta, restore=True)
    return restored


def validate_preserved_xml(original, candidate, sections, blocks, failures):
    expected = []
    for name in segment_blocks(original):
        if name in sections:
            expected.extend(selected_labels(name, sections[name]))
        else:
            expected.append(name)
    if list(blocks) != expected:
        failures.append("Candidate segment order/names differ from the selected replacements")
    if restore_selected_blocks(candidate, sections, blocks) != original:
        failures.append("XML outside the selected blocks changed")


def validate_replacement(name, meta, blocks, failures):
    method = meta.get("method", "biarc")
    labels = selected_labels(name, meta)
    parts = [section_values(ET.fromstring(blocks[label]), label, allow_straight=method in ("scs", "sbbs"), allow_edge_tangents=True) for label in labels]
    validate_replacement_borders(labels, meta, parts, blocks, failures)
    radii = [float(part["radius"]) for part in parts if part["type"] != "str"]
    if not all(0 < radius <= MAX_TORCS_RADIUS_M for radius in radii):
        failures.append(f"{name}: fitted radius exceeds {MAX_TORCS_RADIUS_M:g} m")
    types = [p["type"] for label, p in zip(labels, parts, strict=True) if not label.endswith((":radius-entry-pad", ":radius-exit-pad"))]
    if method == "scs" and types != ["str" if i % 2 == 0 else meta["values"]["type"] for i in range(len(types))]:
        failures.append(f"{name}: straight–curve–straight types/direction changed")
    if method == "sbbs" and (parts[0]["type"] != "str" or parts[-1]["type"] != "str" or len(radii) != 2):
        failures.append(f"{name}: padded two-arc type sequence changed")
    if any(float(p["lg"] if p["type"] == "str" else p["arc"]) <= 0 for p in parts):
        failures.append(f"{name}: nonpositive part length/arc")
    validate_profile_connections(name, parts, meta["values"], failures)
    validate_banking(name, parts, meta["values"], failures)
    return radii


def validate_replacement_borders(labels, meta, parts, blocks, failures):
    lengths = [float(p["lg"]) if p["type"] == "str" else float(p["radius"])*math.radians(float(p["arc"])) for p in parts]
    stations = np.r_[0, np.cumsum(lengths)]/sum(lengths)
    for i, label in enumerate(labels):
        actual = border_blocks(blocks[label])
        if not overrides_preserved(meta, actual, float(stations[i]), float(stations[i+1])):
            failures.append(f"{label}: original border resets/side profiles were not preserved")


def overrides_preserved(meta, actual, start, end):
    original = meta.get("borders", {})
    if actual.keys() != original.keys():
        return False
    for name, block in original.items():
        state = meta.get("side_profiles", {}).get(name)
        if state and state["start"] != state["end"]:
            if not validate_side_split(block, actual[name], state, start, end):
                return False
        elif actual[name] != block:
            return False
    return True


def validate_profile_connections(name, parts, original, failures):
    for key, part in (("z start", parts[0]), ("profil start tangent", parts[0]), ("z end", parts[-1]), ("profil end tangent", parts[-1])):
        if abs(float(part[key])-float(original[key])) > 1e-9:
            failures.append(f"{name}: endpoint {key} changed")
    for first, last in zip(parts[:-1], parts[1:], strict=True):
        validate_profile_join(name, first, last, failures)


def validate_profile_join(name, first, last, failures):
    for end_key, start_key in (("z end", "z start"), ("profil end tangent", "profil start tangent")):
        if abs(float(first[end_key])-float(last[start_key])) > 1e-9:
            failures.append(f"{name}: midpoint {start_key} is discontinuous")


def validate_local_movement(name, baseline, after, failures):
    delta = sampled_profile(group(after, name))-sampled_profile(group(baseline, name))
    plan = float(np.max(np.linalg.norm(delta[:,:2], axis=1)))
    height = float(np.max(abs(delta[:,2])))
    if not (plan <= RADIUS_LOCAL_CENTER_TOLERANCE_M and height <= RADIUS_LOCAL_HEIGHT_TOLERANCE_M):
        failures.append(f"{name}: local displacement exceeds {RADIUS_LOCAL_CENTER_TOLERANCE_M:.2f} m XY / {RADIUS_LOCAL_HEIGHT_TOLERANCE_M:.2f} m Z")
    edges = validate_local_edges(name, baseline, after, failures)
    edges.update(validate_local_edges(name, baseline, after, failures, outer=True))
    return {"sampled_plan_shift_m": plan, "sampled_height_shift_m": height, **edges}


def validate_local_edges(name, baseline, after, failures, outer=False):
    before_parts, after_parts = group(baseline, name), group(after, name)
    sample = sampled_outer_edge if outer else sampled_edge
    differences = [sample(after_parts, side)-sample(before_parts, side) for side in (0, 1)]
    horizontal = max(float(np.max(np.linalg.norm(delta[:, :2], axis=1))) for delta in differences)
    vertical = max(float(np.max(abs(delta[:, 2]))) for delta in differences)
    if not (horizontal <= RADIUS_LOCAL_EDGE_TOLERANCE_M and vertical <= RADIUS_LOCAL_HEIGHT_TOLERANCE_M):
        kind = "outer-side" if outer else "road-edge"
        failures.append(f"{name}: {kind} displacement exceeds {RADIUS_LOCAL_EDGE_TOLERANCE_M:.2f} m XY / {RADIUS_LOCAL_HEIGHT_TOLERANCE_M:.2f} m Z")
    prefix = "sampled_outer" if outer else "sampled_edge"
    return {prefix+"_plan_shift_m": horizontal, prefix+"_height_shift_m": vertical}


def validate_untouched_geometry(sections, baseline, after, failures):
    before_map = {r["name"]: r for r in baseline["rows"]}
    after_map = {r["name"]: r for r in after["rows"]}
    shift = max((float(np.linalg.norm(after_map[n]["end"]-r["end"])) for n,r in before_map.items() if n not in sections), default=0.0)
    if shift > RADIUS_UNTOUCHED_TOLERANCE_M:
        failures.append(f"Untouched segment endpoints moved by more than {RADIUS_UNTOUCHED_TOLERANCE_M*1000:g} mm")
    untouched_vertex_shift = 0.0
    untouched_outer_shift = 0.0
    outliers = []
    for name in before_map.keys()-sections.keys():
        old_rows = [r for r in baseline["rows"] if r["name"] == name]
        new_rows = [r for r in after["rows"] if r["name"] == name]
        if len(old_rows) != len(new_rows):
            failures.append(f"{name}: untouched subdivision count changed")
            continue
        old_vertices = np.array([r["vertices"] for r in old_rows])
        new_vertices = np.array([r["vertices"] for r in new_rows])
        untouched_vertex_shift = max(untouched_vertex_shift, float(np.max(np.linalg.norm(new_vertices-old_vertices, axis=2))))
        old_outer = np.array([r["outer_edges"] for r in old_rows])
        new_outer = np.array([r["outer_edges"] for r in new_rows])
        outer_shift = float(np.max(np.linalg.norm(new_outer-old_outer, axis=-1)))
        vertex_shift = float(np.max(np.linalg.norm(new_vertices-old_vertices, axis=2)))
        untouched_outer_shift = max(untouched_outer_shift, outer_shift)
        if max(outer_shift, vertex_shift) > RADIUS_UNTOUCHED_TOLERANCE_M*.75:
            outliers.append({"segment": name, "road_shift_m": vertex_shift, "outer_shift_m": outer_shift})
    if untouched_vertex_shift > RADIUS_UNTOUCHED_TOLERANCE_M:
        failures.append(f"Untouched road vertices moved by more than {RADIUS_UNTOUCHED_TOLERANCE_M*1000:g} mm")
    if untouched_outer_shift > RADIUS_UNTOUCHED_TOLERANCE_M:
        failures.append(f"Untouched outer side vertices moved by more than {RADIUS_UNTOUCHED_TOLERANCE_M*1000:g} mm")
    origin_shift = after["origin"]-baseline["origin"]
    if np.linalg.norm(origin_shift) > RADIUS_UNTOUCHED_TOLERANCE_M:
        failures.append(f"Normalized origin moved by more than {RADIUS_UNTOUCHED_TOLERANCE_M*1000:g} mm")
    return {"untouched_endpoint_shift_m": shift, "untouched_vertex_shift_m": untouched_vertex_shift,
            "untouched_outer_shift_m": untouched_outer_shift,
            "untouched_outliers": sorted(outliers, key=lambda item: max(item["road_shift_m"], item["outer_shift_m"]), reverse=True),
            "origin_shift_m": origin_shift.tolist()}


def validate_track_state(baseline, after, failures, sections=()):
    # Use road-edge closure, as trackgen does; centreline averages can hide a gap.
    edge_gaps = after["rows"][-1]["vertices"][2:] - after["rows"][0]["vertices"][:2]
    angle = math.degrees(math.remainder(after["rows"][-1]["end_angle"]-after["rows"][0]["angle"], 2*math.pi))
    closure_limits = np.array([DEFAULT_TARGET_DX_M, DEFAULT_TARGET_DY_M, DEFAULT_TARGET_DZ_M])
    if not (np.all(abs(edge_gaps) <= closure_limits) and abs(angle) <= DEFAULT_TARGET_ANG_DEG):
        failures.append("Track closure exceeds finalization limits")
    for key in ("pit_count", "wall_runs"):
        if baseline[key] != after[key]:
            failures.append(f"{key} changed")
    extent_shift = after.get("extent", np.zeros(3))-baseline.get("extent", np.zeros(3))
    if np.any(abs(extent_shift) > RADIUS_UNTOUCHED_TOLERANCE_M):
        failures.append(f"Native track extents changed by more than {RADIUS_UNTOUCHED_TOLERANCE_M*1000:g} mm")
    return {"road_edge_closure_m": edge_gaps.tolist(), "closure_angle_deg": angle,
            "pit_marker_shifts": validate_pit_markers(baseline, after, failures, sections),
            "extent_shift_m": extent_shift.tolist(),
            "pit_count": after["pit_count"], "wall_runs": after["wall_runs"],
            "before_length_m": sum(r["length"] for r in baseline["rows"]),
            "after_length_m": sum(r["length"] for r in after["rows"])}


def validate(original, candidate, sections, baseline, after):
    failures, repairs = [], {}
    blocks = segment_blocks(candidate)
    for name, meta in sections.items():
        if meta.get("method") == "auto":
            meta["method"] = candidate_method(name, blocks)
        if meta.get("method") == "scs":
            meta["cells"] = max(1, sum(label.startswith(name+":radius-turn-") for label in blocks))
    validate_preserved_xml(original, candidate, sections, blocks, failures)
    for name, meta in sections.items():
        radii = validate_replacement(name, meta, blocks, failures)
        repairs[name] = {"radii_m": radii, **validate_local_movement(name, baseline, after, failures)}
    geometry = validate_untouched_geometry(sections, baseline, after, failures)
    state = validate_track_state(baseline, after, failures, sections)
    return {"accepted": not failures, "failures": failures, "repairs": repairs, **geometry, **state}


def candidate_method(name, blocks):
    if name+IN_SUFFIX in blocks:
        return "sbbs"
    return "scs" if name+TURN_SUFFIX in blocks or any(label.startswith(name+":radius-turn-") for label in blocks) else "biarc"
