# Track Manual {#track_manual}

\anchor track_manual_top

This manual explains how TORCS tracks are authored and processed. It starts with an easy conceptual view and then goes into
reference-level detail. It focuses on TORCS behavior and data formats, and discusses AC3D/Blender only where needed for
alignment-safe post-editing. It covers the most recent TORCS track XML format, version 4 (`v4`). The TORCS track editor is not discussed here.

**Contents**

- [1. XML and 3D model](@ref track_manual_1)
- [2. Authoring workflow overview](@ref track_manual_2)
- [3. Tool workflow in detail (`trackgen`, `accc`)](@ref track_manual_3)
- [4. Top-level XML structure](@ref track_manual_4)
- [5. Main Track defaults](@ref track_manual_5)
- [6. Segment geometry (`str`, `lft`, `rgt`)](@ref track_manual_6)
- [7. Elevation and banking](@ref track_manual_7)
- [8. Profile modes (`linear` vs `spline`)](@ref track_manual_8)
- [9. Interpolation and sub-segmentation](@ref track_manual_9)
- [10. Side, border, barrier and variable width](@ref track_manual_10)
- [11. Guidance: when to use side, border, or both](@ref track_manual_11)
- [12. Surface system deep dive (physics + rendering)](@ref track_manual_12)
- [13. Terrain generation chapter (`Graphic/Terrain Generation`)](@ref track_manual_13)
- [14. `trackgen -E` elevation export modes](@ref track_manual_14)
- [15. Pits and cameras](@ref track_manual_15)
- [16. Units and numeric interpretation](@ref track_manual_16)
- [17. Advanced fields and compatibility notes](@ref track_manual_17)
- [18. Reference tables](@ref track_manual_18)
- [19. Author checklist](@ref track_manual_19)

\section track_manual_1 1. XML and 3D model

When you create a TORCS track, there are two related descriptions:

1. **Logical/physical description (XML)**
   - segment layout, elevations, banking, side areas
   - surfaces and physical coefficients
   - pits, cameras, terrain generation settings
2. **Visual model (.ac)**
   - rendered geometry used by graphics
   - referenced from `Graphic/3d description` (usually `<name>.ac` or `<name>.acc`)

Think of it as:

- XML = how the track behaves
- `.ac` or `.acc` = how the track looks

Both should stay consistent. If they drift apart, players can see one edge and collide
with another.

\section track_manual_2 2. Authoring workflow overview

For command-line helpers that convert maps or drawings into track layouts and add
curbs, pits, and elevation, see the [Track Tools Guide](../tools/tracktools/README.md).

Typical loop:

1. Edit `name.xml`.
2. Generate assets with `trackgen`.
3. Optionally post-process with `accc`.
4. Test in TORCS.
5. Iterate back to 1.
6. Optional: Generate raceline geometry with `trackgen -r`.
7. Optional: Edit/add objects in a 3D modeling tool such as AC3D or Blender.
8. Optional: Combine raceline, shading, and track AC files with `accc` into the final track model.

For beginners: start with simple geometry and defaults, then add complexity in this order:

1. segments and width
2. elevation and banking
3. side/border/barrier tuning
4. surfaces and textures
5. pits/cameras
6. terrain and tool-specific refinements

For a compact applied snippet that combines these concepts, see
[11.1 Mini end-to-end XML example](@ref track_manual_example).

\subsection track_manual_2_license 2.1 License and assets (boring, but important)

Track metadata and asset rights should be explicit from the beginning. Beware, if you are not clear about it or choose
incompatible licensing with TORCS, your track cannot be integrated in TORCS or further developed by other people later:

- set `author` and `description` in XML `Header`
- add a clear license statement in track README
- document third-party asset source, author, and license

Do not use random internet assets with unknown license state.
Do not include commercial/proprietary assets unless redistribution and derivative-use
rights are explicitly compatible with your track release.

If you reuse TORCS assets, your track is a derivative work of TORCS content and must
be distributed under terms compatible with TORCS licensing (GPL version 2 or later).

Practical recommendation for README:

- `License` section for XML/AC/ACC/textures
- `Authors` and attribution list
- `Third-party assets` table (source URL, license, modifications)
- short note about whether redistribution and modification are allowed

\subsection track_manual_categories 2.2 Track categories and paths

Tracks are stored in `tracks/<category>/<name>/`, with their definition named
`<name>.xml`. Set `Header/category` to the same category ID used in the directory
and in `trackgen -c <category> -n <name>`.

<table>
  <tr><th>Category ID</th><th>Display name</th><th>Purpose</th></tr>
  <tr><td><code>road</code></td><td>Road Tracks</td><td>Established road racing circuits.</td></tr>
  <tr><td><code>oval</code></td><td>Oval Tracks</td><td>Oval racing circuits.</td></tr>
  <tr><td><code>dirt</code></td><td>Dirt Tracks</td><td>Dirt and mixed-surface racing circuits.</td></tr>
  <tr><td><code>experimental</code></td><td>Experimental Tracks</td><td>Playable work-in-progress tracks.</td></tr>
  <tr><td><code>test</code></td><td>Test Tracks</td><td>Technical layouts for testing geometry, rendering, physics, and tooling.</td></tr>
</table>

For example, an experimental track belongs at
`tracks/experimental/mytrack/mytrack.xml` and uses
`<attstr name="category" val="experimental"/>` in its `Header`.

Category display names come from `data/tracks/<category>.xml`. The track selector
discovers categories dynamically and skips those without valid track definitions.

\section track_manual_3 3. Tool workflow in detail (`trackgen`, `accc`)

\subsection track_manual_trackgen `trackgen` basics

Trackgen takes the track XML file as input and generates the initial 3D-model or model parts (`.ac` files). Basic command:

```bash
trackgen -c <category> -n <name>
```

Common options:

- `-c`, `-n`: category and track name (required).
- `-a`: generate all (track + terrain path).
- `-s`: split track and terrain output.
- `-S`: split all output.
- `-b`: bump-track generation mode.
- `-r`: raceline-track generation mode.
- `-z`: calculate and exit (no full generation).
- `-B`: do not auto-generate border from rectangle; use relief border.
- `-E <n>`: export elevation image mode (detailed in chapter 14).
- `-H <nb>`: height step count for `-E 4`.
- `-i <xml_path>`, `-o <ac_path>`: useful for tests/custom paths.

Example:

```bash
trackgen -c road -n mytrack -a
```

\subsection track_manual_accc `accc` basics

`accc` transforms or merges AC3D files.

Track-focused use cases:

- `+shad`: generate a shading-oriented AC3D file.
- `-g ... -l0 ... -l1 ...`: combine multilayer geometry.
- `+o`: optimize track-zone grouping output.

Car-oriented options (`+s`, `+es`, `+et`) are available but are not the primary path
for basic track authoring.

Example track merge flow:

```bash
accc +shad name-bak.ac name-shade.ac
accc -g name.ac -l0 name-bak.ac -l1 name-shade.ac -d3 1000 -d2 500 -d1 300 -S 300 -es
```

\subsection track_manual_3_alignment 3.1 3D model alignment contract (AC3D/Blender edits)

This is the critical rule when editing generated `.ac` files:

