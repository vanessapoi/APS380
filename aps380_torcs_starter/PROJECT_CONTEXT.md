# APS380 — Updated Project Context for Codex
## Driver-in-the-Loop EV Battery Test Platform

### Established architecture decision — October 20, 2026

The PC connects directly to both the electronic load and the PSU. The Python host on the PC owns instrument communication, signed cell-current demand mapping, SOC/SOP calculations from measured cell data, and battery-dependent TORCS feedback. The ESP32 owns cell sensing, timestamped measurement/status reporting, local supervision and isolation coordination; it is not the instrument-command bridge. Independent PCB protection remains separate.

This decision supersedes earlier ESP32-controlled-instrument and manual-PSU-only proposals, including the ownership assumptions in the October 8 coordination notes below. It defines the intended architecture, not a claim that live instrument control or SOC/SOP integration is already implemented.

### Current prototype decision - October 27, 2026

The mock prototype uses charging-positive CELL current: `i_c = i_p - i_e`.
The PSU CC setpoint is fixed at **1.0 A** during RUNNING; eLoad CC setpoints are
**0 to 3.0 A**, including enabled 0 A; battery requests are **-2.0 to +1.0 A**.
All operating settings and control tolerances are centralized in
`prototype_current_config.py`. These are prototype mock settings, not verified
hardware safety ratings. The final-design 2 A PSU and 12 A eLoad values are NOT
applied to this prototype. Positive-only profile shifting is not implemented.
Raw TORCS pack telemetry/physics remain discharge-positive and unchanged. Python
converts once at cell scaling; branch currents remain nonnegative magnitudes.
CC mode, fixed PSU setpoint, fresh readbacks, feasibility, balanced isolated
startup, reversals, fault latching and shutdown are supervised. No physical driver
or live SOC/SOP connection is added. The existing offline measured-current SOC
counter is migrated to charging-positive input; native simulated pack SOC is
unchanged. Historical captures retain their original schema and sign convention.

### Experimental Mac simulator build — October 27, 2026

On `feat/torcs-macos-build`, the modified TORCS source compiled as native arm64,
installed into `.local/torcs-macos/`, and opened a window in XQuartz. The operator
confirmed the main menu was visible. See `../docs/torcs-macos.md` and
`../scripts/macos/` for the repeatable recipe and isolated launcher. Changes cover
Mac plugin linking, font endianness header, ALUT signature and disabling obsolete
Carbon-based PLIB sound in favor of the existing OpenAL path. Windows-specific
paths are retained; Windows was not rebuilt during this session.

A subsequent Mac console run with the existing Tesla Model 3 reference profile
and deterministic `aps380_ai` driver completed 4218.37 m over 442.08 s simulated
time and passed all 11 existing protocol gates (speed holds, regeneration,
friction braking, stationary hold, course completion and model/impact audits).
The visible AI profile opens through `scripts/macos/run_tesla_ai.py --visible`;
choose Race > Practice > New Race to watch. The graphical AI race also started and recorded over 1,600 driving samples with
zero damage at the observed checkpoint; full graphical course completion has not
yet been independently verified. An executable-level graphics plugin loader
check now guards against missing symbols. The existing 164 Python tests and two
portable setup tests passed in the complete Python 3.13 environment. Shared Windows setup helpers now
accept explicit native runtime/profile/driver paths; model assumptions and
Windows defaults remain unchanged.

No keyboard/G29 validation, Mac live UDP/HUD, physical instrument connection,
measured SOC/SOP or closed-loop battery feedback was demonstrated. The Windows-only UDP/HUD implementation still
has disabled non-Windows paths. Generated dependencies, installed assets and user
configuration stay outside tracked source under `.local/torcs-macos/`.

### 1. Project objective

Current mock-control extension: `instrument_interfaces.py`, `mock_instruments.py`
and `instrument_control.py` connect validated live current demand to an optional
independent mock-only PSU/eLoad worker. Explicit arming, readback-based signed
mapping, separate directional bounds, latched faults and mock isolation shutdown
are implemented; see `../docs/mock-instruments.md`. No physical drivers, ESP32
acquisition, measured SOC/SOP integration or vehicle derating are supplied by this
extension. Existing statements about missing hardware control still apply.

