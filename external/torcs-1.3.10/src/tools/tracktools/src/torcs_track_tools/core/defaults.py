# /***************************************************************************
#
#     file                 : defaults.py
#     created              : 04 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Shared TORCS track authoring defaults used by tracktools scripts."""

from __future__ import annotations

DEFAULT_LICENSE = "GNU General Public License version 2 or later"
PLACEHOLDER_AUTHORS = {"", "opencode", "unknown", "todo", "tbd", "required_by_torcs_track_tools"}

ENTITY_PLACEHOLDER = "__DEFAULT_SURFACES_ENTITY__"

BORDER_NAMES = ("Left Border", "Right Border")
NORMAL_BORDER_WIDTH = 1.0
NORMAL_BORDER_STYLE = "plan"
NORMAL_BORDER_SURFACE = "b-road1-grass6"
PIT_TRANSITION_BORDER_SURFACE = "b-road1-l2p"
LEFT_CURB_SURFACE = "curb-5cm-l"
RIGHT_CURB_SURFACE = "curb-5cm-r"

DEFAULT_PROFILE_STEPS_LENGTH_M = 6.0

DEFAULT_TARGET_DX_M = 0.0005
DEFAULT_TARGET_DY_M = 0.001
DEFAULT_TARGET_DZ_M = 0.00005
DEFAULT_TARGET_ANG_DEG = 0.0001

# Loaded-geometry preservation policy for radius repairs (metres).
DEFAULT_REPAIR_CURVE_RADIUS_M = 3000.0
DEFAULT_RADIUS_FIT_SEED = 22
RADIUS_UNTOUCHED_TOLERANCE_M = 0.002
RADIUS_LOCAL_CENTER_TOLERANCE_M = 0.10
RADIUS_LOCAL_EDGE_TOLERANCE_M = 0.15
RADIUS_LOCAL_HEIGHT_TOLERANCE_M = 0.02
RADIUS_PROFILE_SAMPLE_COUNT = 501  # 500 intervals, including both endpoints.

# Match TORCS parameter-unit conversion, including its legacy feet factor.
DISTANCE_TO_METERS = {
    "": 1.0, "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "feet": 0.304801, "ft": 0.304801,
    "inches": 0.0254, "inch": 0.0254, "in": 0.0254,
}