- physics/collision use the XML-generated track geometry
- graphics render `Graphic/3d description`
- they only line up because both use the same coordinates

If you move/rotate/scale the generated road mesh in AC3D/Blender, visuals and
physics drift apart.

\subsubsection track_manual_origin What exactly is `(0,0,0)`

TORCS computes a bounding box from generated track geometry (track only, without terrain/scenery), then shifts
all segment and camera coordinates so the minimum corner becomes `(0,0,0)`.

- It is the corner with minimum `x`, minimum `y`, minimum `z`.
- It is not tied to the start line.
- It is based on generated track geometry (main/side/border vertices), not terrain.
- Barrier thickness does not expand this origin box because barrier `width` is stored
  as barrier metadata, not as extra boundary vertices.

Geographic metadata uses a different reference: the road centre at the start of
the first segment. See [4.1 Optional georeference](@ref track_manual_georeference).

In practice this means: if you inspect the model, origin often appears aligned with
the inner side of wall barriers (before barrier thickness), which is expected.

\subsubsection track_manual_origin_grid Is origin location random from the start grid perspective?

No. With standard generation and start direction, origin is deterministic:

- it is at or behind start in `x`
- it is at or right of start in `y`

So origin is in the back-right quadrant (including boundaries) when you face race
direction on the grid.

\subsubsection track_manual_axes AC3D axis mapping to TORCS

When loading AC3D vertices, TORCS remaps axes as:

- `x_torcs = x_ac3d`
- `y_torcs = -z_ac3d`
- `z_torcs = y_ac3d`

So AC3D up-axis (`Y`) becomes TORCS up-axis (`Z`), and AC3D `Z` maps to TORCS `Y`
with sign inversion.

\subsubsection track_manual_post_edits Safe and unsafe post-edits

Safe edits:

- add scenery objects
- tweak materials/textures/UVs
- merge layers with `accc` while keeping base road geometry unchanged

Unsafe edits:

- global transform (move/rotate/scale) of generated road mesh
- editing road chunk coordinates without regenerating from XML
- deleting/renaming structural track chunks used by grouping workflows

Quick validation after edits:

- `trackgen` closure deltas remain near zero
- visible road edge matches drivable/collision edge in-game
- pits and cameras still line up

\section track_manual_4 4. Top-level XML structure

Typical layout (simplified):

```xml
<params name="..." type="trackdef" mode="mw">
  <section name="Header">
    <attnum name="version" val="4"/>
    <!-- name, category, author, description -->
  </section>
  <section name="Georeference"> ... </section> <!-- optional -->
  <section name="Surfaces"> ... </section>
  <section name="Graphic"> ... </section>
  <section name="Main Track">
    <section name="Left Side"> ... </section>
    <section name="Right Side"> ... </section>
    <section name="Left Border"> ... </section>
    <section name="Right Border"> ... </section>
    <section name="Left Barrier"> ... </section>
    <section name="Right Barrier"> ... </section>
    <section name="Pits"> ... </section>
    <section name="Track Segments"> ... </section>
  </section>
  <section name="Cameras"> ... </section>
</params>
```

Use exact key strings from `track.h`.

\subsection track_manual_georeference 4.1 Optional georeference

Version-4 tracks can contain an optional top-level `Georeference` section. Its
values refer to the main-road centre at the beginning of the first segment,
the simulated start/finish line.

```xml
<section name="Georeference">
  <attnum name="latitude" unit="deg" val="45.1234567"/>
  <attnum name="longitude" unit="deg" val="7.1234567"/>
  <attnum name="altitude" unit="m" val="230.5"/>
  <attnum name="heading" unit="deg" val="90"/>
</section>
```

<table>
  <tr><th>Key</th><th>Meaning</th></tr>
  <tr><td><code>latitude</code></td><td>WGS84 latitude in degrees, north positive; between -90 and 90.</td></tr>
  <tr><td><code>longitude</code></td><td>WGS84 longitude in degrees, east positive; between -180 and 180.</td></tr>
  <tr><td><code>altitude</code></td><td>Metres above approximate mean sea level at the road centre. Zero and negative values are valid.</td></tr>
  <tr><td><code>heading</code></td><td>Driving direction in degrees clockwise from true north: 0 north, 90 east, 180 south, 270 west.</td></tr>
</table>

Omit unknown values; latitude and longitude must be supplied together. The whole
section may be omitted, for example for a fantasy circuit. Altitude here is
independent of the terrain generation altitude range.

These values are currently informational and do not affect track geometry or racing, but
might be used in the future to place the track on a world map or retrieve local weather.

\section track_manual_5 5. Main Track defaults

`Main Track` provides default values used by segments:

- `width`
- `surface`
- `profil steps length`
- default side/border/barrier sections

Important behavior:

- Main segment width is effectively global (`Main Track/width` used for runtime main segments).
- If you need local widening/narrowing, use side/border design, not per-main-segment road width.

\section track_manual_6 6. Segment geometry (`str`, `lft`, `rgt`)

Each `Main Track/Track Segments/<segment>` entry is one authoring segment.
Segments are listed in driving order. Left and right are viewed facing the direction of travel.

- `type="str"`: straight; `lg` specifies its length.
- `type="lft"`: left-hand turn; requires `radius` and `arc` (turn angle).
- `type="rgt"`: right-hand turn; requires `radius` and `arc`.
- `end radius` optional: enables varying-radius turns.

Example:

```xml
<section name="curve 1">
  <attstr name="type" val="rgt"/>
  <attnum name="arc" unit="deg" val="40.0"/>
  <attnum name="radius" unit="m" val="160.0"/>
  <attnum name="end radius" unit="m" val="100.0"/>
</section>
```

\section track_manual_7 7. Elevation and banking

Plain language:

- `z ...` values define height.
- `grade` defines longitudinal slope; positive values climb in driving direction.
- `banking ...` defines left-right tilt; positive angles raise the left edge relative to the right.

Loader resolution order (important):

1. continuity from previous segment
2. explicit start values (`z start` overrides side-specific start)
3. end centre height (`z end`, else `grade`, else the average of side-specific end heights)
4. banking effects (`banking start/end`) applied where specified

Practical advice:

- Prefer one clear method per segment.
- If you combine methods, do so intentionally and test seams.

\section track_manual_8 8. Profile modes (`linear` vs `spline`)

`profil` (the literal XML spelling for "profile") controls how vertical profile changes inside a segment.

- `linear`: constant slope across the segment.
- `spline`: smooth curve from start to end heights.

What is a spline here?

- The loader uses Hermite interpolation (`TrackSpline`): start and end heights plus
  tangent values shape the curve.

Tangent fields:

- `profil start tangent`, `profil end tangent`
- `profil start tangent left/right`, `profil end tangent left/right`

Generic tangents override side-specific tangents at the same boundary.

\section track_manual_9 9. Interpolation and sub-segmentation

Key model:

- XML segment = authoring unit
- runtime segment(s) = simulation/render units

One authored segment may become multiple runtime segments.

\subsection track_manual_steps Step count logic

For `profil="spline"`:

- start with `profil steps`
- if `profil steps == 1`: `steps = int(length / profil steps length) + 1`
- if segment-local `profil steps length` missing: fallback to `Main Track/profil steps length`