The mock coordinator uses a bounded slew, measured neutral dwell before sign
reversal, tracking/direction faults and startup readback stabilization. Trial
acceptance separates telemetry, process health, instrument control and full-course
completion. `--acceptance smoke` does not require a completed course. Fault
injection retains normal-operation failure separately from verified fault response.
These settings are mock experiments, not physical timing or safety ratings. A
validated native ENDED event disarms and never automatically rearms on new data.
READY now balances the isolated mock branches at zero net current independently
of live demand; fresh settled PSU/eLoad readbacks and a neutral dwell precede
RUNNING. Startup during regeneration no longer tests feasibility against the
first rising PSU sample. Reports distinguish PASS/FAIL/NOT ASSESSED and label
retained pre-fault measurements; no RUNNING evidence means tracking is unassessed.
Expected launcher shutdown is marked before ending the native UDP/HUD peer;
unexpected receiver errors remain visible. These changes add no physical drivers
and do not change the established signed-current architecture.

We are developing a driver-in-the-loop electric vehicle battery testing platform for APS380 at the University of Toronto.

The system connects a driving simulator (TORCS) to a real single-cell lithium-ion battery test circuit.

A driver uses a Logitech G29 steering wheel and pedals to drive a simulated EV. TORCS provides vehicle telemetry, which our software converts into estimated vehicle power demand. That power is scaled into a safe, signed current demand for a single nominally 3.6 V 18650 cell.

A programmable power supply and BK Precision 8500 electronic load apply the desired charging/discharging profile to the physical cell. The cell's voltage, current and temperature are measured through a custom PCB controlled by an ESP32 DevKit.

Measured battery conditions are used to estimate state of charge (SOC) and state of power (SOP). The calculated battery power limitations are fed back into TORCS, affecting the vehicle's available power, torque and performance.

**The central project goal is closed-loop interaction between the simulated EV and the real battery.**

### 2. Updated system architecture

We are using a three-layer software architecture.

#### Layer 1 — TORCS simulator (C/C++)

Responsible for:
- Receiving steering, acceleration and braking inputs from the Logitech G29.
- Simulating vehicle motion.
- Providing vehicle telemetry to the Python application.
- Receiving updated power/torque limits from Python.
- Applying battery-dependent vehicle power derating.

Proposed communication with Python: localhost UDP.

Native human-driver and EV CSV recording and a reduced-order electric powertrain are present; see `../docs/tesla-experiment.md`. Optional Windows loopback UDP now streams native EV data to a Python validator, fixed cell scaler and desktop monitor; see `../docs/torcs-live.md`. External battery-derived power limits remain planned. Live simulated quantities are not proof of physical battery integration or validated Tesla fidelity.

#### Layer 2 — Python host application

Responsible for:
- Receiving TORCS driving telemetry.
- Calculating requested EV battery power.
- Scaling vehicle power demand to the single-cell test platform.
- Estimating SOC and SOP using measured battery data.
- Calculating permissible charging/discharging power.
- Converting permissible power into signed cell-current demand.
- Mapping signed cell-current demand into coordinated eLoad and PSU commands and sending them directly from the PC.
- Receiving battery measurements and fault/status data from the ESP32.
- Sending battery-derived power/torque limits back to TORCS.
- Logging all measurements, commands and vehicle-performance results.

**Established architecture decision: The Python host on the PC connects directly to and controls both the electronic load and the PSU. SOC and SOP are calculated on the PC from measured cell data.**

A separate PC–ESP32 link carries measurements, status, heartbeat and ARM/DISARM supervision. Instrument commands do not pass through the ESP32.

#### Layer 3 — ESP32 DevKit firmware (C/C++)

The ESP32 is the embedded sensing and local-supervision controller.

Responsible for:
- Receiving ARM/DISARM, heartbeat and supervision messages from Python.
- Validating supervision requests against local operating state and fault conditions.
- Reading battery voltage, current and temperature sensors.
- Managing ARM/DISARM operations.
- Monitoring local faults and communication heartbeat.
- Coordinating relay/MOSFET control.
- Reporting battery measurements and hardware status to Python.

The ESP32's exact board variant, firmware development environment and pin assignments remain to be confirmed.

#### Independent PCB safety

Hardware protection must remain functional independently of Python and the ESP32.

The custom PCB is intended to provide:
- Battery voltage/current/temperature sensing.
- Current sensing using a bidirectional shunt monitor.
- Appropriate fuse protection.
- Overvoltage and undervoltage protection.
- Overcurrent and overtemperature protection.
- Default-open battery isolation through an appropriately designed disconnect.
- Emergency-stop functionality.

Software current limits and MCU supervision are additional protections, not substitutes for independent hardware protection.

### 3. Instrument architecture

**Electronic load: BK Precision 8500**

We have identified our electronic load as a BK Precision 8500, 300 W programmable DC electronic load.

The intended operating mode is constant current (CC).

The PC communicates directly with the eLoad through a compatible serial interface/adapter. The Python host owns the instrument driver, subject to confirmation of:
- The appropriate electrical interface and adapter.
- PC adapter and instrument electrical compatibility.
- Required isolation.
- Serial communication protocol.
- Instrument command timing and response latency.
- Available current at low cell voltages.

