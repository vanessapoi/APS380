# APS380

Vehicle telemetry and battery-demand modelling project.

## Workspace layout

- `aps380_torcs_starter/`: existing Python telemetry processing, model, tests and project context.
- `scripts/setup_torcs.py`: reproducible TORCS 1.3.10 source setup.
- `docs/torcs-setup.md`: source provenance, setup and build boundaries.
- `external/torcs-1.3.10/`: complete upstream simulator distribution, installed locally and ignored by Git.
- `APS380.code-workspace`: open this file in VS Code for the APS380 workspace.

## Get started

See [the Python project README](aps380_torcs_starter/README.md) for model setup and use.

Install the TORCS source using an existing download:

```bash
python3 scripts/setup_torcs.py --archive ~/Downloads/torcs-1.3.10.tar.bz2
```

Or download the pinned distribution:

```bash
python3 scripts/setup_torcs.py
```

The script verifies the archive before extraction and refuses to overwrite an existing source directory. See [TORCS setup](docs/torcs-setup.md) for details. Downloading source does not build TORCS or implement live telemetry integration.