For `profil="linear"`: `steps = 1` in loader behavior.

\subsection track_manual_interpolation What is interpolated per runtime segment

- vertical profile
- side width (`start width` -> `end width`)
- attached side/border/barrier geometry

Example:

- `lg = 180m`, `profil="spline"`, `profil steps length = 15m`
- `steps = int(180/15)+1 = 13`

\section track_manual_10 10. Side, border, barrier and variable width

Outward from main track on each side:

1. border
2. side
3. barrier

Variable-width behavior:

- side supports continuous taper (`start width`, `end width`)
- border width is effectively constant within one authored segment
- border can change on each segment

`banking type` for sides:

- `level`: level across the side's width, starting at the adjoining edge height.
- `tangent`: continues the adjoining road's cross-slope across the side.

\subsection track_manual_10_1 10.1 Curb height behavior (`style="curb"`)

`height` on curb-style border segments is not just decorative. It affects both sampled
track height and generated geometry.

Runtime height sampling behavior ([RtTrackHeightL()](@ref RtTrackHeightL)):

- base height is first computed from segment z-profile and banking
- curb then adds a cross-width offset that ramps linearly across the curb width
- formula conceptually is:
  - `base_height + alpha * (curb_height + curb_roughness) / width`
- `alpha` runs across the curb width and is mirrored for right-border orientation
- `curb_roughness` comes from surface roughness and wavelength along segment length

Practical effect:

- wheel/body height on curbs rises smoothly from one edge to the other
- curb can carry extra ripple from the assigned surface roughness model

\subsection track_manual_10_2 10.2 Wall behavior and collision model (`style="wall"`)

There are two relevant collision paths:

1. **Barrier-line collision (always active when crossing barrier bounds)**
   - car corner outside left/right bounds collides against segment barrier normal
   - response uses barrier surface properties (`friction`, `rebound`, `dammage`)
2. **Solid wall object collision (style-driven)**
   - collision solids are built from contiguous `TR_WALL` chains
   - wall height is used to extrude vertical polygons
   - this path is explicitly wall-style specific

Important limitation from current simulation code:

- dedicated solid collision generation exists for wall-style chains
- curbs and flat plan borders are not handled as full solid wall objects in that path

Authoring implication:

- if you need strong body-blocking vertical behavior, use `style="wall"` with
  meaningful `height`
- if you need drivable edge elevation behavior, use `style="curb"` and tune `height`

\section track_manual_11 11. Guidance: when to use side, border, or both

Use **border only** when:

- you need a narrow fixed edge (curb/paint/lip)

Use **side only** when:

- you need runoff/apron with taper

Use **both** when:

- you want realistic layering: asphalt -> curb(border) -> runoff(side) -> barrier

Pit merge rule of thumb:

- taper side across multiple segments
- keep border minimal in crossing zones

\subsection track_manual_example 11.1 Mini end-to-end XML example

This is a full runnable example designed for copy/paste, just try it. It uses an oval layout
(two 180-degree turns), a realistic pit lane layout with 20 pit slots, and demonstrates
banking plus a descending counter-straight.

\code{.xml}
<?xml version="1.0" encoding="UTF-8"?>
<!-- 
    file                 : manual_oval.xml
    copyright            : (C) 2026 by Bernhard Wymann
-->
<!--    This program is free software; you can redistribute it and/or modify  -->
<!--    it under the terms of the GNU General Public License as published by  -->
<!--    the Free Software Foundation; either version 2 of the License, or     -->
<!--    (at your option) any later version.                                   -->