Do not assume that the BK 8500 supports I²C or SPI directly.

Direct PC-to-eLoad control is the established architecture, not a fallback. The ESP32 retains sensing and local battery supervision.

**Power supply: PC-controlled programmable DC PSU**

The instructor indicated that a suitable current-limited PSU can be selected.

The specific PSU model is not finalized.

The PC connects directly to and controls the PSU. Its exact interface, protocol and driver depend on the selected model and remain to be verified. Manual setup may be used during bench bring-up, but does not replace direct PC control in the intended integrated design.

A supply having a current-limit setting does not necessarily mean it will maintain a constant charging current over the complete test.

### 4. Bidirectional current using a constant PSU bias

The electronic load can draw current but cannot supply charging current.

We therefore use the PSU and electronic load simultaneously.

Define:

- `I_cell < 0`: battery discharge, corresponding to propulsion.
- `I_cell > 0`: battery charge, corresponding to regenerative braking.

Ideal current relationship:

`I_cell = I_PSU - I_eLoad`

The PC maps the desired net cell current using actual PSU branch current:

`I_eLoad_target = I_PSU_actual - I_cell_target`

Use measured or verified instrument readback for actual PSU current, with timestamps and freshness checks. Bound commands by equipment capabilities and approved cell limits; if a target is infeasible, limit the achievable cell demand and report it. Compare the result against independently measured net cell current. This mapping alone does not compensate instrument delay or guarantee accurate tracking.

If the PSU maintains a verified constant current bias:

`I_eLoad_command = I_bias - I_cell_command`

Example using illustrative values:

| Condition | PSU bias | eLoad current | Net battery current |
|---|---:|---:|---:|
| Neutral | 1 A | 1 A | 0 A |
| Acceleration | 1 A | 3 A | -2 A |
| Regeneration | 1 A | 0 A | +1 A |

These values are examples only, not approved operating currents.

The final bias/current settings must come from the exact cell's charge/discharge limits, the electrical design and bench validation.

**Important:** The controller must not assume the physical PSU current always equals the configured current limit. Actual net cell current must be independently measured. If constant bias cannot be verified or maintained, the simplified axis-shift relationship must not be used as an exact physical model.

### 5. Proposed hardware communications

| Connection | Proposed communication |
|---|---|
| TORCS ↔ Python | UDP over localhost |
| Python ↔ ESP32 | USB serial |
| ESP32 ↔ INA228 current/voltage monitor | I²C |
| ESP32 ↔ external ADC, if used | I²C |
| ESP32 → relay/MOSFET control | GPIO through appropriate driver circuitry |
| PC / Python ↔ BK Precision 8500 | Direct compatible serial interface/adapter; protocol and electrical interface to be verified |
| PC / Python ↔ PSU | Direct instrument connection; interface and protocol dependent on selected model |

The INA228 and ADS1115 are proposed components from our earlier BOM, not guaranteed final PCB components.

Avoid assigning exact ESP32 GPIO pins or I²C addresses until the development kit and PCB design are confirmed.

### 6. Python processing pipeline

The Python application's intended pipeline is:

1. Read TORCS driving telemetry.
2. Calculate requested vehicle battery power using a simplified EV dynamics model.
3. Scale vehicle power demand into single-cell power demand.
4. Obtain measured battery voltage, current and temperature from ESP32.
5. Update SOC through coulomb counting.
6. Calculate separate allowable discharge and charging SOP limits.
7. Limit requested cell power according to SOP and approved operating limits.
8. Convert permissible cell power to a signed current request.
9. Map the signed current request into coordinated eLoad/PSU commands and send them directly from the PC; obtain instrument status/readback where supported.
10. Send the corresponding power/torque limitation to TORCS.
11. Log all inputs, outputs, measurements and system states.

Cell current is charging-positive: negative means discharge and positive means charge. Raw TORCS pack power/current retain their native discharge-positive convention and are converted exactly once at the Python cell-scaling boundary.

The SOC estimator must use measured net battery current, not eLoad branch current or requested current.

### 7. Battery estimation

SOC and SOP both execute in the Python host on the PC. The ESP32 provides measured, timestamped cell data and fault/status information.

#### SOC

Initialize SOC from rested OCV, then update it in real time through coulomb counting using measured net cell current. The supplied *An Enhanced Li-ion Battery Model with Optimized OCV Estimation* (2025) has now been reviewed: it names the EVE INR18650/35V platform and supplies equation (15), but contains test-procedure and metrics inconsistencies. Its polynomial is implemented only as a candidate approximate-25°C reference, not a validated cell calibration. See `../docs/ocv-paper-review.md` and `../docs/cell-soc.md`.

