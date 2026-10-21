# APS380 — offline telemetry → cell current

The original Milestone 1 demand pipeline is software only. The established architecture assigns instrument communication and SOC/SOP to Python on the PC; ESP32 provides sensing and local supervision. No serial, UDP, PSU or electronic-load control is implemented. The original demo CSV is synthetic; subsequent TORCS recordings and their limitations are documented separately.

An offline candidate cell SOC workflow is now available: [cell SOC setup and replay](../docs/cell-soc.md). It uses a source-labeled EVE OCV reference and measured-net-current input schema, with a clearly marked mock example. Its physical accuracy remains unvalidated. The workflow below still describes the original vehicle-demand/current-scaling model.

## Run

```bash
cd aps380_torcs_starter
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python make_demo_data.py   # optional: bundled synthetic CSV already exists
python run.py
python tests.py
```

`run.py` works from any directory. Default paths are relative to the script. Explicit paths are relative to your working directory:

```bash
python run.py --input data/recorded_lap.csv --config config.json --output-dir output/lap
```

Outputs are `current_profile.csv`, `current_profile.png` and `model_parameters.json` (the effective configuration). Without matplotlib, CSV and parameters are still produced. Plot panels show speed, wheel/battery power and raw/limited current with limit lines.

## Input and code boundaries

CSV requires `time_s` (seconds, nonnegative and strictly increasing), `speed_mps` (forward speed in m/s, nonnegative), `throttle` and `brake` (both 0–1). At least one sample is required; missing, nonnumeric, nonfinite and out-of-range values are rejected with row context. Extra columns are ignored. Pedals are diagnostics, not power inputs: speed dynamics determine demand.

Normalize future TORCS recordings to this schema after verifying the exporter’s units and timestamp convention. Convert km/h to m/s by dividing by 3.6 if appropriate. No specific TORCS exporter or API is assumed. Reverse driving is unsupported.

- `ev_model.py`: vehicle parameters and longitudinal mechanical/electrical power.
- `cell_scaling.py`: equivalent-energy scaling and independent signed current limits.
- `battery_model.py`: telemetry validation, interval calculations and CSV output.
- `run.py`: JSON configuration, command-line entry point and plots.

## Equations and timing

For each sample after the first:

```
dt = t[i] - t[i-1]
a = (v[i] - v[i-1]) / dt
v_bar = (v[i] + v[i-1]) / 2
F = m*a + m*g*Crr + 0.5*rho*CdA*v_bar^2
P_wheel = F*v_bar
P_regen_mechanical = min(max(-P_wheel, 0)*regen_fraction, regen_cap)
P_battery = P_wheel/drive_efficiency + P_aux       if P_wheel >= 0
P_battery = -P_regen_mechanical*regen_efficiency + P_aux otherwise
```

Mass is kg, forces N, acceleration m/s², drag area m², air density kg/m³ and all powers W. The non-recovered negative wheel power is assigned to friction brakes. Road drag and rolling resistance already dissipate energy and are not recoverable. Deceleration does not necessarily imply battery charging.

Each derived power/current at timestamp `t[i]` represents the preceding interval, not instantaneous endpoint demand. The inertial energy is exactly `m*(v[i]^2-v[i-1]^2)/2`; road-load energy uses interval-mean speed as an approximation. The first sample has `interval_s=0`, assumed zero acceleration and a steady-state estimate at its recorded speed; exclude it from energy integration. At rest traction power is zero but configured auxiliary power remains.

## Scaling and sign

```
E_cell_Wh = nominal_voltage_V * capacity_Ah
scale = E_cell_Wh / equivalent_pack_energy_Wh
P_cell_requested = P_battery * scale
I_raw = P_cell_requested / nominal_voltage_V
I_command = clamp(I_raw, -charge_limit_A, discharge_limit_A)
P_cell_command = nominal_voltage_V * I_command
```