<!DOCTYPE params SYSTEM "../../../src/libs/tgf/params.dtd" [
<!ENTITY default-surfaces SYSTEM "../../../data/tracks/surfaces.xml">
<!ENTITY default-objects SYSTEM "../../../data/tracks/objects.xml">
]>
<params name="Manual Oval" type="trackdef" mode="mw">
  <section name="Header">
    <attstr name="name" val="Manual Oval"/>
    <attstr name="category" val="road"/>
    <attnum name="version" val="4"/>
    <attstr name="author" val="Track Manual"/>
    <attstr name="description" val="Runnable example with pits"/>
  </section>

  <section name="Graphic">
    <attstr name="3d description" val="manual_oval.ac"/>
    <attstr name="background image" val="background.png"/>
    <attnum name="background type" val="4"/>
    <section name="Environment Mapping">
      <section name="1">
        <attstr name="env map image" val="env.png"/>
      </section>
    </section>
    <section name="Terrain Generation">
      <attnum name="track step" unit="m" val="8"/>
      <attnum name="border margin" unit="m" val="140"/>
      <attnum name="border step" unit="m" val="16"/>
      <attnum name="terrain transition" unit="m" val="140"/>
      <attnum name="border height" unit="m" val="0"/>
      <attstr name="surface" val="gravel"/>
    </section>
  </section>

  <section name="Surfaces">
    &default-surfaces;

    <!-- Custom main-road surface with raceline overlay texture -->
    <section name="manual-asphalt">
      <attstr name="texture name" val="tr-road1.rgb"/>
      <attstr name="texture type" val="continuous"/>
      <attnum name="texture size" unit="m" val="15.0001"/>
      <attnum name="texture mipmap" unit="m" val="0.0"/>
      <attstr name="texture start on boundary" val="yes"/>
      <attstr name="texture link with previous" val="yes"/>
      <attstr name="raceline name" val="raceline.png"/>
      <attnum name="friction" val="1.06"/>
      <attnum name="rolling resistance" val="0.021"/>
      <attnum name="roughness" val="0.0007"/>
      <attnum name="roughness wavelength" val="2.0"/>
    </section>
  
    <section name="manual-barrier">
      <attstr name="texture name" val="arbor2_n.rgb"/>
      <attstr name="texture type" val="continuous"/>
      <attnum name="texture size" val="10.0" unit="m"/>
      <attnum name="texture mipmap" val="0.0"/>
      <attnum name="friction" val="0.0"/>
      <attnum name="dammage" val="10"/>
    </section>
  </section>

  <section name="Main Track">
    <attnum name="width" unit="m" val="12.0"/>
    <attstr name="surface" val="manual-asphalt"/>
    <attnum name="profil steps length" unit="m" val="4.0"/>
    <attnum name="raceline widthscale" val="1.5"/>
    <attnum name="raceline int" val="3"/>
    <attnum name="raceline ext" val="3"/>

    <section name="Left Border">
      <attnum name="width" unit="m" val="0.8"/>
      <attnum name="height" unit="m" val="0.04"/>
      <attstr name="style" val="curb"/>
      <attstr name="surface" val="curb-5cm-l"/>
    </section>
    <section name="Right Border">
      <attnum name="width" unit="m" val="0.8"/>
      <attnum name="height" unit="m" val="0.04"/>
      <attstr name="style" val="curb"/>
      <attstr name="surface" val="curb-5cm-r"/>
    </section>

    <section name="Left Side">
      <attnum name="width" unit="m" val="5.0"/>
      <attstr name="banking type" val="tangent"/>
      <attstr name="surface" val="grass6"/>
    </section>
    <section name="Right Side">
      <attnum name="width" unit="m" val="4.0"/>
      <attstr name="banking type" val="level"/>
      <attstr name="surface" val="grass6"/>
    </section>

    <section name="Left Barrier">
      <attnum name="width" unit="m" val="0.0"/>
      <attnum name="height" unit="m" val="4.0"/>
      <attstr name="style" val="fence"/>
      <attstr name="surface" val="manual-barrier"/>
    </section>
    <section name="Right Barrier">
      <attnum name="width" unit="m" val="0.5"/>
      <attnum name="height" unit="m" val="1.2"/>
      <attstr name="style" val="wall"/>
      <attstr name="surface" val="wall"/>
    </section>

    <section name="Pits">
      <attstr name="type" val="track side"/>
      <attstr name="side" val="right"/>
      <attstr name="entry" val="pit_entry"/>
      <attstr name="start" val="pit_main"/>
      <attstr name="end" val="pit_main"/>
      <attstr name="exit" val="pit_exit"/>
      <attnum name="speed limit" unit="km/h" val="80"/>
      <attnum name="length" unit="m" val="15"/>
      <attnum name="width" unit="m" val="5.0"/>
    </section>

    <section name="Track Segments">
      <section name="pit_entry">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200.0"/>
        <section name="Right Side">
          <attstr name="surface" val="manual-asphalt"/>
          <attnum name="start width" unit="m" val="4.0"/>
          <attnum name="end width" unit="m" val="14.2"/>
        </section>
        <section name="Right Border">
          <attstr name="style" val="plan"/>
          <attstr name="surface" val="b-road1-l2p"/>
        </section>
      </section>

      <section name="pit_main">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="300.0"/>
        <section name="Right Side">
          <attstr name="surface" val="road1-pits"/>
          <attnum name="start width" unit="m" val="14.5"/>
          <attnum name="end width" unit="m" val="14.5"/>
        </section>
        <section name="Right Border">
          <attstr name="style" val="wall"/>
          <attstr name="surface" val="wall"/>
          <attnum name="width" unit="m" val="0.5"/>
          <attnum name="height" unit="m" val="1.0"/>
        </section>
        <section name="Left Border">
          <attnum name="width" unit="m" val="0.8"/>
          <attstr name="style" val="plan"/>
          <attstr name="surface" val="b-road1-grass6"/>
        </section>
      </section>

      <section name="pit_exit">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200.0"/>
        <attnum name="banking start" unit="deg" val="0.0"/>
        <attnum name="banking end" unit="deg" val="15.0"/>
        <section name="Right Side">
          <attstr name="surface" val="manual-asphalt"/>
          <attnum name="start width" unit="m" val="14.2"/>
          <attnum name="end width" unit="m" val="4.0"/>
        </section>
        <section name="Right Border">
          <attstr name="style" val="plan"/>
          <attstr name="surface" val="b-road1-l2p"/>
          <attnum name="width" unit="m" val="0.8"/>
        </section>
      </section>

      <section name="turn_1">
        <attstr name="type" val="rgt"/>
        <attnum name="radius" unit="m" val="90.0"/>
        <attnum name="arc" unit="deg" val="180.0"/>
        <attnum name="z end" unit="m" val="-10.0"/>
        <attnum name="profil steps length" unit="m" val="3.0"/>
        <attnum name="banking start" unit="deg" val="15.0"/>
        <attnum name="banking end" unit="deg" val="15.0"/>
        <attstr name="marks" val="50;100"/>
        <section name="Right Border">
          <attstr name="style" val="curb"/>
          <attstr name="surface" val="curb-5cm-r"/>
          <attnum name="height" unit="m" val="0.06"/>
        </section>
        <section name="Right Side">
          <attstr name="surface" val="grass6"/>
          <attnum name="start width" unit="m" val="4.0"/>
          <attnum name="end width" unit="m" val="4.0"/>
        </section>
      </section>

      <section name="counter_straight_end_banking">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200.0"/>
        <attnum name="banking start" unit="deg" val="15.0"/>
        <attnum name="banking end" unit="deg" val="0.0"/>
        <attnum name="z end" unit="m" val="5.0"/>
        <section name="Right Border">
          <attstr name="style" val="plan"/>
          <attstr name="surface" val="b-road1-grass6"/>
        </section>
      </section>

      <section name="counter_straight">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="300.0"/>
        <attnum name="z end" unit="m" val="0.0"/>
      </section>

      <section name="counter_straight_start_banking">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200.0"/>
        <attnum name="z end" unit="m" val="0.0"/>
        <attnum name="banking start" unit="deg" val="0.0"/>
        <attnum name="banking end" unit="deg" val="12.0"/>
      </section>

      <section name="turn_2">
        <attstr name="type" val="rgt"/>
        <attnum name="radius" unit="m" val="90.0"/>
        <attnum name="arc" unit="deg" val="180.0"/>
        <attnum name="profil steps length" unit="m" val="3.0"/>
        <attstr name="marks" val="50;100"/>
        <attnum name="banking start" unit="deg" val="12.0"/>
        <attnum name="banking end" unit="deg" val="0.0"/>
        <section name="Right Border">
          <attstr name="style" val="curb"/>
          <attstr name="surface" val="curb-5cm-r"/>
          <attnum name="width" unit="m" val="0.8"/>
          <attnum name="height" unit="m" val="0.06"/>
        </section>
      </section>
    </section>
  </section>
</params>
\endcode

Suggested file path:

```text
tracks/road/manual_oval/manual_oval.xml
```

Generate with:

```bash
trackgen -c road -n manual_oval -a
```

Raceline workflow (easy-start variant using global `data/textures/raceline.png`):

```bash
# 1) Generate regular track and terrain output
trackgen -c road -n manual_oval -a

# 2) Generate raceline geometry layer
trackgen -c road -n manual_oval -r

# 3) Required for normal in-game use: combine into final ACC model
#    (same pattern as track readme files)
accc -g tracks/road/manual_oval/manual_oval.acc \
  -l0 tracks/road/manual_oval/manual_oval.ac \
  -l1 tracks/road/manual_oval/manual_oval-trk-raceline.ac \
  -d3 1000 -d2 500 -d1 300 -S 300 -es
```

If you also use a baked shadow layer, a common layout is:

```bash
accc -g tracks/road/manual_oval/manual_oval.acc \
  -l0 tracks/road/manual_oval/manual_oval.ac \
  -l1 tracks/road/manual_oval/manual_oval-shade.ac \
  -l2 tracks/road/manual_oval/manual_oval-trk-raceline.ac \
  -d3 1000 -d2 500 -d1 300 -S 300 -es
```

Raceline shaping keys in `Main Track`:

- `raceline widthscale`: global width scaling for generated raceline strip.
- `raceline int`: safety margin to inside border (meters).
- `raceline ext`: safety margin to outside border (meters).

The example uses `1.5 / 3 / 3` (same style as `g-track-1`) for a clearly visible,
conservative driving line.

Notes:

- If `accc` fails with `stripe: command not found`, your environment is missing the
  external `stripe` tool used by this conversion path.
- On Linux, install `stripe` from source/build tooling so ACC merge can complete.
- Download links (archived original distribution):
  - https://web.archive.org/web/20131004102243/http://www.cs.sunysb.edu/~stripe/stripe.tar.gz
  - https://web.archive.org/web/20131004102245/http://www.cs.sunysb.edu/~stripe/stripe.zip