Generate an OCV–SOC lookup table from the verified candidate relation and validate its range and invertibility. Validate initial and running SOC against experimental data for the selected cell; do not treat loaded terminal voltage as rested OCV or assume the published polynomial transfers to every 18650.

With SOC represented as a fraction between 0 and 1:

`SOC_next = SOC_previous + I_cell * dt / (3600 * capacity_Ah)`

The calculation must use:
- Measured cell current.
- Correct timestamps and elapsed time.
- A configured battery capacity.
- A defined initial SOC.

SOC should be clamped to the physically valid interval.

Validation target: within 10 percentage points of a rested OCV–SOC reference, recognizing that OCV comparison has limitations.

#### SOP

SOP represents the allowable cell power under current battery conditions.

Prefer separate outputs:

- Maximum allowable discharge power.
- Maximum allowable charging power.

Inputs may include:
- Measured voltage.
- SOC.
- Cell temperature.
- Datasheet current limits.
- Estimated internal resistance.
- Voltage and temperature headroom.

A conservative limits-based SOP model is acceptable initially. More sophisticated models should only be introduced when justified by available data and project timing.

Investigate short-horizon SOP estimation: define the prediction horizon and assess whether a validated cell model can predict voltage/current/temperature constraints over that interval. This is an investigation, not a selected or validated algorithm.

Develop SOC/SOP interfaces with recorded or clearly labelled mock measurements until live cell data and the relevant validation evidence are available.

### 8. TORCS power feedback

Battery SOP must influence the simulated vehicle.

Example:

- Requested cell power: 40 W.
- Allowed cell power: 25 W.
- Allowed propulsion fraction: 0.625.

TORCS should receive an appropriate power/torque limit that reduces vehicle performance.

The exact implementation must be compatible with the simulator's vehicle model.

Do not simply multiply all steering, throttle and brake inputs by one common factor.

The physical current command and TORCS power limitation must derive from the same allowable battery power calculation so the simulation and battery test remain consistent.

### 9. Python starter origin and current implementation

The repository began as an initial software-only starter. The offline calculation foundation is complete as reported by the team; this does not establish physical calibration or completed live integration. The following distinguishes the original baseline from later work:

- Genuine public TORCS CSV ingestion through a separate adapter, with source preservation, unit conversion, exclusions and independent lap/continuity segments. This is not yet this team’s live TORCS/G29 integration.
- Separate configurable EV model, energy-based cell scaling, signed fixed current limits, CSV processing and plotting.
- Optional offline local-linear conditioning and explicit experiment scaling, assessed using comparisons and sensitivity/braking diagnostics. Neither establishes physical calibration.
- Historical baseline: nineteen passing software tests at the October 8 review; architecture diagrams and explanatory documentation. Check current test output rather than treating this as the present test count.
- Subsequent TORCS work includes native CSV recording, an experimental Model 3 reference powertrain, and vehicle-level pack analysis. See `../docs/tesla-experiment.md` and `../docs/tesla-calibration-evidence.md` for recorded verification and remaining calibration limits. The live path now scales native pack power directly using captured pack capacity and explicit fixed cell/experiment parameters; the legacy speed-derived offline model remains separate.
- One-way loopback telemetry, validation/session handling, fixed scaling, desktop monitoring and AI/G29 trial tooling are implemented. An automated wall-clock-paced AI course has recorded CSV/stream agreement and timing evidence. This is not physical current tracking or a battery-to-vehicle feedback loop; see `../docs/torcs-live.md` for replay, trial gates and remaining work.
- Candidate OCV lookup/inversion and PC-side net-cell-current coulomb counting now have an offline replay with explicit rest evidence, capacity basis, measurement-gap/session rejection, provenance and mock tests. No physical-cell accuracy has been established; see `../docs/cell-soc.md`.
- No implemented hardware communication, experimentally validated measured SOC/SOP, live simulator feedback or physical battery control.

Repository:

`aps380_torcs_starter/`

Originally provided as:

`APS380_TORCS_Python_Milestone1.zip`

Expected files:

- `make_demo_data.py`
- `battery_model.py`
- `run.py`
- `tests.py`
- `requirements.txt`
- `README.md`
- `data/`
- `output/`

The starter generates synthetic driving telemetry, estimates EV power, scales it to a single-cell current demand and produces CSV/graph outputs.

The synthetic data is not real TORCS telemetry.

The first expected input CSV format is:

```csv
time_s,speed_mps,throttle,brake
0.0,0.0,0.0,0.0
0.1,0.2,0.3,0.0
0.2,0.6,0.5,0.0
```

