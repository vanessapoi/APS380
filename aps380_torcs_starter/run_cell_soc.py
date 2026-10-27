"""Offline cell-measurement replay. This entry point never controls hardware."""
import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from cell_soc import CellMeasurement, CoulombCounter, RestEvidence, load_reference, DEFAULT_REFERENCE
from prototype_current_config import CELL_CURRENT_CONVENTION, current_metadata

FIELDS = ("session_id", "time_s", "cell_voltage_V", "net_cell_current_A", "cell_temperature_C")


def read_measurements(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            raise ValueError(f"Cell measurement CSV requires {', '.join(FIELDS)}")
        rows = []
        for line, row in enumerate(reader, start=2):
            try:
                rows.append(CellMeasurement(row["session_id"], **{key: float(row[key]) for key in FIELDS[1:]}))
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid measurement at CSV line {line}: {error}") from error
    if len(rows) < 2:
        raise ValueError("At least two cell measurements are required")
    return rows


def replay(measurements, reference, config):
    if config.get('cell_current_convention') != CELL_CURRENT_CONVENTION:
        raise ValueError('Measurement replay must explicitly declare charging_positive current')
    if config["data_kind"] not in ("mock", "recorded"):
        raise ValueError("data_kind must explicitly be mock or recorded")
    if not isinstance(config["capacity_basis"], str) or not config["capacity_basis"].strip():
        raise ValueError("Document capacity_basis (nominal or measured, and source)")
    evidence = RestEvidence(**config["rest_evidence"])
    counter = CoulombCounter.from_rest(reference, measurements[0], evidence,
                                       capacity_Ah=config["capacity_Ah"], max_gap_s=config["max_gap_s"])
    estimates = [counter.initial_estimate()]
    for measurement in measurements[1:]:
        estimates.append(counter.update(measurement))
    return [dict(asdict(measurement), **asdict(estimate), **current_metadata())
            for measurement, estimate in zip(measurements, estimates)]


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def process(input_path, config_path, output_dir, reference_path=DEFAULT_REFERENCE):
    input_path, config_path, output_dir, reference_path = map(Path, (input_path, config_path, output_dir, reference_path))
    names = ("cell_soc.csv", "ocv_lookup.csv", "summary.json", "replay_config.json", "ocv_reference.json")
    sources = {path.resolve() for path in (input_path, config_path, reference_path)}
    if any((output_dir / name).resolve() in sources for name in names):
        raise ValueError("Output would overwrite an input or reference file")
    # Keep exact input bytes for provenance; refuse changes during processing.
    paths = (input_path, config_path, reference_path)
    original = {path: path.read_bytes() for path in paths}
    config = json.loads(original[config_path].decode("utf-8"))
    reference = load_reference(reference_path)
    measurements = read_measurements(input_path)
    rows = replay(measurements, reference, config)
    if any(path.read_bytes() != original[path] for path in paths):
        raise ValueError("Replay inputs changed during processing")
    summary = {
        **current_metadata(),
        "status": "candidate_reference_only; cell accuracy not experimentally validated",
        "data_kind": config["data_kind"],
        "measurement_provenance": "Caller label; replay does not authenticate a physical measurement source",
        "reference_id": reference.reference_id,
        "input_file": str(input_path.resolve()),
        "input_sha256": hashlib.sha256(original[input_path]).hexdigest(),
        "config_sha256": hashlib.sha256(original[config_path]).hexdigest(),
        "reference_sha256": hashlib.sha256(original[reference_path]).hexdigest(),
        "capacity_Ah": config["capacity_Ah"],
        "capacity_basis": config["capacity_basis"],
        "rest_evidence": config["rest_evidence"],
        "max_gap_s": config["max_gap_s"],
        "integration": "Trapezoidal measured net current; linear intersample current assumption; unity charge efficiency",
        "session_id": measurements[0].session_id,
        "samples": len(rows),
        "duration_s": rows[-1]["time_s"] - rows[0]["time_s"],
        "initial_soc": rows[0]["soc"],
        "final_soc": rows[-1]["soc"],
        "net_discharged_Ah": rows[-1]["net_discharged_Ah"],
        "boundary_clipped_samples": sum(row["boundary_clipped"] for row in rows),
        "lookup_voltage_range_V": [reference.lookup[0][1], reference.lookup[-1][1]],
        "limitations": ["No measured uncertainty or cell calibration", "Caller supplies observed rest history",
                        "No SOP, instrument commands, physical protection or live TORCS feedback",
                        "SOC bounds are estimator bookkeeping, not evidence that cell limits were respected",
                        "Running voltage and temperature are logged, not interpreted as protection limits"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "cell_soc.csv", rows)
    write_csv(output_dir / "ocv_lookup.csv", [{"soc": soc, "ocv_V": voltage} for soc, voltage in reference.lookup])
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_dir / "replay_config.json").write_bytes(original[config_path])
    (output_dir / "ocv_reference.json").write_bytes(original[reference_path])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args()
    try:
        summary = process(args.input, args.config, args.output_dir, args.reference)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Cell SOC replay failed: {error}\n")
    print(f"{summary['data_kind']} replay: {summary['samples']} samples; "
          f"SOC {summary['initial_soc']:.3%} -> {summary['final_soc']:.3%}")
    print("Candidate OCV reference only; experimental cell validation remains pending.")


if __name__ == "__main__":
    main()