- In the Windows binary installer `stripe` is already included.

To render the combined model in-game, change:

```xml
<attstr name="3d description" val="manual_oval.ac"/>
```

to:

```xml
<attstr name="3d description" val="manual_oval.acc"/>
```

What this demonstrates:

- Full file structure (`Header`, `Graphic`, `Surfaces`, `Main Track`).
- Closed-loop geometry with two 180-degree turns and long straights.
- Default TORCS surface library via `default-surfaces` entity include.
- Pit entry/exit on 200m straights with flat (`plan`) border sections.
- Pit main section with wall border and 20 pit slots.
- Banking on one turn and descending grade on counter straight.
- `marks` as turn-marker distances on the turns.

\subsection track_manual_fallbacks 11.2 State and fallback rules for omitted fields

The loader reads segments sequentially and keeps state for several fields.
So omitted values are resolved by per-field fallback chains. It is not purely
"always from Main Track" and not purely "always from previous segment".

<table>
  <tr><th>Field</th><th>If omitted in current segment</th><th>Initial source</th></tr>
  <tr><td><code>surface</code> (main segment)</td><td>keeps previous segment surface</td><td><code>Main Track/surface</code></td></tr>
  <tr><td><code>Left/Right Side/start width</code></td><td>defaults to previous side <code>end width</code></td><td><code>Main Track/Left|Right Side/width</code></td></tr>
  <tr><td><code>Left/Right Side/width</code></td><td>defaults to segment <code>start width</code></td><td>derived in segment</td></tr>
  <tr><td><code>Left/Right Side/end width</code></td><td>defaults to segment <code>width</code></td><td>derived in segment</td></tr>
  <tr><td>side/border/barrier <code>surface</code></td><td>keeps previous state</td><td>matching <code>Main Track</code> default subsection</td></tr>
  <tr><td>side/border/barrier <code>style</code></td><td>keeps previous state</td><td>matching <code>Main Track</code> default subsection</td></tr>
  <tr><td><code>profil steps length</code></td><td>uses global value</td><td><code>Main Track/profil steps length</code></td></tr>
  <tr><td>profile start tangents</td><td>continue from previous segment end tangents</td><td><code>0</code> (if no prior data)</td></tr>
  <tr><td><code>z start left/right</code></td><td>continues from previous segment end heights</td><td><code>0</code> at beginning</td></tr>
</table>

Elevation precedence within a segment is separate from state carry-over:

- <code>z start</code> overrides side-specific start heights
- <code>z end</code> overrides side-specific end heights
- if <code>z end</code> is absent and <code>grade</code> is present, end center height is derived from grade
- if banking is present, left/right end heights are recomputed from center height and banking angles

Practical authoring rule:

- segment order matters when fields are omitted
- at transition points (pit entry/start/end/exit, first turn after pits), set key fields explicitly
  to avoid accidental state carry-over

\section track_manual_12 12. Surface system deep dive (physics + rendering)

Surfaces are defined in `Surfaces/<name>`. Segments and side elements reference surface
names via `surface`.

\subsection track_manual_12_1 12.1 Physics properties

Read by track loader (`track4.cpp`) into `tTrackSurface`:

- `friction`
- `rolling resistance`
- `roughness`
- `roughness wavelength`
- `dammage`
- `rebound`

Defaults used if a field is absent are in loader code (`getTrackSurface`).

Meaning at high level:

- `friction`: tire grip potential.
- `rolling resistance`: baseline drag from surface contact.
- `roughness` and `roughness wavelength`: small-scale vertical disturbance model.
- `dammage`: collision damage factor for that material context (the double-m spelling is required in XML).
- `rebound`: restitution-like response.

\subsection track_manual_12_2 12.2 Rendering and texture properties

Used mainly by `trackgen` rendering export paths:

- `texture name`
- `texture type` (`continuous` vs `discrete`)
- `texture link with previous`
- `texture start on boundary`
- `texture size`
- `texture size v` (crossing mapping only; see section 13.4)
- `texture mipmap`
- `bump name`, `bump size`
- `raceline name`
- color fields (`color R1/G1/B1`, `color R2/G2/B2`)

Practical meaning:

- `texture size` controls repetition scale.
- `texture link with previous=yes` keeps texture continuity across segments.
- `texture start on boundary=yes` aligns texture start with segment boundary.
- bump and raceline textures are optional overlays for specific generation modes.

\subsection track_manual_12_3 12.3 Surface authoring tips

- Reuse a small, named library of surfaces (asphalt, curb, grass, gravel, wall).
- Keep physics intent clear first, then tune texture look.
- Avoid too many near-duplicate surfaces unless needed for visual variation.

\subsection track_manual_12_4 12.4 Texture loading order, formats, and transparency quirks

\subsubsection track_manual_texture_search Texture search order

For track model loading, graphics uses this search order:

1. `tracks/<category>/<trackname>`
2. `data/textures`
3. `data/img`
4. `.`

Background loading uses a very similar order but checks `data/img` before
`data/textures`.

Practical implication:

- if the same texture basename exists in multiple places, first match wins
- prefer track-local textures for portable tracks, and avoid ambiguous duplicate names

\subsubsection track_manual_texture_formats Supported texture formats in this path

- `.png`
- `.rgb`

\subsubsection track_manual_mipmaps Mipmap behavior (important quirk)

The renderer applies filename heuristics:

- textures ending with `_n...` disable mipmapping
- textures containing `shadow` disable mipmapping

So `texture mipmap` in surface definitions is a hint, but these filename rules can
still override mipmap behavior.

\subsubsection track_manual_transparency Transparency behavior (filename-triggered)

AC loading enables special alpha-test/blend handling when texture name contains:

- `tree`
- `arbor`
- `trans-`

Additionally, material alpha from AC (`mat->rgb[3]`) is checked:

- if alpha is below `0.99`, geometry is treated as translucent (alpha-test/blend path)
- if alpha is `>= 0.99`, it follows the opaque path unless filename-triggered rules apply

This is commonly used for vegetation and fence-card textures.

Why this convention exists:

- alpha cutout textures with mipmaps can create mixed-alpha fringe/halo artifacts
  (often dark outlines at distance)
- using cutout naming plus `_n` (no mipmaps) is a common TORCS pattern to reduce
  those artifacts

You can see this pattern in stock content (for example e-track-2 tree/arbor textures).

\section track_manual_13 13. Terrain generation chapter (`Graphic/Terrain Generation`)

Key fields:

- `track step`: sampling distance along the track boundary. It also provides the
  lower spacing limit propagated from densely sampled boundary points, capped by
  `border step`.
- `border margin`: terrain extent around track bounds.
- `border step`: coarse terrain-mesh target spacing away from the track.
- `terrain transition`: distance from the track over which target spacing grows
  from the local track-boundary spacing to `border step`.
- `crossing bridge socket gap`: lateral clearance outside each side of a lower
  track at an automatically detected grade-separated crossing; default `0.5 m`.
- `crossing bridge thickness`: minimum vertical thickness below the upper track
  surface at an automatically detected crossing; default `1.0 m`.