The current codebase must be inspected before making assumptions about the precise implementation.

### 10. Current development scope and status

The completed offline foundation is:

**CSV driving telemetry → EV power model → pack-to-cell scaling → signed cell-current demand → plots and logged output.**

The active roadmap now extends this foundation to live telemetry, direct PC instrument control, measured current tracking, ESP32 data, SOC/SOP, monitoring and vehicle feedback. The original offline-only milestone restrictions are historical, not a prohibition on implementing these planned modules. Physical operation remains disabled by default until the relevant equipment, limits and fault responses are validated.

The team has made and run Model 3 reference-model changes in TORCS. Record reproducible evidence for each task below rather than inferring that every G29 check, live interface or hardware task is complete. Keep vehicle-model calibration separate from software integration validation.

### 11. APS380 software roadmap

This is the current eleven-task plan. Numbering identifies workstreams; dependencies permit mock-based development in parallel. “Tuesday 6 PM” is the team's stated target for Tasks 1 and 2; the calendar date is unspecified and no meeting is booked by this document. Tasks 4 and 5 are planned in-lab with Satyam's help, not claimed as completed sessions.

#### 1. TORCS + Logitech G29 integration — Tuesday 6 PM target

- Set up TORCS and connect the G29 using the project's source-built simulator.
- Verify steering, throttle and independent braking, axis direction/calibration and usable transmission settings.
- Evidence: record configuration, build/profile identity and a successful controlled drive; distinguish existing recordings from remaining input checks.

#### 2. TORCS telemetry extraction — Tuesday 6 PM target

Current implementation: native EV CSV and optional live UDP share the same serialized samples. The host checks profile identity, numerical/electrical consistency, session continuity, sequence loss and data age. Real-time AI trial tooling compares received data with native CSV and reports timing. A loopback return link supplies visual HUD metrics and current-limit warnings only. Reverse-direction power derating remains unimplemented.

- Extract real-time speed, throttle, braking and required EV quantities, including requested/applied motor or pack power where available.
- Include timestamps, explicit units, car/profile and session identity; record data for replay and testing.
- Retain existing CSV recorders and implement the live host link; localhost UDP is the proposed transport. Live exchange is required for the closed loop, not satisfied by CSV recording alone.
- Evidence: verify monotonic session timestamps, units, continuity, restart handling and correspondence between the recorded and streamed data.

#### 3. Battery power demand calculation — offline calculation done

- Maintain telemetry-to-power calculation, pack-to-cell scaling and signed charging/discharging current requests: negative means discharge, positive means charge.
- Integrate native EV power telemetry with the existing cell-scaling workflow using one explicit vehicle/cell configuration; retain the offline estimator for replay/diagnostics without double-counting power.
- Evidence: preserve equation/unit tests, scaling provenance and distinct requested versus limited current. Offline completion does not establish hardware tracking or real-car calibration.

#### 4. PSU / electronic-load communication and control — in lab with Satyam

- Establish direct PC communication with both instruments; Python owns their drivers and coordinated commands.
- Map desired cell current using `I_eLoad_target = I_PSU_actual - I_cell_target`, subject to validated topology, measurement freshness and feasible equipment/cell limits.
- Verify actual PSU operating mode, voltage compliance, readback, command ranges and instrument-specific behaviour.
- Evidence: demonstrate controlled command/readback and net-current sign in an approved bench configuration before cell operation.

#### 5. Current tracking and response testing — in lab with Satyam

- Compare requested and commanded cell current with independently measured net cell current.
- Measure mismatch, communication latency, instrument response/settling and transitions between charging, neutral and discharging.
- Determine from measurements whether feedback correction is needed; do not assume the current-mapping equation guarantees tracking or select controller gains without response evidence.
- Evidence: timestamped traces and agreed tracking/timing acceptance criteria, including saturation and delayed response.

#### 6. Software safety limits

- Implement separate approved charging/discharging current limits and voltage/temperature limits.
- Handle absent, invalid or stale measurements, communication loss, equipment faults and stop requests.
- Coordinate PC commands, ESP32 supervision and shutdown with independent hardware protection; stopping the eLoad alone must not leave unintended PSU charging.
- Evidence: mock fault-injection tests followed by approved bench checks of defined fault actions, recovery and stop behaviour.

#### 7. ESP32 communication and data logging

- Agree the measurement message format, units, sign convention, sequence/session identifiers and timestamp meaning with the firmware team.
- Receive timestamped voltage, net cell current, temperature, status and faults; send supervision/heartbeat and ARM/DISARM messages as agreed.
- Align and log measurements alongside driving data, equipment commands/readback, tracking error and system state. Distinguish measurement time from host receipt time.
- Evidence: replay/mock tests for missing, malformed, duplicate, delayed and restarted streams, then live measurement validation. Instrument commands remain on direct PC links.

