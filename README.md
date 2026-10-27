# APS380

Vehicle telemetry and battery-demand modelling project, including the full TORCS 1.3.10 distribution for team development.

## Workspace layout

- `aps380_torcs_starter/`: Python telemetry processing, model, tests and project context.
- `external/torcs-1.3.10/`: version-controlled TORCS source, assets, dependencies, tests and upstream license notices. Make and commit simulator changes here.
- `scripts/setup_torcs.py`: optional upstream archive verification/recovery utility; normal clones already contain TORCS.
- `docs/torcs-setup.md`: source provenance, build boundaries and collaboration instructions.
- `APS380.code-workspace`: open this file in VS Code for the APS380 workspace.

## Get started

Clone this repository and open `APS380.code-workspace`. The full TORCS distribution is included; no separate source download is required. The repository includes approximately 2.4 GB of upstream files, so allow time and disk space for the first clone.

See [the Python project README](aps380_torcs_starter/README.md) for model setup and use, and [TORCS setup](docs/torcs-setup.md) for simulator build guidance. Source availability does not imply a validated simulator build or live telemetry integration.

For the candidate EVE cell OCV reference and offline SOC replay, see [cell SOC estimation](docs/cell-soc.md) and [the source-paper review](docs/ocv-paper-review.md). Mock checks verify the software; experimental cell calibration remains pending.

For native real-time telemetry, fixed cell scaling, the in-game metrics HUD and current-limit warnings, optional desktop monitor and paced AI/manual G29 trials, see [live TORCS setup and timing validation](docs/torcs-live.md). Physical instrument control remains unimplemented.

## Collaborating

Create a feature branch, edit the Python project or `external/torcs-1.3.10/`, run the relevant checks, and push the branch for review. Keep generated build output and local environments out of commits. Preserve upstream license notices. Work in this repository's TORCS copy, rather than the separate copy in Downloads.

## Mock instrument integration

The live telemetry pipeline can optionally drive an explicitly armed, in-memory
PSU/eLoad coordinator. See [mock experiment and live launch instructions](docs/mock-instruments.md).
No physical instruments or battery are operated.