- `border height`: external border wall/height behavior.
- `group size`: split size for terrain grouping (performance/scene graph).
- `surface`: terrain base surface material.
- `relief file`: optional AC3D relief constraints.
- `elevation map`: grayscale height map input.
- `maximum altitude`, `minimum altitude`: grayscale-to-height mapping range.

\subsection track_manual_13_1 13.1 Terrain resolution model

Terrain resolution is distance-based on both sides of the closed track loop. This
means the same rule is applied to topological interior terrain, ordinary exterior
terrain, and exterior pockets that are almost surrounded by the track.

For each unconstrained terrain point, `trackgen` finds the closest sampled track
boundary segment. The target spacing is conceptually:

```text
spacing_floor = min(track_step, border_step)
near_track_spacing = max(projected_boundary_spacing, spacing_floor)
factor = clamp(distance_from_track / terrain_transition, 0, 1)
spacing = near_track_spacing
        + max(0, border_step - near_track_spacing) * factor
```

Consequences:

- At the track boundary, terrain retains the local fine spacing established by
  track-boundary sampling and constraints.
- Short boundary edges are retained to follow tight curves, but their small chord
  lengths are not propagated below `min(track step, border step)` into the
  unconstrained terrain.
- When `border step` is larger than the local spacing, the target reaches
  `border step` at `terrain transition` metres from the nearest track boundary.
- Farther away, target spacing remains at the resulting coarse value, normally
  `border step`.
- Narrow gaps stay relatively detailed because every point in the gap remains
  close to at least one track boundary.
- Broad infields and broad exterior pockets become coarser even when they are
  enclosed by track on several sides.
- If `border step` is not larger than the local near-track spacing, the transition
  does not force a finer or coarser value there.

The generated road, side, border, barrier, and collision geometry are not changed
by this parameter. It controls refinement of the surrounding terrain mesh.

\subsection track_manual_13_2 13.2 Defaults and disabling the transition

If `terrain transition` is omitted, it defaults to `border margin`. This provides
a gradual transition over approximately the same scale as the generated outer
terrain extent.

A non-positive value disables distance-based spacing and retains the legacy
EasyMesh spacing interpolation:

```xml
<attnum name="terrain transition" unit="m" val="0"/>
```

Legacy behavior can leave large interior or almost-enclosed exterior regions finer
than necessary because those regions have no nearby coarse boundary from which to
interpolate.

\subsection track_manual_13_3 13.3 Example values and impact

Assume that the effective near-track spacing is `10 m` and `border step` is
`40 m`:

<table>
  <tr><th><code>terrain transition</code></th><th>Result</th><th>Typical impact</th></tr>
  <tr><td><code>50 m</code></td><td>Spacing reaches <code>40 m</code> only <code>50 m</code> from the track; halfway it is about <code>25 m</code>.</td><td>Aggressive polygon reduction and fast generation, but less elevation detail away from the road.</td></tr>
  <tr><td><code>150 m</code></td><td>Spacing is about <code>25 m</code> at <code>75 m</code> and reaches <code>40 m</code> at <code>150 m</code>.</td><td>Balanced starting point for many medium-sized tracks.</td></tr>
  <tr><td><code>300 m</code></td><td>Spacing is about <code>25 m</code> at <code>150 m</code> and reaches <code>40 m</code> at <code>300 m</code>.</td><td>Gradual falloff with more distant elevation detail, more triangles, and longer generation time.</td></tr>
  <tr><td><code>0 m</code></td><td>Distance-based spacing is disabled.</td><td>Legacy output; potentially much denser in large infields and enclosed exterior pockets.</td></tr>
</table>

For the mini example in chapter 11, `track step="8"`, `border step="16"`, and
`terrain transition="140"` produce a gentle transition. If the effective
near-track spacing is approximately `8 m`, the target is approximately `12 m` at
`70 m` from the track and `16 m` at `140 m` or farther away.

Practical tuning:

- Reduce `track step` when the terrain edge does not follow curves or side geometry
  closely enough, or when finer terrain is needed immediately beside the track.
  This increases boundary samples and usually increases mesh size.
- Increase `border step` to reduce far-field triangle density.
- Reduce `terrain transition` to reach the coarse spacing sooner.
- Increase `terrain transition` when distant elevation-map features look too
  faceted or broad height changes need more geometric detail.
- Keep `terrain transition` larger than the near-track safety/detail zone you want
  to preserve.
- Regenerate and inspect both large infields and concave exterior pockets after
  changing these values. A valid mesh can still be visually too coarse for a
  particular elevation map.

How elevation map is used:

- grayscale is sampled over track bounding box plus margin
- darker -> lower, brighter -> higher
- mapped to `[minimum altitude, maximum altitude]`

Important operational detail:

- when `trackgen` is invoked with `-E`, terrain loading path skips elevation-map loading
  and runs export flow (see chapters 14 and code path in `GenerateTerrain`).

\subsection track_manual_13_4 13.4 Automatic grade-separated crossings

`trackgen` automatically generates bridges where the track crosses over itself.
The upper road must be high enough for the bridge underside to clear the lower
road, its sides, borders, and barriers.

Generate the track and surrounding terrain together with:

```text
trackgen -c <category> -n <name> -a
```

The optional dimensions belong in `Graphic/Terrain Generation`:

```xml
<attnum name="crossing bridge socket gap" unit="m" val="0.5"/>
<attnum name="crossing bridge thickness" unit="m" val="1.0"/>
```

- `crossing bridge socket gap`: lateral clearance between each side of the lower
  track and its bridge support wall. Default **0.5 m**; zero is allowed.
- `crossing bridge thickness`: minimum thickness below the upper road surface.
  Default **1.0 m**; must be positive. Increasing it requires more vertical
  separation between the roads.

Both values must be finite; negative gaps and non-positive thicknesses stop
generation with an error.

`trackgen` reports how many crossings it found and how many bridges it generated.
If a bridge is missing, check vertical clearance and the crossing angle: level
crossings, nearly tangent crossings, and unsuitable local geometry may be skipped.

\subsubsection track_manual_crossing_materials Crossing materials

Four optional `Graphic/Terrain Generation` selectors refer to entries in `Surfaces`:

`underside` controls the bottom of the bridge, `side` its outer vertical faces,
`socket` the support walls beside the lower road, and `floor` the strips between
that road and the support walls.

<table>
  <tr><th>Selector</th><th>Default surface / texture</th><th>Nominal U x V size</th></tr>
  <tr><td><code>crossing bridge underside surface</code></td><td><code>bridge-underside</code> / <code>bridge-underside.png</code></td><td>14 x 7 m</td></tr>
  <tr><td><code>crossing bridge side surface</code></td><td><code>bridge-side</code> / <code>bridge-side.png</code></td><td>14 x 7 m</td></tr>
  <tr><td><code>crossing bridge socket surface</code></td><td><code>bridge-socket</code> / <code>bridge-socket.png</code></td><td>14 x 7 m</td></tr>
  <tr><td><code>crossing bridge floor surface</code></td><td><code>bridge-floor</code> / <code>bridge-floor.png</code></td><td>4 x 4 m</td></tr>
</table>

The defaults are supplied by the shared surface catalog. To override a material,
define a surface and select it, for example:

