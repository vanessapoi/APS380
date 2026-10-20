# Car Setup Workshop {#robot_tutorial_setup_workshop}

This optional companion to [Appendix A](appendix_a.md) explains the other main
setup controls and develops two computed settings. The runnable checkpoint
exposes fuel and rear-wing angle; the extensions below require deliberate C++
changes as well as XML edits.

## 1. Read the allowed setup before tuning

In the source tree, the reference model is
`data/cars/models/car1-stock1/car1-stock1.xml`. The installed data uses
`cars/car1-stock1/car1-stock1.xml`, alongside `categories/stock1.xml`. The model
and category establish which properties may vary. For a running robot, the
incoming `carSettings` handle in `initTrack` is the useful merged reference.

An XML number can carry `min`, `max`, `unit`, and `val`. A string may carry an
`in` list of permitted choices. These declarations describe values and constraints;
they do not grant the driver permission to exceed the incoming reference limits.
An entry with no useful adjustable interval may be fixed by the car model.

To add a numeric car setting to Tutorial A, add a `readCarNumber` call in
`readLayer`, using the correct section and key macros from `car.h`. Rebuild, then
test a sparse XML override. For example, brake pressure uses `SECT_BRKSYST` and
`PRM_BRKPRESS`. That helper checks the reference bounds in internal units and
copies only the accepted number into the returned physical handle.

String settings need a separate path: read the proposed string, check its allowed
choices, set it on the output with `GfParmSetStr`, and retain the final
`GfParmCheckHandle` check. Copy or use borrowed strings while the input handle is
alive. Avoid passing the whole private configuration file through as a car setup.

## 2. What the main controls mean {#robot_tutorial_setup_controls}

### Fuel and aerodynamic balance

Fuel adds mass and determines the available driving distance. A short qualifying
run and a long race need different allowances for warm-up, measurement error,
and refuelling opportunities. The lightest starting car is not useful if it cannot
finish its planned stint.

Wing angle is measured relative to the car. Over the modest range used in Appendix
A, more angle adds aerodynamic loading and drag in the reference physics model.
Front and rear wing changes also alter aerodynamic balance. A rear-wing change
can therefore change both straight-line performance and the way a corner is
negotiated. See [aerodynamic braking](braking_math.md) for the speed-dependent force
model. Keep its approximations distinct from the full simulator.

### Gear ratios

Gear entries are nested, for example `Gearbox/gears/1` and `Gearbox/gears/r`, with
the attribute `ratio`. Reverse uses a negative ratio. Ignoring slip and losses,

\htmlonly
<div class="formula-card"><div class="formula-label">Gear ratio: speed and torque tradeoff</div>
\endhtmlonly
\f[
v=\frac{\omega_e r_w}{|i_g i_f|},\qquad
|T_w|\approx \eta |i_g i_f T_e|.
\f]
\htmlonly
</div>
\endhtmlonly

Here \f$\omega_e\f$ is engine angular speed in rad/s, \f$r_w\f$ rolling radius in
metres, \f$i_g\f$ gear ratio, \f$i_f\f$ final-drive ratio, \f$T_e\f$ engine torque,
and \f$\eta\f$ transmission efficiency. A larger forward ratio increases ideal
wheel torque but reduces road speed at the same engine speed. A shorter first
gear can improve acceleration until traction or rapid shifting becomes the limit.
A taller top gear is only helpful if the engine can pull it against resistance.
Recheck the driver's shift behavior after changing ratios.

### Differential

`Rear Differential/type` selects a model such as `FREE`, `LIMITED SLIP`, or `SPOOL`
when permitted by the car. A free differential allows the driven wheels to turn
at different speeds, but a low-grip wheel can limit useful traction. A limited-slip
model couples the wheels more strongly under its configured conditions. A spool
constrains them to turn together, affecting cornering because the two wheel paths
have different lengths. None is universally best for every surface and controller.

Compare exit acceleration and off-road recovery as well as a smooth solo lap.
Understeer during acceleration is a clue to investigate; it does not by itself
prove that the differential is the sole cause.

### Wheel alignment and ride height

Wheel sections such as `Front Right Wheel` contain `ride height`, `toe`, and
`camber`. Read both left and right definitions before editing them.

- **Toe** is wheel alignment seen from above. It changes the wheel's direction
  relative to the vehicle's forward direction.
- **Camber** is wheel tilt seen from the front or rear. Its effect depends on the
  selected physics implementation. In current simuv2 the grip multiplier includes
  a sine of the static camber and steering-induced correction; “more negative is
  always better” is not a general rule.
- **Ride height** sets the static clearance and participates in the ground-effect
  model. Lower settings can increase modeled aerodynamic loading while leaving
  less room for bumps, body movement, and suspension compression.

Inspect road contact, stability, and edge recovery. Do not substitute a real-car
alignment convention or a remembered sign rule for the definitions in the selected
simulator and car. Angles requested from the API with no output unit are radians;
XML commonly uses degrees.

### Springs, anti-roll bars, and damping

