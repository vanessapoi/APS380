# /***************************************************************************
#     file                 : radius_batch.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Resumable orchestration of the existing radius tools and native generators."""

import hashlib
import json
import math
import os
import shutil
import signal
import subprocess  # nosec B404 - local authoring executables, argv lists, no shell
import sys
import tempfile
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

from torcs_track_tools.core.artifact_io import file_sha256 as digest
from torcs_track_tools.core.artifact_io import read_json, write_json
from torcs_track_tools.core.defaults import (
    DEFAULT_REPAIR_CURVE_RADIUS_M,
    DEFAULT_TARGET_ANG_DEG,
    DEFAULT_TARGET_DX_M,
    DEFAULT_TARGET_DY_M,
    DEFAULT_TARGET_DZ_M,
)
from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.radius_audit import audit_track, audit_tree, repair_preflight
from torcs_track_tools.core.radius_repair import segment_blocks
from torcs_track_tools.core.track_loader_probe import relocated_entities
from torcs_track_tools.core.track_xml import child_section, get_attstr, parse_xml_readonly
from torcs_track_tools.core.trackgen import parse_trackgen_output


@contextmanager
def exclusive_file(path):
    """OS lock survives neither process death nor exceptions; file may remain."""
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def execute(command, cwd, log, timeout):
    with log.open("wb") as output:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, **options) as process:  # nosec B603 - trusted tool argv, no shell
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate_tree(process, output)
                raise
    if code:
        raise RuntimeError(f"Command failed ({code}); see {log.name}")


def terminate_tree(process, output):
    if os.name == "nt":
        taskkill = str(Path(os.environ["SystemRoot"])/"System32/taskkill.exe")
        subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], stdout=output, stderr=subprocess.STDOUT,
                       timeout=30, check=False)  # nosec B603 - OS utility, numeric child PID, no shell
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


def closure_metrics(log):
    text = log.read_text(encoding="utf-8", errors="replace")
    return parse_trackgen_output(text)


def check_closure(log):
    metrics = closure_metrics(log)
    for key, limit in (("delta_x", DEFAULT_TARGET_DX_M), ("delta_y", DEFAULT_TARGET_DY_M),
                       ("delta_z", DEFAULT_TARGET_DZ_M), ("delta_ang_deg", DEFAULT_TARGET_ANG_DEG)):
        if not math.isfinite(metrics[key]) or abs(metrics[key]) > limit:
            raise ValueError(f"{log.name}: {key} closure {metrics[key]} exceeds {limit}")
    return metrics


def track_path(runtime, key):
    parts = key.split("/")
    if len(parts) != 2 or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
        raise ValueError(f"Expected category/name: {key}")
    path = (runtime/"tracks"/parts[0]/parts[1]/(parts[1]+".xml")).resolve()
    if not path.is_relative_to((runtime/"tracks").resolve()) or not path.is_file():
        raise ValueError(f"Invalid track path: {key}")
    return path


def visual_target(source):
    root = parse_xml_readonly(source).getroot()
    category = get_attstr(child_section(root, "Header"), "category", source.parent.parent.name)
    if category != source.parent.parent.name:
        raise ValueError("Track header category differs from its runtime directory")
    graphic = child_section(root, "Graphic")
    name = source.stem
    target = get_attstr(graphic, "3d description", name+".ac")
    if target not in (name+".ac", name+".acc"):
        raise ValueError(f"Nonstandard visual target {target}; manual asset review required")
    return target


def verify_backup(source, backup, replacements=()):
    with zipfile.ZipFile(backup) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            with archive.open(info) as stream:
                expected = hashlib.file_digest(stream, "sha256").hexdigest()
            current = source.parent/info.filename
            if not current.is_file() or digest(current) != expected:
                raise ValueError(f"Live input changed since backup: {info.filename}")
        original_names = {info.filename for info in archive.infolist() if not info.is_dir()}
    for relative in replacements:
        if relative not in original_names and (source.parent/relative).exists():
            raise ValueError(f"New live output appeared since backup: {relative}")