```xml
<section name="Surfaces">
  <section name="my-bridge-concrete">
    <attstr name="texture name" val="my-concrete.png"/>
    <attnum name="texture size" unit="m" val="14"/>
    <attnum name="texture size v" unit="m" val="7"/>
  </section>
</section>
<section name="Graphic">
  <section name="Terrain Generation">
    <attnum name="crossing bridge socket gap" unit="m" val="0.5"/>
    <attnum name="crossing bridge thickness" unit="m" val="1.0"/>
    <attstr name="crossing bridge socket surface" val="my-bridge-concrete"/>
  </section>
</section>
```

Merge these entries into the existing sections and supply `my-concrete.png` in
the track directory or shared texture path. `texture size` is nominal U size;
`texture size v` is nominal V size and defaults to U. Independent V sizing applies
to the crossing mapper, not existing road or terrain mapping. Missing/empty
texture definitions fall back to the existing concrete material, or to the
adjacent lower-track boundary material for floors. An invalid U size uses the
fallback material's positive size; a missing or invalid V size uses U.

\subsubsection track_manual_crossing_mapping Texture mapping and fitting

`texture size` and `texture size v` specify the physical width and height of a
texture tile in metres. Increasing them makes the pattern larger.

- **Underside:** U runs across the upper road and V along it. A narrow bridge
  crops the image; a bridge wider than the U size enlarges the image proportionally
  to fit the width. The texture can repeat along the bridge.
- **Bridge sides and support walls:** U runs horizontally and V vertically.
  Short walls crop the image. Walls taller than the V size enlarge it
  proportionally to fit the height, preserving its aspect ratio. The texture can
  repeat horizontally.
- **Floor strips beside the lower road:** U runs along the lower road and V across
  it. Both directions repeat at the configured sizes.

\section track_manual_14 14. `trackgen -E` elevation export modes

`-E <n>` writes elevation PNG outputs. The mode number selects which image(s) are written.

\subsection track_manual_14_1 14.1 Numeric mode meaning

Supported values:

- `0`: export all four maps (`-elv`, `-elv2`, `-elv3`, `-elv4`) in one run.
- `1`: export continuous grayscale height map from the combined generated scene AC.
- `2`: export continuous grayscale height map from terrain mesh AC (`-msh`).
- `3`: export occupancy-style map from terrain mesh AC (track/terrain footprint dark, outside white).
- `4`: export quantized (stepped) grayscale height map from track AC (`-trk`).

\subsection track_manual_14_2 14.2 Output filenames and behavior

From current implementation:

- mode `1` (or `0`) -> `<name>-elv.png`
- mode `2` (or `0`) -> `<name>-elv2.png`
- mode `3` (or `0`) -> `<name>-elv3.png`
- mode `4` (or `0`) -> `<name>-elv4.png`

Generation mapping in code:

- `-elv.png`: continuous grayscale altitude map from `<name>.ac` (`dispf=1`).
- `-elv2.png`: continuous grayscale altitude map from `<name>-msh.ac` (`dispf=1`).
- `-elv3.png`: coverage mask from `<name>-msh.ac` (`dispf=0`):
  - mesh-hit pixels are dark
  - no-mesh pixels are white
- `-elv4.png`: stepped altitude map from `<name>-trk.ac` (`dispf=2`), using `-H` bins.

Practical reading of the images:

- brighter pixel means higher altitude (for `dispf=1` and `dispf=2` maps)
- `-elv3.png` is best for "where geometry exists" checking, not for exact altitude

\subsection track_manual_14_3 14.3 `-H` interaction

- `-H <nb>` sets quantization count for mode `4`.
- Larger values: finer altitude bands.
- Smaller values: coarser stepped map.

\subsection track_manual_14_4 14.4 Typical use cases

- mode `1`: single-image altitude overview after a generation pass
- mode `2`: inspect terrain-mesh-specific altitude without track-only export path
- mode `3`: create/edit masks and verify terrain coverage extents quickly
- mode `4`: produce banded contour-style map for manual elevation editing workflow
- mode `0`: generate complete diagnostic set for comparison

\section track_manual_15 15. Pits and cameras

\subsection track_manual_pits Pits

`Main Track/Pits` typically uses:

- `entry`, `start`, `end`, `exit`
- `side`
- `speed limit`
- `length`, `width`

`entry`, `start`, `end`, and `exit` refer to segment names. Keep those names unique and stable.

\subsection track_manual_cameras Cameras

Common camera fields:

- `segment`
- `to right`
- `to start`
- `height`
- `fov start`, `fov end` (field of view)

On turns, many tracks use `unit="deg"` for `to start`.

\section track_manual_16 16. Units and numeric interpretation

TORCS parameter handling converts values with `unit=...` to SI internally.

Examples:

- `deg` -> radians
- `%` or `percent` -> divide by 100
- `km`, `cm`, `mm`, `ft`, `in` -> meters

Implications for authors:

- Keep units explicit in XML for readability.
- Understand that final stored values are SI.
- Be careful when comparing raw XML values against debug prints in different layers.

\section track_manual_17 17. Advanced fields and compatibility notes

Advanced per-segment fields used by loader include:

- `env map index`
- `marks`

Notes:

- `env map index` feeds environment mapping selection in graphics modules.
- `marks` defines turn-marker sign distances (for example `25;50;100`) used by
  `trackgen` turn-mark generation in extension build paths.

\section track_manual_18 18. Reference tables

For a compact applied example that uses many keys from these tables together, see
[11.1 Mini end-to-end XML example](@ref track_manual_example).

\subsection track_manual_18_1 18.1 Segment geometry core keys

<table>
  <tr><th>Key</th><th>Scope</th><th>Meaning</th><th>Default/Fallback</th></tr>
  <tr><td><code>type</code></td><td>segment</td><td>geometry kind: <code>str</code> straight, <code>lft</code> left turn, <code>rgt</code> right turn</td><td>required</td></tr>
  <tr><td><code>lg</code></td><td><code>str</code></td><td>straight length</td><td>required for <code>str</code></td></tr>
  <tr><td><code>radius</code></td><td><code>lft/rgt</code></td><td>start radius</td><td>required for <code>lft/rgt</code></td></tr>
  <tr><td><code>end radius</code></td><td><code>lft/rgt</code></td><td>end radius (varying-radius turn)</td><td>defaults to <code>radius</code></td></tr>
  <tr><td><code>arc</code></td><td><code>lft/rgt</code></td><td>turn angle</td><td>required for <code>lft/rgt</code></td></tr>
  <tr><td><code>z start</code></td><td>segment</td><td>center start height</td><td>overrides side start heights</td></tr>
  <tr><td><code>z end</code></td><td>segment</td><td>center end height</td><td>preferred end-height source</td></tr>
  <tr><td><code>z start left/right</code></td><td>segment</td><td>side-specific start heights</td><td>used when <code>z start</code> is absent</td></tr>
  <tr><td><code>z end left/right</code></td><td>segment</td><td>side-specific end heights</td><td>used when <code>z end</code> is absent</td></tr>
  <tr><td><code>grade</code></td><td>segment</td><td>longitudinal slope</td><td>used when <code>z end</code> is absent</td></tr>
  <tr><td><code>banking start/end</code></td><td>segment</td><td>cross-slope angles</td><td>applied to side heights where provided</td></tr>
  <tr><td><code>profil</code></td><td>segment</td><td>vertical interpolation mode</td><td>defaults to <code>spline</code></td></tr>
  <tr><td><code>profil steps</code></td><td>segment</td><td>split count hint</td><td>if <code>1</code>, may derive from step length</td></tr>
  <tr><td><code>profil steps length</code></td><td>segment/main</td><td>target split length</td><td>segment value or main-track fallback</td></tr>
  <tr><td><code>profil ... tangent ...</code></td><td>segment</td><td>spline shape control</td><td>side-specific or generic override</td></tr>
  <tr><td><code>surface</code></td><td>segment</td><td>material/surface name</td><td>previous segment; initially <code>Main Track/surface</code></td></tr>