Suspension sections contain `spring`, `suspension course`, `bellcrank`, `packers`,
and the bump/rebound damping parameters. Anti-roll-bar sections couple the left
and right sides of an axle and resist their differential movement.

- A stiffer spring changes load support and response to movement. It does not
  create extra total tyre load out of nothing.
- The bellcrank is a motion ratio. In a simple ideal linkage with ratio \f$b\f$,
  spring deflection is \f$b x_w\f$ and wheel force is \f$b F_s\f$. The effective
  wheel stiffness is therefore \f$k_w=b^2 k_s\f$. Current simuv2 transforms both
  displacement and force; a ratio change can be substantial.
- Suspension course limits travel. Packers limit compression, affecting available
  movement before a hard limit is reached.
- Bump damping resists compression; rebound damping resists extension.
  **Slow and fast refer to damper velocity**, not vehicle speed and not directly
  to the frequency of an oscillation. Braking, kerbs, and bumps excite different
  motions, but they do not select a damping regime by name.
- Anti-roll stiffness changes how an axle responds to unequal wheel movement and
  redistributes load between its tyres. Its effect on grip and balance depends
  on the tyre/load model and the rest of the setup.

Change one family at a time, testing both a smooth corner and a bumpy section.
Keep enough travel for the actual track. A faster best lap accompanied by repeated
loss of road contact is a poor basis for a reliable race setup.

## 3. A computed starting-fuel setting {#robot_tutorial_setup_fuel}

Instead of writing a fixed starting amount, you can use a configured consumption
estimate and the planned driving distance. For a lap-based exercise:

\htmlonly
<div class="formula-card"><div class="formula-label">Starting fuel for a planned stint</div>
\endhtmlonly
\f[
\begin{aligned}
F_{\rm wanted}&=(N+N_{\rm allowance})\widehat f+F_{\rm reserve},\\
F_{\rm start}&=\operatorname{clamp}
 (F_{\rm wanted},F_{\min},\min(F_{\max},F_{\rm tank})).
\end{aligned}
\f]
\htmlonly
</div>
\endhtmlonly

\f$N\f$ is the number of laps planned before refuelling or finishing;
\f$N_{\rm allowance}\f$ accounts for an extra distance allowance;
\f$\widehat f\f$ is litres per lap; \f$F_{\rm reserve}\f$ is litres. Obtain
\f$F_{\min}\f$, \f$F_{\max}\f$, and tank capacity from the current car reference.
Check that the allowable interval is valid before clamping.

For six planned laps, one additional lap, 1.5 l/lap, and a 0.5 l reserve, the
estimate is 11 l. If the result exceeds tank capacity, clamping does not make the
race feasible without a stop: it identifies the need for a stint plan. Timed races
need an estimated distance or duration model rather than blindly using a lap count.

To implement this extension, compute the amount during `initTrack`, then set
`SECT_CAR/PRM_FUEL` on the output handle with `GfParmSetNum(..., "l", ...)`.
Decide and document whether this computed policy overrides an explicit XML fuel
value; do not leave two competing assignments with accidental precedence. Keep
the existing no-side-pits policy in mind.

The supplied checkpoint deliberately uses a direct fuel override for the first
exercise. Its `fuel per lap` private setting feeds the **pit strategy's fallback**;
it does not automatically compute starting fuel. Once driving begins, Chapter 6's
measured consumption is the better basis for updating the plan.

## 4. Brake pressure from torque capacity {#robot_tutorial_setup_brakes}

This develops the setup idea introduced in [Wheel Control](wheel_control.md).
It is an optional analytical experiment, not an automatic feature of Tutorial A.
The equations below describe **current simuv2's ordinary service-brake path**.

Let \f$u\in[0,1]\f$ be the brake command, \f$P_{\max}\f$ the `max pressure`
setting in pascals, and \f$q\f$ the effective front pressure fraction. With
no extra brake-balance command, \f$q\f$ is the configured
`front-rear brake repartition`. Each front wheel receives
\f$P_f=uP_{\max}q\f$; each rear wheel receives
\f$P_r=uP_{\max}(1-q)\f$.

For wheel \f$i\f$, simuv2 constructs the coefficient and brake torque as

\htmlonly
<div class="formula-card"><div class="formula-label">Brake hardware: pressure to torque</div>
\endhtmlonly
\f[
C_i=\frac{d_i}{2}A_i\mu_{b,i},\qquad
T_{b,i}=C_i P_i.
\f]
\htmlonly
</div>
\endhtmlonly

\f$d_i\f$ is `disk diameter` in metres, \f$A_i\f$ the modeled `piston area` in
square metres, and \f$\mu_{b,i}\f$ brake friction. Use the simulator coefficient
as written; do not add an assumed extra pair of pads or caliper multiplier.
\f$C_i\f$ has units of cubic metres, and \f$C_iP_i\f$ has units N·m.

Ignoring wheel rotational dynamics, a longitudinal contact force \f$F_{x,i}\f$
requires approximately \f$T_i=r_iF_{x,i}\f$, with rolling radius \f$r_i\f$.
For a simple straight-line grip estimate \f$|F_{x,i}|\leq\mu_{t,i}F_{z,i}\f$,

