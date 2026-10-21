# Automated EV course validation

Two speed holds, lift-off regeneration, isolated friction braking, a stationary hold, and a complete course are checked from recorded native telemetry.

| Run | 30 km/h hold | 50 km/h hold | Stopped | Net pack energy | Gates |
| --- | --- | --- | --- | --- | --- |
| 1 | 13.96 s | 12.00 s | 6.00 s | 558.040 Wh | Pass |
| 2 | 13.96 s | 12.00 s | 6.00 s | 558.040 Wh | Pass |

Net-energy spread: 0.0% across 2 run(s); at least two runs are needed to assess repeatability.

Each run folder contains the raw native CSV, effective car XML, frozen vehicle profile, driver trace, protocol gates, detailed plot, pack analysis, and readiness audit. Source and binary hashes are in summary.json.

The driver is a deterministic centerline follower with feedback speed control, not a racing optimizer. A hold requires contiguous native samples within ±0.2 m/s of target, |acceleration| ≤0.15 m/s², lateral speed <0.3 m/s and at least 20 m of straight road remaining. Sample gaps over 50 ms break a hold. Damage and departures from the road abort the run.

These are internally verified results for the configured model. Battery efficiency, capacity, regeneration and handling assumptions remain unvalidated against an independent real Tesla.