</table>

\subsection track_manual_18_2 18.2 Side/border/barrier keys

<table>
  <tr><th>Element</th><th>Key set</th><th>Behavior</th></tr>
  <tr><td>side</td><td><code>start width</code>, <code>width</code>, <code>end width</code>, <code>surface</code>, <code>banking type</code></td><td>supports continuous width interpolation within segment</td></tr>
  <tr><td>border</td><td><code>width</code>, <code>height</code>, <code>surface</code>, <code>style</code></td><td>width is constant per authored segment</td></tr>
  <tr><td>barrier</td><td><code>width</code>, <code>height</code>, <code>surface</code>, <code>style</code></td><td>collision boundary layer outside side/border</td></tr>
</table>

Side width fallback chain:

- `start width` <- previous side end width when omitted
- `width` <- `start width` when omitted
- `end width` <- `width` when omitted

Style values seen in loader:

- border `style`: `plan`, `curb`, `wall`
- barrier `style`: `fence`, `wall`

Style behavior notes:

- `curb`: `height` acts as cross-width elevation offset (wheel-height relevant)
- `wall`: `height` defines vertical wall extrusion; used by wall collision solids
- `plan`: flat strip behavior without curb/wall-specific offset semantics

\subsection track_manual_18_3 18.3 Surface keys

<table>
  <tr><th>Key</th><th>Category</th><th>Meaning</th></tr>
  <tr><td><code>friction</code></td><td>physics</td><td>grip coefficient</td></tr>
  <tr><td><code>rolling resistance</code></td><td>physics</td><td>rolling drag factor</td></tr>
  <tr><td><code>roughness</code></td><td>physics</td><td>disturbance amplitude parameter</td></tr>
  <tr><td><code>roughness wavelength</code></td><td>physics</td><td>disturbance spatial wavelength</td></tr>
  <tr><td><code>dammage</code></td><td>physics</td><td>damage factor</td></tr>
  <tr><td><code>rebound</code></td><td>physics</td><td>restitution-like factor</td></tr>
  <tr><td><code>texture name</code></td><td>rendering</td><td>base texture</td></tr>
  <tr><td><code>texture type</code></td><td>rendering</td><td><code>continuous</code> or <code>discrete</code> mapping behavior</td></tr>
  <tr><td><code>texture link with previous</code></td><td>rendering</td><td>continuity across segment boundaries</td></tr>
  <tr><td><code>texture start on boundary</code></td><td>rendering</td><td>reset texture origin at boundaries</td></tr>
  <tr><td><code>texture size</code></td><td>rendering</td><td>texture repeat scale</td></tr>
  <tr><td><code>texture size v</code></td><td>crossing rendering</td><td>independent nominal V size; defaults to <code>texture size</code>; see section 13.4 for fitting rules</td></tr>
  <tr><td><code>texture mipmap</code></td><td>rendering</td><td>mipmap hint value</td></tr>
  <tr><td><code>bump name</code>, <code>bump size</code></td><td>rendering</td><td>bump-texture and scale</td></tr>
  <tr><td><code>raceline name</code></td><td>rendering</td><td>raceline overlay texture</td></tr>
  <tr><td><code>color R1/G1/B1</code>, <code>R2/G2/B2</code></td><td>rendering</td><td>color channels for surface definitions</td></tr>
</table>

\subsection track_manual_18_4 18.4 Terrain generation keys

<table>
  <tr><th>Key</th><th>Meaning</th></tr>
  <tr><td><code>track step</code></td><td>track-boundary sampling step and lower limit for spacing propagated from dense boundary points, capped by <code>border step</code></td></tr>
  <tr><td><code>border margin</code></td><td>terrain extent around track bounds</td></tr>
  <tr><td><code>border step</code></td><td>coarse target spacing away from the track</td></tr>
  <tr><td><code>terrain transition</code></td><td>distance over which terrain spacing grows from near-track spacing to <code>border step</code>; defaults to <code>border margin</code>, non-positive disables it</td></tr>
  <tr><td><code>crossing bridge socket gap</code></td><td>lateral clearance outside lower-track sides; finite and non-negative, default 0.5 m</td></tr>
  <tr><td><code>crossing bridge thickness</code></td><td>minimum thickness below the upper road; finite and positive, default 1.0 m</td></tr>
  <tr><td><code>crossing bridge underside surface</code></td><td>underside material; default <code>bridge-underside</code></td></tr>
  <tr><td><code>crossing bridge side surface</code></td><td>fascia and coplanar portal-extension material; default <code>bridge-side</code></td></tr>
  <tr><td><code>crossing bridge socket surface</code></td><td>socket wall and filler material; default <code>bridge-socket</code></td></tr>
  <tr><td><code>crossing bridge floor surface</code></td><td>lower floor-strip material; default <code>bridge-floor</code></td></tr>
  <tr><td><code>border height</code></td><td>border wall/height parameter</td></tr>
  <tr><td><code>group size</code></td><td>terrain grouping granularity</td></tr>
  <tr><td><code>surface</code></td><td>base terrain material</td></tr>
  <tr><td><code>relief file</code></td><td>optional relief geometry constraints</td></tr>
  <tr><td><code>elevation map</code></td><td>grayscale input map for altitude shaping</td></tr>
  <tr><td><code>maximum altitude</code> / <code>minimum altitude</code></td><td>map grayscale to world-height range</td></tr>
</table>

\subsection track_manual_18_5 18.5 Tool option recap

- `trackgen`: `-a -s -S -b -r -z -B -E -H -i -o`
- `accc`: `+o +shad -g -l0 -l1 -l2 -l3 -d1 -d2 -d3 -S -es -nts`

\section track_manual_19 19. Author checklist

Before generation/testing:

- XML version is 4.
- Segment names used by pits/cameras exist exactly.
- Every turn has `radius` and `arc`.
- Expected profile step count is known for critical segments.
- Side taper is on side sections, not border.
- Surface names referenced by segments exist in `Surfaces`.
- Terrain settings (`track step`, `border step`, `terrain transition`, margins,
  and altitude range) are intentional.
- XML header metadata (`author`, `description`) is present and accurate.
- README contains explicit license and attribution for XML, models, and textures.
- No third-party assets with unknown or incompatible license terms are included.

After changes:

- regenerate with `trackgen`
- run optional `accc` post-processing if needed
- test in-game for seams, banking transitions, runoff feel, pit behavior, and cameras

@author Bernhard Wymann