Positive power/current means discharge; negative means charge. Equivalent-energy scaling approximates each cell’s share of a homogeneous pack and preserves nominal C-rate: `I_raw/capacity_Ah = P_battery/equivalent_pack_energy_Wh`. It is a modelling choice, not a claim about a verified pack topology. Current limits do not determine the scale.

The example 75 kWh pack and 3 Ah, 3.6 V cell imply scale 0.000144 (about 6944 equivalent cells); 100 kW maps to 14.4 W and 4 A before limiting. This corrects the original arbitrary 160 kW-to-4 A normalization. Clipping distorts the waveform and energy; the CSV retains raw demand, limited demand and `command_saturated` to expose it. No vehicle feedback is applied in this offline milestone.

## Configuration and limitations

Edit `config.json`. All defaults are illustrative engineering assumptions, not measured or approved settings:

| Parameter | Example | Rationale / limitation |
| --- | ---: | --- |
| Vehicle mass | 2100 kg | representative heavy EV, not a calibrated vehicle |
| Drag area | 0.65 m² | combined Cd × frontal area |
| Rolling coefficient | 0.012 | constant road/tire approximation |
| Air density / gravity | 1.225 kg/m³ / 9.81 m/s² | reference atmosphere / gravity |
| Drive / regen efficiencies | 0.88 / 0.65 | constant conversion approximations |
| Regen fraction / mechanical cap | 0.7 / 60 kW | assumed braking allocation and motor limit |
| Auxiliary power | 300 W | constant electrical accessory demand |
| Pack energy | 75000 Wh | nominal equivalent-energy scale |
| Cell voltage / capacity | 3.6 V / 3 Ah | nominal single-cell approximation |
| Discharge / charge limits | 4 A / 1 A | offline clipping examples only, not safe cell ratings |

The model assumes flat road, still air and forward motion. It omits grade, rotating inertia, cornering/tire slip losses, motor efficiency maps, actual brake blending and low-speed regen fade. Regen fraction is fixed, not inferred from the brake pedal. No propulsion power cap is applied: impossible acceleration telemetry can yield impossible raw vehicle demand, which should be reviewed rather than silently rewritten. Sparse/noisy speed data can produce large acceleration errors; filtering and sampling validation need calibration against real recordings. Irregular positive intervals are supported but gaps are not reconstructed.

In this legacy demand/scaling workflow, nominal voltage is fixed; there is no electrochemical model, measured voltage, SOC/SOP, temperature derating or verified hardware operating envelope. Energy scaling is approximate, and does not reproduce cell aging or transient voltage behavior. The separate candidate SOC replay uses net-cell-measurement inputs, never this requested current or eLoad branch current; live ESP32 acquisition remains pending. Approved current limits and independent PCB protections require separate cell-specific bench validation. No PSU bias mapping is part of this milestone.

## Validation

`python tests.py` uses standard-library unittest. It checks irregular-time acceleration energy, cruising road load, capped regeneration/friction allocation, passive coasting, rest and first-sample behavior, scaling independent of limits, both current limits, invalid parameters, malformed CSV/direct telemetry and the synthetic profile. These are equation and input-contract tests, not physical model calibration.

## Genuine TORCS sample integration