#### 8. SOC estimation — PC side

Current implementation: candidate EVE OCV lookup and stateful current integration are implemented and checked with mock data. The paper has been reviewed; experimental OCV coverage, effective capacity, relaxation criteria and SOC accuracy remain unvalidated. Live measurement acquisition is not implemented. See `../docs/cell-soc.md` for the interface, assumptions and executable example.

- Verify the candidate 2025 OCV-estimation paper and cell applicability before adopting its polynomial; generate and validate an OCV–SOC lookup table.
- Estimate initial SOC from rested OCV under documented conditions.
- Implement real-time coulomb counting using measured net cell current and measurement elapsed time, with explicit capacity, initial state and measurement-gap handling.
- Validate against experimental battery data; retain the section 7 rested-OCV comparison target with its limitations.
- Evidence: reference provenance, lookup-table checks, recorded-data tests and experimental error results; mocks alone do not validate cell accuracy.

#### 9. Battery monitoring and UI

Current implementation: the in-game HUD and optional desktop monitor show live simulated pack quantities, fixed-scale requested/limited cell demand, sample age, errors and stream state. In-game visual warnings use unclipped demand and separate charge/discharge bounds; stale feedback makes current unavailable. Physical cell V/I/T/SOC are explicitly not connected. The sensing, measured monitoring and hardware supervision requirements below are still pending.

- Provide a lightweight live display of voltage, measured current, temperature, SOC and relevant maxima/minima with a defined reset/window policy.
- Show requested, commanded and measured current distinctly, together with faults, operating state and data freshness.
- Connect the same display to replay/mock and live data; monitoring must not block control or substitute for independent protection.
- Evidence: verify display values, extrema, stale-data indications and fault visibility against logs. A monitoring UI is an explicit deliverable; a large GUI framework is not required.

#### 10. SOP estimation and driving-performance feedback — PC side

- Calculate separate available discharge and charge-absorption power limits from measured battery conditions and approved bounds.
- Investigate short-horizon prediction as described in section 7; begin with a justified conservative method rather than assuming a validated dynamic model exists.
- Apply a common allowable-power calculation and consistent pack/cell scaling to equipment commands and TORCS motor power/torque limits.
- Preserve steering and friction braking; distinguish driver demand from applied power and address regeneration limits, low-speed behaviour, pauses and stale feedback.
- Evidence: mock derating tests, logged requested/applied/actual values and then measured battery-dependent vehicle response. Simulated SOC is not a substitute for physical-cell SOC.

#### 11. System integration and testing

- Test individual modules with recorded/mock inputs, then integrate TORCS, calculations, direct PC instrument links, ESP32 measurement/supervision and monitoring.
- Validate timing, current tracking, fault handling and charging/discharging under acceleration, cruise, lift-off/braking, stops and session transitions.
- Record time bases, end-to-end delays, dropped/stale data, command saturation, measurement mismatch and energy/current signs. Define acceptance criteria before declaring a test passed.
- Evidence: reproducible configurations and logs linking each requirement to results and unresolved limitations. A running simulator or passing unit tests alone do not complete hardware integration.

### 12. Safety principles

All physical hardware control must be disabled by default in the Python starter.

Use simulated current commands until the MCU and instrument interface are validated.

Do not hardcode illustrative cell currents, bias currents, protection thresholds or temperature limits as though they are approved operating values.

The hardware design must address unintended PSU charging when the electronic load is disabled.

A zero-current software request does not guarantee zero physical battery current.

A serial disconnect, MCU reset, PC crash or communication timeout must not leave the battery exposed to uncontrolled charging or discharging.

Independent hardware protection must be implemented and reviewed separately from the Python and ESP32 firmware.

### 13. Instructions to Codex

Act as a software engineering collaborator on this project.

Inspect the existing repository before making changes.

Use the eleven-task roadmap in section 11 as the current software scope. Preserve the completed offline foundation while implementing live integration, monitoring and PC-owned SOC/SOP and instrument control in validated increments.

Use the full project architecture as context for choosing clean interfaces, but avoid implementing future subsystems prematurely.

Prefer:
- Small, testable modules.
- Clear data structures.
- Configurable vehicle/battery parameters.
- Explicit units and current sign conventions.
- Deterministic testing.
- Offline operation without hardware.
- Minimal dependencies.
- Clear documentation.

