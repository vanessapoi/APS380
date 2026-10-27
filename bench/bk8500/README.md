# Original BK 8500 bench bring-up

Standalone, opt-in physical instrument tests. These tools are separate from the
live TORCS/mock controller and do not control the PSU, ESP32 or any battery.
Use Python 3.9+ on Mac or Windows. No GUI or virtual machine is needed for these
serial tests. The current project’s live software has separate requirements.

## What was demonstrated on October 27, 2026

A Mac communicated with an original BK 8500 (serial 1697510042) at 9600 baud,
address 0, through the user-confirmed IT-E132 USB-to-TTL interface. A manually
configured B&K 9115B supplied approximately 5.12 V, with its current limit set to
2 A. We exercised only 0–0.10 A of load current, at about 0.51 W maximum.
The PSU current limit was a ceiling, not a forced current or verified CC bias.

Two ten-second synthetic profiles completed. A 17.952-second recorded
TORCS-derived segment then completed 18 requests at approximately 1 Hz:

| Capture | Max requested/reported error | Mean / max command acknowledgement |
| --- | --- | --- |
| Synthetic 16:28:38 | 1 mA | 60.7 / 72.1 ms |
| Synthetic 16:31:42 | 1 mA | 63.3 / 81.1 ms |
| TORCS-derived 16:33:48 | 1.9 mA | 63.7 / 93.4 ms |

TORCS replay maximum command scheduling lateness was 5.05 ms. The input was
confirmed OFF and measured current zero after each capture; the TORCS replay also
zeroed the setpoint. The synthetic captures left a zero final setpoint by virtue
of their last request. Remote control remained enabled. PSU voltage remained
present after the eLoad input was disabled.

These are **instrument-reported** measurements sampled around half a second after
each request, not independently calibrated current measurements or electrical
settling-time measurements. No protection faults were reported. We have not
validated live streaming, 10 Hz control, physical regeneration, constant-current
PSU bias, battery operation, SOC/SOP, independent protection or vehicle feedback.

## Wiring and first settings

With power off and zero terminal voltage, connect insulated bench leads:

```text
Mac or Windows PC -> USB -> verified IT-E132 -> BK 8500 COM(TTL)
9115B OUTPUT + ----------------------------> 8500 INPUT +
9115B OUTPUT - ----------------------------> 8500 INPUT -
```

Have the lab supervisor check polarity and connections. Use a current-limited
5 V PSU only; no cell, battery, ESP32, external bias circuit or second source.
For a new first test, use a PSU current ceiling of 0.20 A, local sensing and output
initially OFF. The test requests at most 0.10 A. Enable the checked PSU manually
before replay; the tool requires terminal voltage between 4.5 and 5.5 V.

The original 8500's DB9 uses **5 V TTL**, not standard RS-232. A matching connector
alone does not establish compatibility. Do not attach an ordinary RS-232 adapter
directly. USB detection does not verify the electrical interface.

## Setup

From the repository root, create an environment and install the small bench-only
requirements. Keep your environment out of Git.

macOS:

```sh
python3 -m venv .venv-bench
.venv-bench/bin/python -m pip install -r bench/bk8500/requirements.txt
.venv-bench/bin/python bench/bk8500/replay.py --ports
```

Windows PowerShell:

```powershell
py -3 -m venv .venv-bench
.\.venv-bench\Scripts\python.exe -m pip install -r bench/bk8500/requirements.txt
.\.venv-bench\Scripts\python.exe bench/bk8500/replay.py --ports
```

Use the Python executable from your environment for the following commands.
Replace `/dev/cu.usbserial-110` with your detected port (for example `COM4` on
Windows). Port names change after reconnection. Default baud is 9600, address 0;
`--baud` and `--address` are configurable.

Read-only connection check (does not change settings):

```sh
python bench/bk8500/replay.py --identify --port /dev/cu.usbserial-110 --confirm-ttl
```

Prepare an offline plan **without opening a port**:

```sh
python bench/bk8500/replay.py
python bench/bk8500/replay.py --profile synthetic
```

Review `planned_profile.csv` in the printed run folder. Execute only after checking
the PSU-only wiring and limits, with the front-panel OFF control accessible:

```sh
python bench/bk8500/replay.py --run --port /dev/cu.usbserial-110 --confirm-ttl --confirm-psu-only
python bench/bk8500/replay.py --profile synthetic --run --port /dev/cu.usbserial-110 --confirm-ttl --confirm-psu-only
```

