# APS380 — Updated Project Context for Codex
## Driver-in-the-Loop EV Battery Test Platform

### 1. Project objective

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

The exact telemetry extraction and power-derating hooks in TORCS have not yet been implemented or verified.

#### Layer 2 — Python host application

Responsible for:
- Receiving TORCS driving telemetry.
- Calculating requested EV battery power.
- Scaling vehicle power demand to the single-cell test platform.
- Estimating SOC and SOP using measured battery data.
- Calculating permissible charging/discharging power.
- Converting permissible power into signed cell-current demand.
- Sending the desired cell-current command to the ESP32.
- Receiving battery measurements and fault/status data from the ESP32.
- Sending battery-derived power/torque limits back to TORCS.
- Logging all measurements, commands and vehicle-performance results.

**Important architecture decision: The Python host does not directly control the electronic load or power supply in the intended final design.**

It communicates with the ESP32, which handles instrument commands and local hardware control.

#### Layer 3 — ESP32 DevKit firmware (C/C++)

The ESP32 is the embedded hardware controller.

Responsible for:
- Receiving signed current-demand commands from Python.
- Validating current requests against configured operating limits.
- Translating requested battery current into electronic-load current commands.
- Communicating with the BK Precision 8500.
- Interfacing with the PSU if suitable remote-control functionality is available.
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

The ESP32 is expected to communicate with the eLoad through its serial interface, subject to confirmation of:
- The appropriate electrical interface and adapter.
- TTL logic-level compatibility.
- Required isolation.
- Serial communication protocol.
- Instrument command timing and response latency.
- Available current at low cell voltages.

Do not assume that the BK 8500 supports I²C or SPI directly.

If the ESP32-to-eLoad communication proves impractical, PC-to-eLoad serial control is an acceptable architectural fallback, while the ESP32 retains sensing and battery protection supervision.

**Power supply: Programmable or manually configured DC PSU**

The instructor indicated that a suitable current-limited PSU can be selected.

The specific PSU model is not finalized.

The initial plan is to configure the PSU manually with appropriate current and voltage settings. ESP32-controlled PSU communication is optional and depends on the selected instrument.

A supply having a current-limit setting does not necessarily mean it will maintain a constant charging current over the complete test.

### 4. Bidirectional current using a constant PSU bias

The electronic load can draw current but cannot supply charging current.

We therefore use the PSU and electronic load simultaneously.

Define:

- `I_cell > 0`: battery discharge, corresponding to propulsion.
- `I_cell < 0`: battery charge, corresponding to regenerative braking.

Ideal current relationship:

`I_cell = I_eLoad - I_PSU`

If the PSU maintains a constant current bias:

`I_eLoad_command = I_bias + I_cell_command`

Example using illustrative values:

| Condition | PSU bias | eLoad current | Net battery current |
|---|---:|---:|---:|
| Neutral | 4 A | 4 A | 0 A |
| Acceleration | 4 A | 7 A | +3 A |
| Regeneration | 4 A | 2 A | -2 A |

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
| ESP32 ↔ BK Precision 8500 | Verified compatible serial/UART interface |
| ESP32 ↔ PSU | Optional, dependent on model |

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
9. Send the signed current request to ESP32.
10. Send the corresponding power/torque limitation to TORCS.
11. Log all inputs, outputs, measurements and system states.

Positive current means discharge and negative current means charge throughout the entire codebase.

The SOC estimator must use measured net battery current, not eLoad branch current or requested current.

### 7. Battery estimation

#### SOC

Initial SOC estimation method: coulomb counting.

With SOC represented as a fraction between 0 and 1:

`SOC_next = SOC_previous - I_cell * dt / (3600 * capacity_Ah)`

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

For the current software milestone, measured battery data is not yet available, so SOC/SOP integration should be deferred or implemented behind clearly identified mock interfaces.

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

The repository began as an initial software-only starter. Its current implemented status is summarized below and supersedes the original expected-file list:

- Genuine public TORCS CSV ingestion through a separate adapter, with source preservation, unit conversion, exclusions and independent lap/continuity segments. This is not yet this team’s live TORCS/G29 integration.
- Separate configurable EV model, energy-based cell scaling, signed fixed current limits, CSV processing and plotting.
- Optional offline local-linear conditioning and explicit experiment scaling, assessed using comparisons and sensitivity/braking diagnostics. Neither establishes physical calibration.
- Nineteen passing software tests at the October 8 review; architecture diagrams and explanatory documentation.
- No implemented hardware communication, measured SOC/SOP, live simulator feedback or physical battery control.

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

### 10. Immediate development milestone

**Milestone 1: Reliable offline telemetry-to-current processing**

We are currently refining the initial Python starter, not implementing the final hardware controller.

The first goal is:

**CSV driving telemetry → EV power model → pack-to-cell scaling → signed cell-current demand → plots and logged output.**

Tasks:

- Review the existing Python implementation.
- Identify inaccurate or unjustified assumptions.
- Ensure calculations are dimensionally correct.
- Use SI units consistently.
- Make EV and battery parameters configurable.
- Validate timestamp handling, acceleration calculation and signed regenerative braking.
- Ensure current requests are bounded by clearly identified simulation/test limits.
- Separate the EV power model from cell-scaling logic where useful.
- Add unit tests for acceleration, cruising, regenerative braking, zero demand and invalid input.
- Produce clear graphs and CSV output.
- Document model limitations and assumptions.
- Keep the code small, understandable and maintainable.

Do not add a GUI unless it becomes necessary.

Do not implement physical BK 8500 or PSU commands as part of this milestone.

### 11. Future software milestones

**Milestone 2 — Real TORCS telemetry**

Identify or build a C/C++ TORCS telemetry exporter.

Obtain actual speed, throttle, braking and timestamp data. Initially record these as CSV.

Then optionally implement live TORCS-to-Python streaming using UDP.

**Milestone 3 — Python-to-ESP32 communication**

Develop a simple USB serial protocol.

The Python host will eventually send signed battery-current demands.

The ESP32 will return timestamped V/I/T data, fault status and controller state.

Begin with simulated ESP32 responses; do not require physical hardware to test the host interface.

**Milestone 4 — ESP32 instrument integration**

Implement a suitable BK 8500 serial driver on the ESP32 after validating its interface.

Use the ESP32 to map signed current requests into electronic-load commands.

Test the interface first without a lithium-ion cell using an approved bench configuration.

**Milestone 5 — SOC/SOP closed-loop feedback**

Integrate measured V/I/T.

Develop SOC and SOP algorithms.

Use SOP to constrain battery-current requests and simulated vehicle power/torque.

**Milestone 6 — Full system integration and validation**

Demonstrate:

- Driver-controlled vehicle dynamics.
- Real battery current response.
- Measured V/I/T.
- SOC/SOP estimation.
- Battery-induced TORCS power derating.
- Logging and repeatable tests.
- Hardware safety response.

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

Our current priority is the Python telemetry-to-battery-current pipeline.

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
- Direct Python control of BK 8500 or PSU in the intended architecture.
- ESP32-specific firmware inside the Python repository.
- Unverified claims about TORCS APIs or physical instrument behaviour.
- Unnecessary abstraction or complex design patterns.

Keep the first milestone achievable, then expand the implementation incrementally.

### 14. Team coordination update — October 8, 2026

These notes reconcile the team's proposed hardware/firmware plan with the existing architecture. Proposed options and dates below are not completed work or finalized component selections.

#### Immediate bench proof of concept