\htmlonly
<div class="formula-card"><div class="formula-label">Estimated first-wheel force capacity</div>
\endhtmlonly
\f[
P_{\max}\lesssim
\min_i\frac{\mu_{t,i}F_{z,i}r_i}{u C_i q_i},
\qquad
q_i=\begin{cases}q&\text{front},\\1-q&\text{rear}.\end{cases}
\f]
\htmlonly
</div>
\endhtmlonly

Here \f$\mu_{t,i}\f$ is an effective tyre/surface grip estimate, distinct from
brake friction; \f$F_{z,i}\f$ is normal load in newtons. Require positive radii,
coefficients, loads, and \f$u q_i\f$ before dividing. This bound estimates the
first wheel likely to reach its modeled force capacity at the chosen command.
It is not a complete locked-wheel criterion.

For example, take \f$F_z=4000\ \mathrm N\f$, \f$\mu_t=1\f$,
\f$r=0.33\ \mathrm m\f$, \f$d=0.38\ \mathrm m\f$,
\f$A=0.002\ \mathrm{m^2}\f$, \f$\mu_b=0.3\f$, \f$q=0.66\f$, and \f$u=1\f$.
Then \f$C=0.000114\ \mathrm{m^3}\f$, and this front wheel gives approximately
\f$P_{\max}=17.54\ \mathrm{MPa}=17544\ \mathrm{kPa}\f$.
These are illustrative inputs, not a measured optimum for the reference car.

### Why the estimate changes while driving

For a level, straight-line approximation with mass \f$m\f$, wheelbase \f$\ell\f$,
centre-of-mass height \f$h\f$, static front load fraction \f$\lambda_f\f$, and
positive braking deceleration \f$a\f$:

\htmlonly
<div class="formula-card"><div class="formula-label">Braking transfers load toward the front axle</div>
\endhtmlonly
\f[
\begin{aligned}
\Delta F_z&=\frac{mah}{\ell},\\
F_{z,f}&=\lambda_f mg+\Delta F_z+D_f,\\
F_{z,r}&=(1-\lambda_f)mg-\Delta F_z+D_r.
\end{aligned}
\f]
\htmlonly
</div>
\endhtmlonly

\f$D_f,D_r\f$ are simplified front/rear aerodynamic loads. Divide axle loads
between the two wheels only when the situation is sufficiently symmetric. Actual
loads change with banking, bumps, body motion, aero balance, and cornering.
Cornering also uses some of the tyre's available force; a friction-circle
approximation would replace the full longitudinal allowance by
\f$\sqrt{(\mu_t F_z)^2-F_y^2}\f$ where the radicand is nonnegative.

The command matters as much as the pressure setting. The normal speed controller
caps its brake request below 1, while other states can command stronger braking.
Do not inflate pressure to compensate for one controller cap without checking
recovery, pit stopping, and the full-brake case. ABS modulates the command; it does
not change the configured hardware coefficient or make every pressure equally useful.

### Turn it into an experiment

1. Read the effective brake, wheel, mass, and balance parameters; include inherited
   category defaults rather than inspecting one XML file in isolation.
2. Compute a documented operating-point estimate. Check units and positive
   denominators; then compare it with the car's legal pressure interval.
3. Add the pressure setting to the whitelist and preserve a known baseline.
4. Run repeated straight braking tests at the same initial speed and load. Observe
   stopping distance, wheel slip, ABS action, and directional stability.
5. Repeat with changed fuel and with turning. Retain a setting only after the
   complete driver still stops correctly in its other modes.

Reducing pressure can reduce excessive slip but also lengthen stopping distance.
Moving the balance rearward can help one operating point and destabilize another.
The estimate is a starting hypothesis to test, not a universal automatic setup.

## 5. Session-specific setups and systematic tuning {#robot_tutorial_setup_sessions}

A possible extension is **defaults → track → session-specific track**. Select a
session name from `situation->_raceType` using `RM_TYPE_PRACTICE`,
`RM_TYPE_QUALIF`, and `RM_TYPE_RACE`, then load a third layer such as
`drivers/tutoriala/race/g-track-1.xml`. Define an explicit fallback for other
session types. Add every new directory/file to the Linux and Windows installation
rules. A directory name has no effect until your loader uses it.

Qualifying may favour short-run pace with a smaller fuel allowance. A race setup
must also finish its stints, handle traffic and recovery, and avoid accumulating
damage. Driver skill level and the selected physics module affect comparisons;
record them and keep them fixed. Multiple driver indices and independent state
are covered in [Appendix C](appendix_c.md).

For systematic tuning, start from a baseline, try a smaller and a larger value,
and repeat the promising direction. Recheck nearby values before moving to another
parameter. This is a local search, not proof of a global optimum: settings interact,
and changing the controller can invalidate a previously good setup. Record flying
laps, road-edge behavior, recovery, fuel use, and damage. Finish with a full-race
test and restore the baseline if the supposed gain does not repeat.

Return to [Appendix A](appendix_a.md).
