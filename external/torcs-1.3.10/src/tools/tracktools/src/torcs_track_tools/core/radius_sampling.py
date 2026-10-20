# /***************************************************************************
#     file                 : radius_sampling.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Preserve native angular sampling and distribute long shallow bends."""

import math


def configure_sampling(meta, original_parts):
    if meta.get("requested_method") != "auto":
        return
    meta["curve_steps"] = len(original_parts)
    meta["heading_weight"] = 20000.
    if meta["method"] != "scs":
        return
    radius = float(meta["values"]["radius"])
    arc = math.radians(float(meta["values"]["arc"]))
    # A single concentrated turn departs from a long shallow circle by roughly
    # (R-r)*angle^2/8. More cells reduce that shape error approximately as N^2.
    error = max(0., radius-meta["curve_radius"])*arc*arc/8
    cells = max(1, min(8, math.ceil(math.sqrt(error/.035))))
    meta["cells"] = min(cells, meta["curve_steps"])


def step_counts(total, cells):
    if total is None:
        return [None]*cells
    whole, extra = divmod(total, cells)
    return [whole+int(i < extra) for i in range(cells)]


def scs_geometry(kind, parameters, radius, cells=1, native_steps=None):
    before, angle, after = parameters
    if min(before, angle, after) <= 0:
        raise ValueError("Degenerate straight–curve–straight fit")
    counts = step_counts(native_steps, cells)
    if cells == 1:
        return [("str", before, 0, 0), (kind, radius*angle, radius, angle, counts[0]), ("str", after, 0, 0)]
    weights = [count/native_steps for count in counts] if native_steps else [1/cells]*cells
    pads = [(before+after)*weight for weight in weights]
    transfer = (before-after)/2
    first, last = pads[0]/2+transfer, pads[-1]/2-transfer
    if min(first, last) <= 0:
        raise ValueError("Distributed curve needs positive end pads")
    result = [("str", first, 0, 0)]
    for i, weight in enumerate(weights):
        result.append((kind, radius*angle*weight, radius, angle*weight, counts[i]))
        following = last if i == cells-1 else (pads[i]+pads[i+1])/2
        result.append(("str", following, 0, 0))
    return result


def distributed_labels(name, cells):
    labels = [name]
    for i in range(cells):
        labels.append(name+f":radius-turn-{i+1}")
        labels.append(name+":radius-out" if i == cells-1 else name+f":radius-pad-{i+1}")
    return labels