- Proposed bench meeting: Friday, October 9, 2026. Time, attendees, lab access and meeting booking remain unconfirmed; recording this plan does not schedule or contact anyone.
- Objective: demonstrate bidirectional **net cell-path current** using a sourcing PSU and sinking electronic load, both intended to operate in constant-current (CC) mode where their operating envelopes permit.
- Use “CC mode” for this instrument behavior; “CCM” can also mean continuous-conduction mode in converter design and is ambiguous here.
- First validate the concept without a lithium-ion cell using a supervisor-approved battery substitute / bench configuration that supports the intended source/sink conditions. Do not assume a resistor alone reproduces a bidirectional cell interface.
- Independently measure PSU branch current, eLoad branch current and net test-path current; compare commanded and achieved current during discharge, neutral and charging requests and transitions.
- Confirm whether the PSU actually maintains constant bias, including voltage compliance, mode changes and instrument synchronization. The ideal relation remains `I_cell = I_eLoad - I_PSU`; bias shifting remains conditional.
- Assess instrument operating limits at the intended cell voltage, current tracking/settling, measurement accuracy and behavior when either instrument or controller stops. Capture evidence before claiming the bias concept is validated.
- This is a separate hardware workstream; Milestone 1 Python remains offline.

#### Cell, mechanical partition and BOM decisions

The exact 18650 model remains unspecified. Record datasheet-backed minimum/maximum voltage, charge and discharge current limits separately, continuous versus pulse ratings (including pulse duration), capacity, and separate charge/discharge temperature ranges. “18650” specifies a form factor, not an operating envelope.

A movable cell/protection daughterboard for temperature-chamber testing is a proposed option. Decide where sensing, independent protection, disconnects and connectors belong, and ensure moving the cell does not bypass protection or invalidate sensing. A separate BMS IC/board is not yet selected; it must have an explicitly defined role rather than silently replacing Python or ESP32 responsibilities.

Relay/MOSFET/mechanical isolation, latching or resettable protection, precharge, discharge/bleed resistors, and any PSU-associated resistor are unresolved electrical design choices. Specify the purpose and circuit topology before choosing values or ordering application-specific parts. Evaluate precharge only after identifying capacitance, inrush and switch/instrument constraints; it is not automatically required for every single-cell setup.

No BMS IC, capacitor, inductor, switch or resistor value is approved by these notes. The October 9 ordering list remains a candidate BOM, dependent on requirements, chosen topology and component ratings. Component reuse from perfboard to PCB is a cost-saving option, not a guaranteed assembly plan.

#### Protection and monitoring responsibilities

Maintain three separate layers:

1. Python: high-level demand, measured SOC/SOP, operating limits and reporting.
2. ESP32: local sensing, command validation, instrument coordination, current-tracking/mismatch monitoring, communication timeout and firmware supervision.
3. Independent hardware: cell isolation and protection that do not rely on Python or normal ESP32 execution.

Monitor cell voltage, net current and temperature; protect against over/undervoltage, overcurrent/short circuit and excessive temperature. Address host freeze, firmware freeze, reset, communication loss and PSU/eLoad mismatch. Specify fault detection thresholds, permitted transient duration, action, reset policy and verification separately. Software freezing is not the only failure mode: instrument outputs and the sourcing PSU can persist after command loss.

Independent disconnection must interrupt hazardous paths in either current direction. An eLoad shutdown or a zero-current request is not sufficient isolation. A resettable fuse alone is not equivalent to complete controllable isolation; exact device capabilities must be evaluated. A current-sensing IC plus an automotive relay is one candidate, not an approved design; a sensor alone does not establish an independent trip mechanism.

Temperature monitoring and isolation address overheating risk but do not guarantee that an internally initiated thermal runaway can be stopped. The lab's cell-handling/test procedures must address residual hazards independently of software estimates.

SOC/SOP are operating estimates, not substitutes for direct trips. SOC uses measured net current, measurement elapsed time, capacity and initial SOC; voltage can inform/reference the estimate. SOP uses measured voltage/current/temperature, SOC and approved cell limits, with a conservative model initially.

#### Ownership clarification for firmware planning

