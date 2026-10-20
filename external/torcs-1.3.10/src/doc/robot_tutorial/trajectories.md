# Paths, Speed and Other Steering Approaches {#robot_tutorial_trajectories}

This optional companion to [Chapter 4](chapter_4.md) connects its
faster-cornering experiment with broader ideas about trajectory
planning. A **path** describes where to travel. A **speed profile** describes
how fast to travel along it. Together they determine motion over time.

## Which radius belongs in the speed formula? {#robot_tutorial_paths_radius}

Chapter 3 uses \f$v=\sqrt{\mu gR}\f$ as a basic steady-cornering estimate.
The R in that formula is the radius of the **car's path**, not automatically
the radius stored in a track segment.

A driver may use the width of a bend to follow a shallower path, especially
through a small change of direction. But its path must connect to the entry
and exit, fit the road with room for the car, and respect the next bend. An
outside track edge radius alone does not establish any of those facts.

![Different paths can have different radii within the same road](images/path-radius.svg)

Our steering chooses centerline targets, but the resulting driven path depends
on lookahead, speed, steering response, and tyre forces. Increasing a radius
inside the speed model does not make the car follow that radius.

## A short-turn speed heuristic {#robot_tutorial_paths_heuristic}

One way to estimate a more generous corner radius is to start with the outside
radius and enlarge it for small-angle bends. Accumulate the arcs of consecutive
segments turning in the same direction, so splitting a bend into several pieces
does not automatically make each piece a short turn.

Writing that idea explicitly, with road width w and accumulated angle A:

\f[ f=\frac{A}{\pi/2},\qquad
R_{\mathrm{estimate}}=\frac{R+w/2}{\sqrt{f}}.\f]

The angle is normalized by a quarter-turn, so f is dimensionless. Small f
increases the estimated radius and therefore the proposed speed. As the car
approaches the end of a bend, a smaller remaining angle can encourage earlier
acceleration. This is an empirical idea, not a derivation of an optimal path.

### The bounded experiment in Tutorial 4

`USE_SHORT_TURN_HEURISTIC` in `speed4.cpp` selects `experimentalRadius`:

1. For the current segment, subtract the angle already travelled. For future
   segments, start at their beginning.
2. Add positive arcs while the segments continue turning the same way, stopping
   at a quarter-turn or the bounded segment-count limit.
3. Clamp f to [0.05, 1].
4. Limit the estimated radius to 1.5 times the local centerline radius:

\htmlonly
<div class="formula-card"><div class="formula-label">Bounded effective-radius experiment</div>
\endhtmlonly

\f[ R_{\mathrm{experiment}}=
\min\left(1.5R,\frac{R+w/2}{\sqrt{\operatorname{clamp}(f,0.05,1)}}\right).\f]

Both bounds are teaching choices. Neither proves that a feasible trajectory exists.
\htmlonly
</div>
\endhtmlonly

For R = 40 m, w = 10 m, and A = π/4, the unbounded estimate is about 63.64 m.
The experiment limits it to 60 m. Without aerodynamics this can raise the local
model speed by at most \f$\sqrt{1.5}\approx1.225\f$ before the existing margin
and speed cap. The same ratio is **not** a universal bound with downforce:
the aerodynamic denominator also changes with radius. The absolute speed cap
still applies.

The smaller-angle limit prevents division by zero, and the loop bound prevents
an endless search on a circular list. The estimate still has substantial
limitations: it groups bends by turn direction, not by equal radius; it does
not check the available swept corridor; and it does not model how one corner's
exit position affects the next corner's entry. The normal braking lookahead
continues to check the speed targets of subsequent segments.

**Experiment:** keep the 8 m / 0.33 s steering settings and Chapter 3's speed
settings, then compare the switch off and on. Record lap times, road-edge
excursions, and damage on both CG Speedway number 1 and E-Track 2. Watch whether
the higher corner-speed target leaves enough room to exit each bend and approach
the next one.

## Why merely cutting throttle is insufficient {#robot_tutorial_paths_filter}

Consider a simple position-based throttle filter: cut throttle when the car is
more than a quarter of the road width away from the centerline on a straight
or on the outside of a bend. Permit acceleration on the inside and bypass the
filter at low speed. Could this restore stability after raising corner speed?

There are useful ideas here: position should influence driving, inside and
outside have different geometry, and a slow car needs enough power to rejoin.
There are also important limits:

- A center-position threshold ignores the car's width and heading.
- Lifting is not the same as requesting enough braking for the available space.
- Being on the inside is not permission to accelerate indefinitely. The car
  may already be cutting across the inside edge, or may lack enough tyre force
  to turn onto its intended path.

