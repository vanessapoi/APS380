# Candidate cell SOC estimation

The Python host now has an offline, stateful SOC estimator for cell measurements. It initializes SOC using the candidate EVE INR18650/35V OCV relation from equation (15) of the 2025 paper, then integrates net cell current. It has no instrument connections and does not send commands to TORCS or hardware.

See [the paper review](ocv-paper-review.md) for source inconsistencies and limitations. This implements software behavior for roadmap Task 8; experimental cell validation remains pending. No SOC uncertainty bound or SOP performance is established.

## Files and units

- `aps380_torcs_starter/cell_soc.py`: candidate lookup, rest qualification and stateful coulomb counter, using only the Python standard library.
- `aps380_torcs_starter/profiles/eve_35v_ocv_candidate.json`: printed coefficients, source identity and candidate initialization policy. It is separate from the Tesla pack model and legacy current-scaling configuration.
- `aps380_torcs_starter/run_cell_soc.py`: replay of timestamped net-cell measurements with provenance and CSV outputs.
- `aps380_torcs_starter/data/mock_cell_soc_charging_positive.csv` and `profiles/mock_cell_soc_replay.json`: explicitly synthetic demonstration and configuration. They are not battery calibration or bench evidence.

Application SOC is a **fraction, 0–1**. Polynomial input is percent, converted internally. Current is amperes, charging positive and discharging negative. New replay configurations must explicitly declare `cell_current_convention: charging_positive`. Time is measurement time in seconds within a single session; the initial timestamp anchors integration and contributes no charge.

## Run the mock example

From the repository root in PowerShell:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe .\aps380_torcs_starter\run_cell_soc.py `
  --input .\aps380_torcs_starter\data\mock_cell_soc_charging_positive.csv `
  --config .\aps380_torcs_starter\profiles\mock_cell_soc_replay.json `
  --output-dir .\.local\cell-soc-demo
```

Expected: eight samples, initial SOC 50%, final SOC approximately 49.881%, and net discharge `15/3600 Ah`. The current changes sign during the example; its first discharge/charge sequence returns to the initial SOC before the final discharge. Loaded voltage changes do not reset the coulomb counter.

Outputs:

- `cell_soc.csv`: original measurement values plus SOC, unclamped SOC, interval duration, interval/cumulative signed discharge Ah and an explicit clipping flag.
- `ocv_lookup.csv`: 1001 points with SOC spacing 0.001, covering the candidate's mathematical domain.
- `summary.json`: input/config/reference SHA-256 values, caller-declared data kind, capacity basis, rest evidence, assumptions, clipping count and remaining limitations.
- Exact copies of the replay configuration and candidate reference.

The command replaces its named output files on another successful run. It validates the replay before producing output and rejects an output path that would overwrite an input/config/reference. Preserve the input CSV with the output when archiving a real experiment; the summary records its absolute path and hash.

## Measurement contract and initialization

The replay requires these CSV columns:

```csv
session_id,time_s,cell_voltage_V,net_cell_current_A,cell_temperature_C
```

Use independently measured **net cell current**, never a requested current, eLoad branch current or simulated pack current. Existing simulator/current-command CSVs do not satisfy this schema. The `mock`/`recorded` setting is an explicit provenance label supplied by the caller; the tool cannot authenticate measurement origin.

Capacity and maximum measurement gap must be explicitly configured. Document whether capacity is a datasheet assumption or a measured effective capacity. The demo's 3.5 Ah and 15-second maximum gap are mock replay choices, not live acquisition requirements or calibrated parameters.

For candidate OCV initialization the caller must supply observed rest duration, maximum absolute net current during rest, and minimum/maximum temperature during that history. The first sample must agree with that evidence. The candidate policy requires at least 3600 seconds rest, at most 0.01 A absolute current, and temperatures within 25 ± 2°C. The paper supplies the approximate temperature and one-hour rest; the current tolerance and ±2°C band are engineering qualification choices, not verified relaxation criteria or charge/discharge limits. A first sample alone does not establish rest. Firmware/live acquisition must eventually retain the evidence; this replay only checks the caller's declaration.

The lookup is checked for finite values and strict increase, then inverted using bounded linear interpolation. Values outside approximately 3.163–4.182 V are rejected; a 1e-12 V endpoint tolerance handles floating-point roundoff only. No fit extrapolation to 2.50 V or forced SOC endpoint is performed. Monotonicity and round-trip tests verify software, not experimental accuracy or coverage of the paper's raw data.

## Running current integration

For successive measurements in the same session:

```text
dt = time_now - time_previous
delta_Ah = (I_previous + I_now)/2 * dt/3600
SOC_unclamped = SOC_previous + delta_Ah/capacity_Ah
SOC = clamp(SOC_unclamped, 0, 1)
```

Trapezoidal integration assumes linear current between samples and unity charge efficiency. Sampling aliasing, current-sensor bias, charge efficiency, aging and effective capacity require physical characterization. No numerical uncertainty band is fabricated.

Duplicate/reversed timestamps, nonfinite measurements, nonpositive voltage, excessive gaps and changed sessions raise an error without advancing estimator state. Replay fails instead of bridging missing intervals. Backfill using actual measurements or explicitly reinitialize with new rest evidence; do not fill a gap with requested current. Host-time freshness, sequence checking and live transport remain future integration tasks.

SOC clipping is visible and cumulative measured charge remains recorded. Continued counting after clipping loses an absolute charge reference: treat a clipped trace as requiring review/reinitialization before trusting later absolute SOC. A bounded SOC value is not evidence of safe physical cell operation. Running voltage and temperature are logged but no protection thresholds, SOP model or automatic derating are implemented here.

## Validation and remaining work

From `aps380_torcs_starter`:

```powershell
& .\.venv\Scripts\python.exe -m unittest test_cell_soc -v
& .\.venv\Scripts\python.exe -m unittest discover -p 'test*.py'
```

The new tests cover the polynomial and inversion, endpoint handling, invalid/rest evidence, independent Ah calculations with irregular timestamps and both current signs, continuity rejection without state mutation, explicit clipping, no running reinitialization from loaded voltage, and replay outputs/source preservation. These are deterministic software checks.

Physical acceptance still requires recorded, calibrated cell measurements and a separately established SOC reference, including several rested SOC points, measured capacity, sensor-bias assessment, relevant charging/discharging and temperature conditions, and quantified SOC error. Comparing an estimator only with the same polynomial that initialized it is not independent calibration. SOP, real instrument control, independent protection and battery-dependent TORCS feedback remain separate workstreams.