def validate_curve_radius(radius):
    if radius is not None and not 0 < radius <= MAX_TORCS_RADIUS_M:
        raise ValueError(f"Curve radius must be in (0, {MAX_TORCS_RADIUS_M:g}] metres")
    return radius


class Batch:
    def __init__(self, runtime, work, tracks, resume=False, deploy=False, workers=2, timeout=1800, clearance_acceptances=None, curve_radius=None):
        self.runtime, self.work = runtime.resolve(), work.resolve()
        self.deploy, self.workers, self.timeout = deploy, workers, timeout
        self.curve_radius = validate_curve_radius(curve_radius)
        self.mutex, self.merge_mutex = threading.Lock(), threading.Lock()
        if self.work.is_relative_to(self.runtime/"tracks"):
            raise ValueError("Batch work directory must be outside the live track collection")
        if self.work.exists() and not resume:
            raise ValueError("Work directory already exists; use a new directory or --resume")
        self.work.mkdir(parents=True, exist_ok=resume)
        self.manifest = self.work/"manifest.json"
        if resume:
            self.data = read_json(self.manifest)
            if self.data["runtime"] != str(self.runtime):
                raise ValueError("Resume runtime differs from original batch")
            if tracks and not set(tracks) <= set(self.data["tracks"]):
                raise ValueError("Resume selection contains tracks outside the original batch")
        else:
            if self.manifest.exists():
                raise ValueError("Batch already exists; use --resume")
            self.data = {"schema": 1, "id": uuid.uuid4().hex[:12], "runtime": str(self.runtime),
                         "track_dll_sha256": digest(self.runtime/"modules/track/track.dll"),
                         "tracks": {key: {"status": "pending", "attempt": 0} for key in tracks}}
            self.save()
        if self.data["track_dll_sha256"] != digest(self.runtime/"modules/track/track.dll"):
            raise ValueError("Track DLL changed; start a new batch")
        self.keys = list(tracks) if tracks else list(self.data["tracks"])
        self.clearance_acceptances = selected_clearance_acceptances(clearance_acceptances, self.keys)

    def save(self):
        self.data["summary"] = status_counts(self.data["tracks"])
        write_json(self.manifest, self.data)

    def update(self, key, **fields):
        with self.mutex:
            self.data["tracks"][key].update(fields)
            self.save()

    def command(self, key, phase, args, directory):
        self.update(key, phase=phase)
        print(f"{key}: {phase}", flush=True)
        execute(args, self.runtime, directory/(phase+".log"), self.timeout)

    def python(self, key, phase, module, args, directory):
        self.command(key, phase, [sys.executable, "-m", "torcs_track_tools.cli."+module, *map(str, args)], directory)

    def fit_track(self, key, source, directory):
        record = self.data["tracks"][key]
        old = Path(record["fit_dir"]) if record.get("fit_dir") else None
        if old and (old/"candidate.xml").is_file() and read_json(old/"report.json")["accepted"]:
            self.check_fit_report(key, old)
            self.update(key, candidate_sha256=digest(old/"candidate.xml"))
            return old
        attempt = record["attempt"]+1
        output = directory/f"fit-{attempt:03d}"
        self.update(key, attempt=attempt, fit_dir=str(output))
        args = ["--input", source, "--runtime-dir", self.runtime, "--all-over-limit", "--method", "auto",
                "--polish-closure", "--work-dir", output]
        args += self.fit_resume_arguments(old)
        self.python(key, f"fit-{attempt:03d}", "repair_track_radii", args, directory)
        if not read_json(output/"report.json")["accepted"] or not (output/"candidate.xml").is_file():
            raise ValueError("Fitter did not produce an accepted candidate")
        self.check_fit_report(key, output)
        self.update(key, candidate_sha256=digest(output/"candidate.xml"))
        return output

    def fit_resume_arguments(self, old):
        checkpoint = next((old/name for name in ("report.json", "fit-progress.json") if (old/name).is_file()), None) if old else None
        previous_radius = read_json(checkpoint).get("curve_radius_m", DEFAULT_REPAIR_CURVE_RADIUS_M) if checkpoint else DEFAULT_REPAIR_CURVE_RADIUS_M
        radius = self.curve_radius if self.curve_radius is not None else previous_radius
        args = ["--curve-radius", radius]
        if checkpoint and radius == previous_radius:
            args += ["--resume-report", checkpoint]
        return args

    def check_fit_report(self, key, output):
        report = read_json(output/"report.json")
        if report.get("accepted") is not True:
            raise ValueError("Saved fit report is not accepted")
        if report["source_sha256"] != self.data["tracks"][key]["source_sha256"]:
            raise ValueError("Fit report does not match the batch input")
        if report["track_dll_sha256"] != self.data["track_dll_sha256"]:
            raise ValueError("Fit report uses a different track DLL")
        if self.curve_radius is not None and report.get("curve_radius_m") != self.curve_radius:
            raise ValueError("An accepted fit already exists with a different curve radius")
        # Older completed batches stored the digest only in the manifest. Do
        # not trust an unhashed candidate after a crash between fit and update.
        expected = report.get("candidate_sha256") or self.data["tracks"][key].get("candidate_sha256")
        if not expected:
            raise ValueError("Saved candidate has no validation hash; revalidate it before reuse")
        if digest(output/"candidate.xml") != expected:
            raise ValueError("Saved candidate was modified after fitting")

    def validate_candidate(self, key, source, fit_dir, directory):
        candidate = fit_dir/"candidate.xml"
        if audit_track(candidate)["segments"]:
            raise ValueError("Candidate still has oversized radii")
        for tool, report in (("adjust_side_clearance", "side-clearance"), ("adjust_side_overlap", "side-overlap")):
            self.python(key, report, tool, ["--input", candidate, "--dry-run", "--report", directory/(report+".json")], directory)
        accepted = self.check_existing_clearance(key, source, candidate, directory)
        check_side_reports(directory, accepted)
        model = directory/"model"
        model.mkdir(exist_ok=True)
        xml = model/source.name
        xml.write_text(relocated_entities(candidate.read_bytes().decode("utf-8"), source.parent, model), encoding="utf-8", newline="")
        category, name = key.split("/")
        common = [str(self.runtime/"trackgen.exe"), "-c", category, "-n", name, "-i", model.as_posix()]
        self.command(key, "closure", [*common, "-z"], directory)
        metrics = check_closure(directory/"closure.log")
        if metrics["pits"] != read_json(fit_dir/"report.json")["pit_count"]:
            raise ValueError("Trackgen pit count differs from validated model")
        self.update(key, closure=metrics)
        return model, common

    def check_existing_clearance(self, key, source, candidate, directory):
        names = self.clearance_acceptances.get(key)
        if not names:
            return []
        baseline_path = directory/"baseline-side-clearance.json"
        self.python(key, "baseline-side-clearance", "adjust_side_clearance",
                    ["--input", source, "--dry-run", "--report", baseline_path], directory)
        accepted = accept_unchanged_clearance(source, candidate, read_json(baseline_path),
                                              read_json(directory/"side-clearance.json"), names)
        write_json(directory/"accepted-clearance.json", {"source_sha256": digest(source), "conditions": accepted})
        self.update(key, accepted_baseline_clearance=accepted)
        return accepted

    def generate(self, key, source, model, common, directory, target):
        self.command(key, "geometry", [*common, "-o", model.as_posix(), "-a", "-q"], directory)
        self.command(key, "raceline", [*common, "-o", model.as_posix(), "-r", "-q"], directory)
        name = source.stem
        if target.endswith(".acc"):
            with self.merge_mutex, exclusive_file(self.runtime/".radius-batch-accc.lock"):
                args = [str(self.runtime/"accc.exe"), "-g", str(model/target), "-l0", str(model/(name+".ac")),
                        "-l1", str(model/(name+"-trk-raceline.ac")), "-d3", "1000", "-d2", "500", "-d1", "300", "-S", "300", "-es"]
                self.command(key, "merge", args, directory)
        self.python(key, "labels", "render_labeled_segments_svg", ["--track-xml", model/source.name, "--output", model/"segments-labeled.svg"], directory)
        self.python(key, "map", "render_track_map", ["--track-xml", model/source.name, "--output", model/(name+".png"), "--svg-output", model/"track-map.svg"], directory)
        files = generated_files(name, target)
        for filename in files:
            if not (model/filename).is_file() or (model/filename).stat().st_size == 0:
                raise ValueError(f"Missing/empty generated asset {filename}")
        return files

    def process(self, key):
        try:
            if self.data["tracks"][key]["status"] in ("deployed", "already_clear"):
                return
            track_path(self.runtime, key)
            with exclusive_file(self.runtime/(".radius-track-"+key.replace("/", "__")+".lock")):
                self.process_track(key)
        except (Exception, SystemExit) as error:
            self.update(key, status="failed", error=str(error))
            print(f"{key}: FAILED: {error}", flush=True)

    def process_track(self, key):
        record = self.data["tracks"][key]
        if record["status"] == "deployed":
            return
        source = track_path(self.runtime, key)
        directory = self.work/key.replace("/", "__")
        directory.mkdir(exist_ok=True)
        if (directory/"deployment.json").exists():
            if recover_deployment(source, Path(record["fit_dir"])/"before.zip", directory/"deployment.json"):
                self.update(key, status="deployed", deployed_xml_sha256=digest(source))
                (directory/"deployment.json").unlink()
                return
        current_hash = digest(source)
        if record.get("source_sha256", current_hash) != current_hash:
            raise ValueError("Source XML changed since the batch started")
        if record["status"] == "staged":
            self.finish_staged(key, source, directory)
            return
        audit = audit_track(source)
        if not audit["segments"]:
            self.update(key, status="already_clear")
            return
        preflight = repair_preflight(source, [s["name"] for s in audit["segments"]])
        if preflight["status"] == "blocked":
            self.update(key, status="blocked", preflight=preflight)
            return
        target = visual_target(source)
        self.update(key, status="running", source_sha256=current_hash, error=None, validation_failures=[],
                    accepted_baseline_clearance=[], segment_count=len(audit["segments"]))
        fit_dir = self.fit_track(key, source, directory)
        model, common = self.validate_candidate(key, source, fit_dir, directory)
        files = self.generate(key, source, model, common, directory, target)
        staged = [*files, "segments-labeled.svg", "track-map.svg"]
        self.update(key, status="staged", fit_report=read_json(fit_dir/"report.json"),
                    generated_files=files, staged_hashes={name: digest(model/name) for name in staged})
        self.finish_staged(key, source, directory)

    def finish_staged(self, key, source, directory):
        record = self.data["tracks"][key]
        model, fit_dir = directory/"model", Path(record["fit_dir"])
        self.check_fit_report(key, fit_dir)
        for name, expected in record["staged_hashes"].items():
            if digest(model/name) != expected:
                raise ValueError(f"Staged asset was modified: {name}")
            if Path(name).suffix in (".ac", ".acc"):
                validate_model(model/name)
        if self.deploy:
            self.update(key, status="deploying")
            deploy_track(source, fit_dir, model, record["generated_files"], directory, self.data["id"],
                         verify=lambda: self.verify_live(key, source, directory, record["closure"]["pits"]))
            self.update(key, status="deployed", deployed_xml_sha256=digest(source))
            (directory/"deployment.json").unlink(missing_ok=True)
        print(f"{key}: {self.data['tracks'][key]['status']}", flush=True)

    def verify_live(self, key, source, directory, pits):
        category, name = key.split("/")
        self.command(key, "deployed-closure", [str(self.runtime/"trackgen.exe"), "-c", category, "-n", name, "-z"], directory)
        metrics = check_closure(directory/"deployed-closure.log")
        if metrics["pits"] != pits:
            raise ValueError("Deployed pit count changed")
        report_dir = source.parent/"source"/("radius-batch-"+self.data["id"])
        shutil.copy2(directory/"deployed-closure.log", report_dir/"deployed-closure.log")

    def run(self):
        with exclusive_file(self.work/".batch.lock"):
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [pool.submit(self.process, key) for key in self.keys]
                for future in as_completed(futures):
                    future.result()
            self.save()
            counts = self.data["summary"]
            write_summary(self.work/"summary.md", self.data)
        print(json.dumps(counts, indent=2), flush=True)
        return int(bool(counts.get("failed") or counts.get("blocked")))

    def diagnose(self):
        """Measure original seams and summarize rejected fits without retrying."""
        with exclusive_file(self.work/".batch.lock"):
            for key in self.keys:
                record = self.data["tracks"][key]
                if record["status"] != "failed":
                    continue
                category, name = key.split("/")
                directory = self.work/key.replace("/", "__")
                self.command(key, "baseline-closure", [str(self.runtime/"trackgen.exe"), "-c", category, "-n", name, "-z"], directory)
                details = {"baseline_closure": closure_metrics(directory/"baseline-closure.log")}
                report = Path(record["fit_dir"])/"report.json" if record.get("fit_dir") else None
                if report is not None and report.exists():
                    details["fit_report"] = read_json(report)
                    details["validation_failures"] = details["fit_report"].get("failures", [])
                self.update(key, **details)
            write_summary(self.work/"summary.md", self.data)
            write_diagnostics(self.work/"diagnostics.md", self.data)
        print(f"Wrote {self.work/'diagnostics.md'}", flush=True)
        return 0