In a ground-fixed view, inward tyre force changes the velocity direction. If
there is too little inward force, the car turns less sharply than desired and
can run wide. An outward “centrifugal force” belongs to a rotating-frame
description; it is not an extra external force we can rely on to place the car
back on the centerline.

Tutorial 4 therefore uses the signed road clearance of four corners and lowers
the speed target on **either** side. It interpolates from the planner's target
to at most 5 m/s across the last metre of clearance. The existing pedal controller
then decides between acceleration, coasting, and braking. This preserves motion
at low speed while allowing braking when lifting alone would be insufficient.
It remains reactive, and its current-corner samples are not a swept-path proof.

## Heading-error steering and pure pursuit {#robot_tutorial_paths_pursuit}

Our implementation requests a nominal steering angle equal to the target's
heading error α, then divides by the steering lock to form a command. It is
easy to follow, but it has no wheelbase in the calculation.

A geometric pure-pursuit controller instead fits a circle through a target
relative to a chosen vehicle reference point, usually the rear axle center.
Let D be the **straight-line distance** from that reference point to the target,
α its direction relative to the vehicle, and b the wheelbase. For an ideal
no-slip bicycle model:

\f[ \kappa=\frac{2\sin\alpha}{D},\qquad
\delta=\arctan(b\kappa).\f]

κ is signed curvature in 1/m and δ is the front-wheel steering angle. Notice
that D is not the centerline lookahead L used to select the target. A complete
implementation must also use a consistent axle reference, map δ to the actual
steering controls, and consider saturation and dynamic slip.

This is a useful next experiment, but changing just the formula while leaving
the reference point unexplained would obscure its assumptions. The supplied
example uses the heading-error method explained in Chapter 4.

## What makes a trajectory good? {#robot_tutorial_paths_approaches}

### Heuristic paths

Rules such as “aim farther ahead when faster” or “allow a larger radius for a
short bend” are quick to implement and easy to experiment with. Improvements
on one track can expose problems on another. Test tight bends, alternating
directions, narrow roads, and changes of grip rather than selecting only the
track where a rule works best.

### Geometric curvature smoothing

Rémi Coulom's K1999 driver is an example of geometric curvature smoothing.
Such approaches adjust a sequence of path
points within road boundaries to reduce abrupt or large curvature demands.
They can provide a useful candidate racing line efficiently.

Geometry alone does not include the car's power, braking ability, downforce,
or grip variation. A path with gentle curvature is not necessarily the fastest:
it may be longer, compromise a critical exit, or place acceleration where the
tyres are already working hard to turn.

### Splines

A spline provides a smooth curve through or near chosen control points. A
simple construction starts with a few promising points, checks where the curve
leaves the road, and inserts or adjusts points there. Smoothness is helpful,
but a spline can overshoot between control points. Check the continuous curve
or sufficiently bounded subdivisions, with room for the vehicle's footprint;
checking only the control points misses the very problem being corrected.

### Clothoids and circular arcs

A circular arc has constant curvature. Clothoids vary curvature linearly with
distance, making them useful for transitions between straights and curves.
Fitting arcs or clothoids within the road can produce understandable paths, but
joining them requires attention to tangent direction, curvature continuity,
available width, and the following turn. A collection of large circles that
individually fit does not automatically form one drivable lap.

### Vehicle-dependent minimum-time planning

For a path parameterized by distance s and a positive speed profile v(s), lap
time is:

\f[ t_{\mathrm{lap}}=\int_0^{S}\frac{1}{v(s)}\,ds.\f]

Minimizing this quantity requires constraints: road boundaries and vehicle
footprint, lateral grip, longitudinal acceleration and braking, steering,
and an appropriate vehicle model. Downforce, load transfer, or transient tyre
behavior may matter depending on the intended accuracy. Modern numerical
optimization can solve discretized versions, but the result depends on the
model, resolution, initialization, and solver convergence. A local solution
is not automatically a globally optimal racing line.

Computational difficulty depends on the exact planning problem. An inexpensive
geometric candidate can be a useful starting point for a more demanding
path-and-speed optimization with explicit vehicle constraints.

### Learning-based approaches

TORCS also provides a setting for learning steering, speed, or path decisions.
Define what the agent observes, which controls it chooses, and how success is
measured. A reward based only on progress can encourage cutting corners or
accepting damage. Compare with this simple driver and evaluate on tracks and
conditions not used for training. Report road departures, completed laps,
damage, and consistency alongside lap time.

For a class project, comparing two modest, well-explained approaches on the
same conditions is more informative than claiming an “optimal” driver without
stating its assumptions.

Return to [Chapter 4](chapter_4.md), or work through the [geometry](geometry.md).
You can also [ask a question or share an experiment](@ref robot_tutorial_feedback).