Avoid:
- A large GUI framework.
- Premature asynchronous infrastructure.
- Routing eLoad/PSU commands through the ESP32 or moving primary SOC/SOP estimation off the PC without an explicit architecture change.
- ESP32-specific firmware inside the Python repository.
- Unverified claims about TORCS APIs or physical instrument behaviour.
- Unnecessary abstraction or complex design patterns.

Keep each roadmap increment small and testable, and update implementation status only when supported by evidence.

### 14. Team coordination update — October 8, 2026

These are historical October 8 coordination notes. The established architecture decision and eleven-task roadmap above supersede their software scope and priority statements. Proposed options and dates below are not completed work or finalized component selections.

#### Immediate bench proof of concept

- Proposed bench meeting: Friday, October 9, 2026. Time, attendees, lab access and meeting booking remain unconfirmed; recording this plan does not schedule or contact anyone.
- Objective: demonstrate bidirectional **net cell-path current** using a sourcing PSU and sinking electronic load, both intended to operate in constant-current (CC) mode where their operating envelopes permit.
- Use “CC mode” for this instrument behavior; “CCM” can also mean continuous-conduction mode in converter design and is ambiguous here.
- First validate the concept without a lithium-ion cell using a supervisor-approved battery substitute / bench configuration that supports the intended source/sink conditions. Do not assume a resistor alone reproduces a bidirectional cell interface.
- Independently measure PSU branch current, eLoad branch current and net test-path current; compare commanded and achieved current during discharge, neutral and charging requests and transitions.
- Confirm whether the PSU actually maintains constant bias, including voltage compliance, mode changes and instrument synchronization. The ideal relation remains `I_cell = I_PSU - I_eLoad`; bias shifting remains conditional.
- Assess instrument operating limits at the intended cell voltage, current tracking/settling, measurement accuracy and behavior when either instrument or controller stops. Capture evidence before claiming the bias concept is validated.
- Historical boundary: the original Milestone 1 Python work was offline. The current roadmap now explicitly includes PC instrument control and hardware integration.

#### Cell, mechanical partition and BOM decisions

Historical note: the exact 18650 model was unspecified in these October 8 notes. The subsequently supplied `../documentation/18650.pdf` specifies EVE INR18650/35V; confirm that the physical cell matches it. Record datasheet-backed minimum/maximum voltage, charge and discharge current limits separately, continuous versus pulse ratings (including pulse duration), capacity, and separate charge/discharge temperature ranges. “18650” specifies a form factor, not an operating envelope. A complete approved bench operating profile has not been configured by the candidate SOC work.

A movable cell/protection daughterboard for temperature-chamber testing is a proposed option. Decide where sensing, independent protection, disconnects and connectors belong, and ensure moving the cell does not bypass protection or invalidate sensing. A separate BMS IC/board is not yet selected; it must have an explicitly defined role rather than silently replacing Python or ESP32 responsibilities.

Relay/MOSFET/mechanical isolation, latching or resettable protection, precharge, discharge/bleed resistors, and any PSU-associated resistor are unresolved electrical design choices. Specify the purpose and circuit topology before choosing values or ordering application-specific parts. Evaluate precharge only after identifying capacitance, inrush and switch/instrument constraints; it is not automatically required for every single-cell setup.

No BMS IC, capacitor, inductor, switch or resistor value is approved by these notes. The October 9 ordering list remains a candidate BOM, dependent on requirements, chosen topology and component ratings. Component reuse from perfboard to PCB is a cost-saving option, not a guaranteed assembly plan.

#### Protection and monitoring responsibilities

Maintain three separate layers:

1. Python on the PC: high-level demand, measured SOC/SOP, operating limits, direct eLoad/PSU communication, instrument coordination, current-tracking/mismatch monitoring and reporting.
2. ESP32: local sensing, supervision-message validation, timestamped measurements/status, communication timeout, isolation coordination and firmware supervision.
3. Independent hardware: cell isolation and protection that do not rely on Python or normal ESP32 execution.

Monitor cell voltage, net current and temperature; protect against over/undervoltage, overcurrent/short circuit and excessive temperature. Address host freeze, firmware freeze, reset, communication loss and PSU/eLoad mismatch. Specify fault detection thresholds, permitted transient duration, action, reset policy and verification separately. Software freezing is not the only failure mode: instrument outputs and the sourcing PSU can persist after command loss.

Independent disconnection must interrupt hazardous paths in either current direction. An eLoad shutdown or a zero-current request is not sufficient isolation. A resettable fuse alone is not equivalent to complete controllable isolation; exact device capabilities must be evaluated. A current-sensing IC plus an automotive relay is one candidate, not an approved design; a sensor alone does not establish an independent trip mechanism.