The original `data/Torcs_Sample_Data.csv` comes from [CognitiaAI/TORCS-Self-Driving-Agent](https://github.com/CognitiaAI/TORCS-Self-Driving-Agent), whose README describes Ahoora-agent-generated driving data. This is genuine simulator telemetry, not a G29 human-driver recording, and not measured EV battery power. The repository reports preprocessing its training data, but this sample's raw sensor ranges and physical distance consistency support interpreting it as raw SCR telemetry, not standardized model features.

The [SCR competition software manual](https://usermanual.wiki/Document/SCRMANUAL.2071538563.pdf), sensor/actuator tables, defines `curLapTime` in seconds, longitudinal `speedX` in km/h, and `accel`/`brake` as 0–1 virtual pedals. `accel` is not acceleration in m/s². `torcs_adapter.py` maps these fields to our schema, converting only speed by `/3.6`. Time remains the recorded lap clock, including its fractional starting value.

```bash
python torcs_adapter.py
python run.py --input data/torcs_normalized/segment_01.csv --output-dir output/torcs/segment_01
python run.py --input data/torcs_normalized/segment_02.csv --output-dir output/torcs/segment_02
python run.py --input data/torcs_normalized/segment_03.csv --output-dir output/torcs/segment_03
python tests.py
```

The adapter is separate from all EV/cell equations. It exports individual segments and `data/torcs_normalized/inspection.json`, which records original CSV row numbers (header is row 1), excluded rows, boundary diagnostics, interval counts and the original SHA-256. No downloads occur during normal processing, and the input file is never written. A downloaded copy was compared byte-for-byte to the existing local original on 2026-10-08; they matched:

```
83eee7c7ccca37ef009976ddebb0307b41c127bca8ee778bbc4a49d92e728e85
```

### Continuity policy

The adapter breaks segments at non-increasing lap time, track changes, decreasing cumulative race distance, excluded samples and positive timestamp gaps exceeding `--max-gap-s` (default 0.03 s). The threshold conservatively admits the observed 20/22 ms sampling, rather than assuming uniform sampling. It is configurable for other verified recordings. Optional diagnostic fields are used when present; four-column recordings cannot establish session identity beyond their available clock evidence.

Negative time and negative longitudinal speed are excluded and reported, never clamped. Other malformed/nonfinite numeric data and invalid pedals cause an error. Segments are never concatenated, re-timed or interpolated. Each segment starts a new derivative chain; its first power estimate assumes zero acceleration as in the existing pipeline. Adjacent source rows within each exported segment remain adjacent: no derivatives bridge an omitted row.

### Inspection of this sample

- 5,000 source samples, all labelled `CGSpeedwayNumber1`; no observed track changes, duplicate times or decreases in `distRaced`.
- 49 samples have negative pre-start lap times. 50 have negative longitudinal speed (magnitude at most 0.00803 km/h). Their union is the first 50 samples, all excluded because the current model supports nonnegative time and forward motion.
- Positive clock increments: 2,140 × 20 ms, 2,854 × 22 ms, one each near 19.999 ms and 22.002 ms (serialization precision), and one 40 ms interval in the excluded startup region. No retained within-segment gaps exceed 30 ms.
- Lap-clock resets at source rows 2203 and 4185 coincide with `distFromStart` wrapping to near zero, continued cumulative race distance, and `lastLapTime` updating to 45.058 and 41.716 s. These support two lap crossings rather than race restarts. Exported segments represent the initial lap portion, the next lap portion and a truncated third lap. No timing across either boundary is reconstructed.
- Integrating `speedX/3.6` gives approximately 2,040, 2,015 and 939 m across the three retained segments versus cumulative-distance changes of 2,082, 2,056 and 954 m. Agreement within about 2% supports the speed-unit interpretation; longitudinal velocity, path curvature/lateral motion and sensor timing can differ from race-distance accumulation. Exact sensor/action alignment and the precise collection configuration are not independently established.

| Segment | Samples | Recorded time range (s) | Duration (s) | Limited samples |
| --- | ---: | --- | ---: | ---: |
| 01 | 2151 | 0.038–45.046 | 45.008 | 2007 |
| 02 | 1982 | 0.00800134–41.698 | 41.690 | 1897 |
| 03 | 817 | 0.00399792–17.956 | 17.952 | 775 |

Outputs for each segment are in `output/torcs/segment_XX/`: the existing CSV, plot and configuration snapshot. Synthetic outputs remain in their original locations.

### Interpretation of the real-data outputs

Speed reaches 244.229 km/h. Applying the existing illustrative EV configuration yields peak positive battery demand of about 767 kW, raw requested current up to 30.67 A, and limited current between −1 and +4 A. 4,679/4,950 samples (94.5%) saturate. The existing mechanical regen cap yields a maximum net battery charging demand of 38.7 kW, or −1.548 A before the cell charge limit.

Finite-difference acceleration ranges approximately −34 to +15.27 m/s². Braking fluctuations and brief speed discontinuities can create extreme inferred wheel power. `speedX` is body-axis longitudinal velocity, so changes during steering/slip need not equal changes in total vehicle speed. The flat-road model omits those effects and treats this racing car trajectory as demand for our assumed heavy EV; it does not identify the original car's mass, engine power, grade or drivetrain. No filtering, propulsion cap or parameter retuning was introduced to conceal the mismatch.

These plots demonstrate real-source ingestion and expose model/scaling limitations. They are not a calibrated EV profile or an approved hardware command trace. Next, justify a representative vehicle/cell configuration, evaluate velocity conditioning against raw data, and quantify clipping before selecting a usable experiment. Do not infer SOC or measured current from these commands. Hardware communications remain absent.

Adapter tests cover unit conversion, unchanged recorded clocks, lap/duplicate/gap/session boundaries, exclusions without derivative bridging, malformed source data and byte preservation of this original. The full suite now has 15 tests.

## Source-informed comparison experiment

Run `python compare_profiles.py` to generate four cases for each independent segment:

1. Existing illustrative heavy-EV configuration, raw speed.
2. `config_torcs.json`, raw speed.
3. Source-informed configuration, speed smoothed over 0.2 s.
4. The same smoothed profile with explicit experiment scale 0.2.

Results are in `output/torcs_comparison/`: three comparison plots, `summary.csv`, and per-segment/per-case profiles and parameter snapshots. Use `--window-s`, `--experiment-scale` and `--output-dir` to run sensitivity comparisons. This script requires matplotlib. Baseline inputs and outputs are unchanged.

`config_torcs.json` uses 1150 kg and body drag area 0.35 × 1.92 = 0.672 m² from the repository's [car1-trb1 configuration](https://github.com/CognitiaAI/TORCS-Self-Driving-Agent/blob/master/torcs_server/cars/car1-trb1/car1-trb1.xml). The [SCR driver configuration](https://github.com/CognitiaAI/TORCS-Self-Driving-Agent/blob/master/torcs_server/drivers/scr_server/scr_server.xml) selects this car. It is a likely association, not verified sample-specific metadata. The model describes a simplified electric equivalent: fuel mass, wing drag/downforce and actual simulator setup are omitted; efficiency, auxiliaries, rolling coefficient, regeneration and 75 kWh equivalent battery remain illustrative assumptions. These values do not reconstruct the original combustion-car drivetrain.

`telemetry_conditioning.py` applies a local linear speed fit using the actual timestamps inside a centered window. Window width is in seconds, not samples. Boundary windows are truncated; predicted negative speeds are explicitly bounded to zero. No timestamps, pedals or source files change. Each segment is conditioned independently, without resampling or filling missing data. This offline filter uses future samples and is not a proposed live-controller implementation. The comparison exports the conditioned speed so its effects can be audited against the raw case.

All cell configurations now optionally accept `experiment_scale` (default 1). The power scaling equation becomes:

```
P_cell_requested = P_vehicle * (V_nominal * capacity_Ah / pack_energy_Wh) * experiment_scale
```

At 1, nominal C-rate equivalence remains. At 0.2, requested cell current and power are one fifth of the energy-equivalent values; C-rate equivalence is deliberately sacrificed to retain more waveform detail at bench scale. This factor is an offline experiment choice, not a larger fictional pack or an approved operating envelope. It does not change vehicle power or increase current limits. Ordinary `run.py` accepts this field through its existing cell configuration; smoothing is only applied by the comparison script.

For this dataset, source-informed raw peak current is 17.03 A. With the 0.2 s window it is 14.93 A; smoothed negative acceleration still reaches about −21.84 m/s². Smoothing therefore reduces spikes without establishing physical realism. Source-informed smoothing alone still clips 85.7–89.6% of samples by segment. Applying the additional 0.2 scale produces peak demand around 2.99 A and no clipping with the example limits. This is a useful demonstration waveform, not proof of calibrated power or cell suitability.

`summary.csv` reports peak power/current, acceleration range, sample/time clipping fractions, time-weighted commanded RMS current, and requested/commanded discharge/charge energies separately. Energies sum interval power × actual dt; zero-duration first samples contribute nothing. There is no energy integration across lap boundaries. Charge energy is reported as a positive magnitude. RMS and time metrics are preferable to unweighted averages with irregular sampling.

Next validation: inspect braking events against `speedY`, steering and brake signals; compare several smoothing windows and quantify changes in energy and event timing; confirm the representative EV and exact cell before adopting parameters. The current smoothing window and scale are comparison defaults, not recommendations for physical testing. Eighteen tests now pass, including conditioning, explicit scaling and integration metrics.

## Window sensitivity and braking-event inspection

Run `python analyze_telemetry.py` to compare 0 (raw), 0.1, 0.2 and 0.5 s smoothing independently in each segment. It writes `output/torcs_analysis/window_sensitivity.csv`, `braking_events.csv`, parameter provenance and three detailed braking plots. The analysis uses the source-informed vehicle and experiment scale 0.2, without changing any defaults. It verifies the original hash and normalized timestamp/speed mapping before aligning source signals by audited CSV row number.

The plots show ±1.5 s around each segment's strongest raw deceleration, with raw/conditioned longitudinal speed and acceleration, original throttle/brake/steering commands, and lateral speed. This targets three events, not every braking episode or a complete dynamics calibration.

Observed sensitivity for this recording:

| Window | Speed RMS change across segments | Requested discharge energy change | Requested charge-energy change |
| --- | --- | --- | --- |
| 0.1 s | 0.032–0.049 m/s | −1.53 to −1.86% | −0.89 to +2.27% |
| 0.2 s | 0.074–0.078 m/s | −3.50 to −4.89% | −3.66 to +5.11% |
| 0.5 s | 0.222–0.233 m/s | −8.23 to −9.06% | −0.66 to +10.47% |

The 0.1 s window is a reasonable candidate for further review because its energy distortion is smaller; it is not automatically enabled. These percentages describe model-derived cell energy before current clipping, not observed physical battery energy. Filter changes affect braking allocation and capped regeneration nonlinearly.

`strongest_decel_time_shift_s` compares global strongest-event timestamps. A shift near 14.6 s in segment 02 means a different event becomes strongest after filtering, not a 14.6 s filter delay. `local_decel_peak_shift_s` instead restricts the conditioned search to ±1.5 s around the original event; even that is peak movement, not a measurement of controller latency.

The strongest raw events occur at source rows 1916, 3282 and 4942, with accelerations approximately −34, −26.79 and −32.69 m/s². All three rows record zero brake and zero throttle. This does not prove braking is absent: commands may be aligned with subsequent sensor updates, and neighbouring rows may differ. Nor does it establish that speed changes are purely noise. Lateral motion, tire/drivetrain behavior and collection alignment remain possible contributors requiring further investigation. Do not choose a filter solely to erase these events.

Next: inspect several neighbouring brake-command transitions and verify logger sensor/action ordering, compare the candidate 0.1 s results against raw data, and select the exact cell. Retain both the raw and conditioned profiles in the report. Hardware integration and adoption of a final profile remain separate tasks. The test suite now has 19 tests, including time-weighted sensitivity metrics.

## Revised software architecture diagrams

See [SOFTWARE_ARCHITECTURE.md](docs/SOFTWARE_ARCHITECTURE.md) for the working Milestone 1 and planned full-system diagrams, explanations of every component and numbered connection, equations and changes from the original teammate sketch. Printable figures: [two-page PDF](docs/APS380_software_block_diagrams.pdf), [offline SVG](docs/milestone1_software_diagram.svg), and [planned-system SVG](docs/planned_system_diagram.svg). PNG versions are alongside the SVGs. Rebuild the figures with `python docs/render_architecture.py`.