The notes proposing firmware SOC/SOP work do **not** transfer primary estimator ownership: Python remains responsible for the project SOC/SOP estimates and the common allowable-power / TORCS feedback calculation. ESP32 owns sensing, fast local supervision and execution. Optional local conservative bounds or cross-check estimates may supplement the host, but must have defined authority and be reported so conflicting limits are reconciled explicitly.

The ESP32 is more than a passive monitor: it also controls instruments and isolation requests. Independent protection remains separate. RTOS setup and JTAG/breakpoint debugging are firmware investigation tasks, not new Python dependencies or a finalized board/toolchain selection.

#### Communication scope

“I²C most likely” applies to compatible selected sensing ICs, not the entire system:

| Link | Intended interface |
| --- | --- |
| TORCS ↔ Python | CSV replay now; proposed localhost UDP for live exchange |
| Python ↔ ESP32 | Proposed USB serial |
| ESP32 ↔ selected sensing ICs | I²C / ADC acquisition as supported by the chosen devices |
| ESP32 ↔ BK Precision 8500 | Verified compatible serial interface; electrical compatibility/isolation unresolved |
| ESP32 ↔ PSU | Optional model-dependent remote interface; manual setup initially |
| ESP32 → isolation driver | GPIO through suitable driver circuitry |

#### Tentative parallel work and timeline

Parallel work means team workstreams with shared interfaces and test evidence; it does not require creating extra software frameworks.

| Period | Proposed work | Dependencies / qualification |
| --- | --- | --- |
| October 9 | Bidirectional bench POC; start appropriate breadboard/perfboard prototyping | Approved bench configuration and instrument availability; prototype current paths must be suitable for their ratings |
| Through end of October | Software independently develops own telemetry extraction, meaningful driver/power profiles, live processing mocks, feedback-hook investigation, monitoring/logging and software fault behavior | Public CSV ingestion already works; live telemetry modification/feedback is not yet implemented |
| October, in parallel | Firmware sensing, serial protocol, instrument control, local faults, RTOS/debugging investigation alongside electrical prototyping | Board/toolchain and hardware interfaces need confirmation; define units/sign/timestamps/state contract early |
| October design phase | Evaluate optional PLECS battery/circuit simulation; resolve precharge, bleed, resistors, switches and protection | Simulation is optional supporting evidence, not proof of bench protection or timing |
| First week of November | If PCB is ready, connect/flash the ESP32 firmware and test in stages, beginning with protection before meaningful cell load | Manufacturing and delivery are not guaranteed; MCU may remain a DevKit connected to the custom PCB |
| Within one week of PCB availability | Target HW/FW integration and decide whether to use the validated perfboard fallback | Target rather than demonstrated feasibility; fallback must still meet protection and measurement requirements |
| By end of second week of November | Begin full SW/HW/FW integration | Compatible protocol, calibrated sensing, independently validated protection and instrument behavior |
| Third week of November | Basic closed-loop functionality and refinement | Measured SOC/SOP and TORCS feedback must be verified together |
| Fourth week of November | Video and final reports | Preserve validation evidence and limitations |
| First week of December | Contingency buffer | Confirm against course submission dates |

Consulting Professor Trescases and outside papers is proposed team research; access/contact and source verification remain pending. These notes do not authorize automated scheduling, emails or hardware operation.

#### Milestone 1 alignment and acceptance boundary

The implemented offline software aligns with the team tasks of creating meaningful driving/power/current profiles and with the Python host architecture. It does not implement physical POC control, a BMS, measured monitoring, independent protection, SOC/SOP or live telemetry feedback. Fixed clipping and passing equation tests are software evidence, not bench safety validation.

The demonstrated source-informed smoothed/reduced profile is an engineering comparison: source-car association is inferred, nominal voltage/capacity and pack energy are assumptions, and experiment scale 0.2 deliberately reduces C-rate. Final profile and cell-specific bounds must be justified after cell selection and current-tracking POC evidence. Centered offline smoothing must be replaced or explicitly redesigned before real-time control.