Temperature monitoring and isolation address overheating risk but do not guarantee that an internally initiated thermal runaway can be stopped. The lab's cell-handling/test procedures must address residual hazards independently of software estimates.

SOC/SOP are operating estimates, not substitutes for direct trips. SOC uses measured net current, measurement elapsed time, capacity and initial SOC; voltage can inform/reference the estimate. SOP uses measured voltage/current/temperature, SOC and approved cell limits, with a conservative model initially.

#### Ownership clarification for firmware planning

The notes proposing firmware SOC/SOP work do **not** transfer primary estimator ownership: Python remains responsible for the project SOC/SOP estimates and the common allowable-power / TORCS feedback calculation. ESP32 owns sensing, fast local supervision and isolation coordination; the PC executes instrument commands. Optional local conservative bounds or cross-check estimates may supplement the host, but must have defined authority and be reported so conflicting limits are reconciled explicitly.

The ESP32 is more than a passive monitor: it handles local supervision and isolation requests. The PC controls both instruments directly. Independent protection remains separate. RTOS setup and JTAG/breakpoint debugging are firmware investigation tasks, not new Python dependencies or a finalized board/toolchain selection.

#### Communication scope

“I²C most likely” applies to compatible selected sensing ICs, not the entire system:

| Link | Intended interface |
| --- | --- |
| TORCS ↔ Python | CSV replay now; proposed localhost UDP for live exchange |
| Python ↔ ESP32 | Proposed USB serial |
| ESP32 ↔ selected sensing ICs | I²C / ADC acquisition as supported by the chosen devices |
| PC / Python ↔ BK Precision 8500 | Direct compatible serial interface; electrical compatibility/isolation to be verified |
| PC / Python ↔ PSU | Direct model-dependent remote interface; model/protocol to be verified |
| ESP32 → isolation driver | GPIO through suitable driver circuitry |

#### Tentative parallel work and timeline

Parallel work means team workstreams with shared interfaces and test evidence; it does not require creating extra software frameworks.

| Period | Proposed work | Dependencies / qualification |
| --- | --- | --- |
| October 9 | Bidirectional bench POC; start appropriate breadboard/perfboard prototyping | Approved bench configuration and instrument availability; prototype current paths must be suitable for their ratings |
| Through end of October | Software independently develops own telemetry extraction, meaningful driver/power profiles, live processing mocks, feedback-hook investigation, monitoring/logging and software fault behavior | Public CSV ingestion already works; live telemetry modification/feedback is not yet implemented |
| October, in parallel | Firmware sensing, supervision serial protocol, local faults and RTOS/debugging investigation alongside electrical prototyping; PC-side instrument drivers developed by the software workstream | Board/toolchain and hardware interfaces need confirmation; define units/sign/timestamps/state contract early |
| October design phase | Evaluate optional PLECS battery/circuit simulation; resolve precharge, bleed, resistors, switches and protection | Simulation is optional supporting evidence, not proof of bench protection or timing |
| First week of November | If PCB is ready, connect/flash the ESP32 firmware and test in stages, beginning with protection before meaningful cell load | Manufacturing and delivery are not guaranteed; MCU may remain a DevKit connected to the custom PCB |
| Within one week of PCB availability | Target HW/FW integration and decide whether to use the validated perfboard fallback | Target rather than demonstrated feasibility; fallback must still meet protection and measurement requirements |
| By end of second week of November | Begin full SW/HW/FW integration | Compatible protocol, calibrated sensing, independently validated protection and instrument behavior |
| Third week of November | Basic closed-loop functionality and refinement | Measured SOC/SOP and TORCS feedback must be verified together |
| Fourth week of November | Video and final reports | Preserve validation evidence and limitations |
| First week of December | Contingency buffer | Confirm against course submission dates |

Consulting Professor Trescases and outside papers is proposed team research; access/contact and source verification remain pending. These notes do not authorize automated scheduling, emails or hardware operation.

#### Milestone 1 alignment and acceptance boundary

The implemented offline software aligns with the team tasks of creating meaningful driving/power/current profiles and with the Python host architecture. A candidate offline SOC estimator has subsequently been added with mock measurements. It does not implement physical POC control, a BMS, live measured monitoring, independent protection, validated SOC/SOP or live telemetry feedback. Fixed clipping and passing equation tests are software evidence, not bench safety validation.

The demonstrated source-informed smoothed/reduced profile is an engineering comparison: source-car association is inferred, nominal voltage/capacity and pack energy are assumptions, and experiment scale 0.2 deliberately reduces C-rate. Final profile and cell-specific bounds must be justified after cell selection and current-tracking POC evidence. Centered offline smoothing must be replaced or explicitly redesigned before real-time control.