def status_counts(tracks):
    result = {}
    for record in tracks.values():
        result[record["status"]] = result.get(record["status"], 0)+1
    return result


def selected_clearance_acceptances(acceptances, keys):
    result = acceptances or {}
    if not result.keys() <= set(keys):
        raise ValueError("Clearance acceptance must identify a selected batch track")
    return result


def write_summary(path, manifest):
    lines = ["# Radius repair batch", "", f"Batch ID: `{manifest['id']}`", "",
             ", ".join(f"{status}: {count}" for status, count in manifest["summary"].items()), "",
             "| Track | Status | Repaired curves | Closure X / Y (mm) | Details |",
             "|---|---|---:|---|---|"]
    for key, record in manifest["tracks"].items():
        closure = record.get("closure")
        xy = f"{closure['delta_x']*1000:.3f} / {closure['delta_y']*1000:.3f}" if closure else ""
        detail = record.get("error") or ""
        if record["status"] == "failed" and record.get("validation_failures"):
            detail = "; ".join(record["validation_failures"])
        if record.get("accepted_baseline_clearance"):
            detail += " Accepted unchanged baseline clearance: " + ", ".join(c["segment"] for c in record["accepted_baseline_clearance"])
        if record["status"] == "blocked":
            detail = "; ".join(sorted({item["reason"] for item in record["preflight"]["blocked_segments"]}))
        detail = detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {key} | {record['status']} | {record.get('segment_count', '')} | {xy} | {detail} |")
    lines += ["", "Full metrics, hashes and phase logs are retained beside this summary.",
              "Successful deployments retain before.zip and reports under each track's source/radius-batch-<batch-id>/.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_diagnostics(path, manifest):
    lines = ["# Radius batch failure diagnostics", "",
             "Original and candidate seams are separate: preserving an existing gap is not closing it.", "",
             "| Track | Original X / Y (mm) | Candidate max X / Y (mm) | Untouched vertices (mm) | Failures |",
             "|---|---|---|---:|---|"]
    for key, record in manifest["tracks"].items():
        if record["status"] != "failed":
            continue
        old = record.get("baseline_closure", {})
        report = record.get("fit_report", {})
        gaps = report.get("road_edge_closure_m", [[0., 0.]])
        xy = [max(abs(gap[axis]) for gap in gaps)*1000 for axis in (0, 1)]
        shift = report.get("untouched_vertex_shift_m", 0.)*1000
        failures = "; ".join(record.get("validation_failures", [])).replace("|", "\\|")
        lines.append(f"| {key} | {old.get('delta_x', 0)*1000:.3f} / {old.get('delta_y', 0)*1000:.3f} | {xy[0]:.3f} / {xy[1]:.3f} | {shift:.3f} | {failures} |")
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def generated_files(name, target):
    files = [name+suffix for suffix in (".ac", "-trk.ac", "-msh.ac", "-trk-raceline.ac", ".png")]
    if target.endswith(".acc"):
        files.append(target)
    return files


def validate_model(path):
    """Catch truncated/nonfinite models and invalid surface vertex references."""
    vertices = faces = materials = 0
    count = 0
    with path.open(encoding="utf-8") as stream:
        if stream.readline().strip() != "AC3Db":
            raise ValueError(f"Invalid generated model header: {path.name}")
        for line in stream:
            fields = line.split()
            if not fields:
                continue
            keyword = fields[0]
            if keyword == "MATERIAL":
                materials += 1
            elif keyword == "OBJECT":
                count = 0
            elif keyword == "numvert":
                count = int(fields[1])
                validate_vertices(stream, count)
                vertices += count
            elif keyword == "mat" and not 0 <= int(fields[1]) < materials:
                raise ValueError(f"Invalid material reference: {path.name}")
            elif keyword == "refs":
                validate_references(stream, int(fields[1]), count)
                faces += 1
    if vertices <= 0 or faces <= 0:
        raise ValueError(f"Generated model contains no geometry: {path.name}")


def validate_vertices(stream, count):
    if count < 0:
        raise ValueError("Negative vertex count")
    for _ in range(count):
        values = [float(v) for v in stream.readline().split()]
        if len(values) < 3 or not all(math.isfinite(v) for v in values):
            raise ValueError("Truncated or nonfinite model vertex")


def validate_references(stream, count, vertices):
    if count <= 0:
        raise ValueError("Invalid surface reference count")
    for _ in range(count):
        fields = stream.readline().split()
        if len(fields) < 3 or not 0 <= int(fields[0]) < vertices:
            raise ValueError("Invalid model vertex reference")
        if not all(math.isfinite(float(v)) for v in fields[1:]):
            raise ValueError("Nonfinite texture coordinates")


def check_side_reports(directory, accepted_clearance=()):
    clearance = read_json(directory/"side-clearance.json")
    overlap = read_json(directory/"side-overlap.json")
    # A dry-run must propose no geometry edits. Exact report fields are emitted
    # by the existing validators, not inferred from subprocess success alone.
    expected = {(item["segment"], item["side"]) for item in accepted_clearance}
    actual = {(item["segment"], item["side"]) for item in clearance["anomalies"]}
    if actual != expected or clearance["anomaly_count"] != len(expected) or clearance["applied_runs"]:
        raise ValueError("Side-clearance anomalies require review")
    if overlap["overlap_count"] or overlap["proposal_count"] or overlap["final_overlap_count"]:
        raise ValueError("Side overlaps require review")


def clearance_signature(item):
    fields = ("segment", "side", "type", "radius", "start_radius", "end_radius", "arc_deg",
              "old_side_width", "old_side_start_width", "old_side_end_width", "border_width",
              "clearance_margin", "deficit", "unresolved_deficit", "protected")
    return tuple(item[key] for key in fields)


def accept_unchanged_clearance(source, candidate, baseline, current, names):
    """Explicit per-segment exception; never waive new/worsened/edited geometry."""
    old_blocks = segment_blocks(source.read_bytes().decode("utf-8"))
    new_blocks = segment_blocks(candidate.read_bytes().decode("utf-8"))
    original = {(item["segment"], item["side"]): item for item in baseline["anomalies"]}
    accepted = []
    for item in current["anomalies"]:
        name, side = item["segment"], item["side"]
        previous = original.get((name, side))
        if name not in names or previous is None:
            raise ValueError(f"Unapproved/new clearance anomaly: {name}")
        if old_blocks.get(name) != new_blocks.get(name):
            raise ValueError(f"Clearance exception section was edited: {name}")
        if clearance_signature(item) != clearance_signature(previous):
            raise ValueError(f"Baseline clearance condition changed: {name}")
        remaining = item["clearance_margin"]-item["deficit"]
        if not math.isfinite(remaining) or remaining <= 0:
            raise ValueError(f"Baseline exception cannot accept nonpositive physical clearance: {name}")
        accepted.append({"segment": name, "side": side, "physical_clearance_m": remaining,
                         "configured_margin_m": item["clearance_margin"], "existing_deficit_m": item["deficit"],
                         "original_section_sha256": hashlib.sha256(old_blocks[name].encode("utf-8")).hexdigest()})
    return accepted


def recover_deployment(source, backup, journal):
    state = read_json(journal)
    if state.get("committed"):
        for relative, expected in state["hashes"].items():
            if digest(source.parent/relative) != expected:
                raise ValueError("Completed deployment was subsequently modified; manual review required")
        return True
    rollback(source, backup, journal)
    return False


def rollback(source, backup, journal):
    if not journal.is_file():
        return
    items = read_json(journal)["files"]
    with zipfile.ZipFile(backup) as archive:
        archived = set(archive.namelist())
        for relative in items:
            target = source.parent/relative
            if relative in archived:
                with archive.open(relative) as stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
            elif target.exists():
                target.unlink()
    journal.unlink()


def deploy_track(source, fit_dir, model, files, directory, batch_id, verify=None):
    backup = fit_dir/"before.zip"
    replacements = {name: model/name for name in files}
    replacements.update({"source/segments-labeled.svg": model/"segments-labeled.svg", "source/track-map.svg": model/"track-map.svg"})
    replacements[source.name] = fit_dir/"candidate.xml"  # XML last, with its original portable prolog.
    verify_backup(source, backup, replacements)
    report_dir = source.parent/"source"/("radius-batch-"+batch_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in ("before.zip", "before.xml", "report.json"):
        shutil.copy2(fit_dir/name, report_dir/name)
        if digest(fit_dir/name) != digest(report_dir/name):
            raise OSError(f"Backup/report copy mismatch: {name}")
    for name in ("side-clearance.json", "side-overlap.json", "closure.log"):
        shutil.copy2(directory/name, report_dir/name)
    for name in ("baseline-side-clearance.json", "accepted-clearance.json"):
        if (directory/name).exists():
            shutil.copy2(directory/name, report_dir/name)
    journal = directory/"deployment.json"
    write_json(journal, {"files": list(replacements)})
    try:
        for relative, staged in replacements.items():
            target = source.parent/relative
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".radius-", delete=False) as stream:
                temporary = Path(stream.name)
            try:
                shutil.copy2(staged, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            if digest(staged) != digest(target):
                raise OSError(f"Deployment hash mismatch: {relative}")
        if audit_track(source)["segments"]:
            raise ValueError("Deployed track still has oversized radii")
        if verify is not None:
            verify()
        write_json(journal, {"files": list(replacements), "committed": True,
                             "hashes": {name: digest(source.parent/name) for name in replacements}})
    except BaseException:
        rollback(source, backup, journal)
        raise


def eligible_keys(runtime):
    report = audit_tree(runtime/"tracks", preflight=True)
    if report["errors"]:
        raise ValueError(f"Audit errors: {report['errors']}")
    return [str(Path(track["path"]).parent.relative_to(runtime/"tracks")).replace("\\", "/") for track in report["tracks"]]