Every run writes a new folder under `bench/bk8500/runs/` (ignored by Git), with a
plan, metadata, timestamped measurements and result. `--output` chooses another
new folder. Reviewed evidence can be copied into `evidence/` and committed.
No instrument runs automatically at import, test discovery or default execution.

On normal completion or a caught error/interrupt, the tool attempts input OFF,
zeroes the CC setpoint, and checks readback. It retains remote mode and does not
restore prior settings. If communication is lost, software cannot guarantee
shutdown: use the physical controls and disable the PSU. There is no independent
hardware watchdog here. Do not use this tool on a battery or infer that a timeout
makes the equipment safe. The PSU remains manually controlled.

## TORCS scaling and sign conventions

The default is the existing historical
`aps380_torcs_starter/output/torcs_comparison/segment_03/candidate_smoothed_scaled/current_profile.csv`.
It contains 817 samples from one continuous segment, with maximum timestamp gap
22.002 ms. We reject resets, duplicate times, gaps above 30 ms, nonfinite values
and profiles longer than 60 seconds rather than stitching sessions.

This **historical** capture is discharge-positive. Its exact SHA-256 is recognized
in the tool. Your teammate's current prototype instead uses **charging-positive
cell current**, `I_cell = I_PSU - I_eLoad`; native pack telemetry remains
discharge-positive. Other source files require an explicit `--source-sign`:

```sh
python bench/bk8500/replay.py --source path/to/current_profile.csv --source-sign charging-positive
```

The source must contain `time_s` and `cell_current_unclamped_A`. Convert its sign
once to discharge-positive internally. Hold each source value until the next
source timestamp. Integrate `max(0, I_source)` over each one-second bin and divide
by actual bin duration. Retain the final partial bin and original elapsed time.
Then use one fixed gain:

```text
I_request = round_to_0.1mA(gain * positive_time_average)
gain = 0.10 A / largest_positive_time_average
```

For the captured TORCS segment the gain was 0.035485586. This is an additional
**bench amplitude reduction**, not a calibrated vehicle-to-cell conversion. The
historical model already assumed mass 1150 kg, 3.6 V / 3 Ah cell, 75 kWh equivalent
pack, experiment scale 0.2 and centered 0.2-second offline smoothing. Source
parameters and hash are saved in metadata; original CSVs are unchanged.

Negative portions are removed **before** averaging; bins containing both signs
can retain a small positive request even when their signed mean is negative.
This reproduces averaged discharge demand, not the exact signed waveform or its
net energy. We command nonnegative **eLoad branch current**, not project net cell
current. There is no cell or PSU bias mapping in this bench setup. Centered
smoothing, whole-file peak scaling and look-ahead averaging are offline operations;
a causal streaming implementation needs separate design and validation. The observed
roughly 64 ms command round trip also exceeds the mock controller’s 20 ms I/O
budget; do not plug this driver into that worker without revisiting timing,
scheduling, stale-data handling and shutdown behaviour.

## Tests and provenance

```sh
python -m unittest discover -s bench/bk8500 -p 'test_*.py' -v
```

The 12 bench tests passed on Python 3.9.6 during repository integration. The
wider starter suite could not load on that interpreter because existing code
uses Python 3.10+ type syntax; it was not claimed to pass in this session.

Tests use simulated transports/devices. They verify protocol units/checksums,
current limits, sign conversion, malformed timestamps, reproduction of the actual
recorded plan, and cleanup after measurement failure. They do not open ports.
The portable replay is refactored from the executed lab script; its hardware path
has not been rerun after this refactor.

`evidence/2026-10-27/` preserves the actual CSV/JSON captures and the original
executed TORCS script (an archival snapshot with Mac-specific paths; use the
portable tool above for new work). Original metadata preserves original local
paths. Early one-off identity and constant-current checks were visible in the
session but had no saved CSV; we have not manufactured logs for them.

Manufacturer references:
[8500 manual](https://bkpmedia.s3.amazonaws.com/downloads/manuals/en-us/85xx_manual.pdf)
(pp. 10, 46, 53–56, 68–69) documents TTL, 26-byte packets, DTR/RTS and command units;
[9115 series manual](https://bkpmedia.s3.us-west-1.amazonaws.com/downloads/manuals/en-us/9115_Series_manual.pdf)
documents the PSU output and current-limit operation.
