from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cell_soc import CellMeasurement, CoulombCounter, RestEvidence, load_reference
from run_cell_soc import process, read_measurements, replay

BASE = Path(__file__).parent


def sample(time_s=0, current=0, voltage=3.8040625, temperature=25, session="cell-test"):
    return CellMeasurement(session, time_s, voltage, current, temperature)


class CellSocTest(unittest.TestCase):
    def setUp(self):
        self.reference = load_reference()
        self.rest = RestEvidence(3600, 0.0, 25, 25)

    def test_paper_percent_units_endpoints_and_inversion(self):
        self.assertAlmostEqual(self.reference.voltage(0), 3.163)
        self.assertAlmostEqual(self.reference.voltage(.5), 3.8040625)
        self.assertAlmostEqual(self.reference.voltage(1), 4.182)
        self.assertEqual(self.reference.soc_from_ocv(4.182), 1)
        self.assertEqual(self.reference.soc_from_ocv(3.163), 0)
        for i in range(1001):
            soc = i / 1000
            self.assertAlmostEqual(self.reference.soc_from_ocv(self.reference.voltage(soc)), soc, places=12)
        for soc in (.00051, .123456, .80037, .9995):
            self.assertAlmostEqual(self.reference.soc_from_ocv(self.reference.voltage(soc)), soc, delta=1e-6)

    def test_no_extrapolation_or_nonfinite_input(self):
        for voltage in (2.5, 3.162999, 4.2, float("nan"), float("inf"), True):
            with self.subTest(voltage=voltage), self.assertRaises(ValueError):
                self.reference.soc_from_ocv(voltage)
        for soc in (-.01, 1.01, 50, float("nan")):
            with self.assertRaises(ValueError):
                self.reference.voltage(soc)
        with self.assertRaises(ValueError):
            replace(self.reference, coefficients_descending=(-1, 4))

    def test_rest_history_is_required_and_consistent(self):
        invalid = [replace(self.rest, duration_s=3599), replace(self.rest, duration_s=float("nan")),
                   replace(self.rest, max_abs_current_A=.02), replace(self.rest, max_abs_current_A=-1),
                   replace(self.rest, min_temperature_C=22), replace(self.rest, max_temperature_C=28),
                   replace(self.rest, min_temperature_C=26)]
        for evidence in invalid:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                CoulombCounter.from_rest(self.reference, sample(), evidence, capacity_Ah=3.5, max_gap_s=1)
        for measurement in (sample(current=.1), sample(temperature=24), sample(voltage=4.2)):
            with self.assertRaises(ValueError):
                CoulombCounter.from_rest(self.reference, measurement, self.rest, capacity_Ah=3.5, max_gap_s=1)

    def test_coulomb_counting_units_charge_sign_and_irregular_intervals(self):
        counter = CoulombCounter(2, 4000, .8, sample(current=-1))
        first = counter.update(sample(900, current=-1))
        self.assertAlmostEqual(first.soc, .675)  # 0.25 Ah removed from 2 Ah.
        second = counter.update(sample(2700, current=-1))
        self.assertAlmostEqual(second.soc, .425)
        third = counter.update(sample(3600, current=1))
        self.assertAlmostEqual(third.soc, .425)  # Linear -1 to +1 A has zero net charge.
        final = counter.update(sample(3960, current=1))
        self.assertAlmostEqual(final.soc, .475)
        self.assertAlmostEqual(final.net_discharged_Ah, .65)

    def test_reject_gaps_duplicate_reversed_time_and_session_without_mutation(self):
        counter = CoulombCounter(3.5, 2, .5, sample())
        for measurement in (sample(0), sample(3), sample(1, session="new-session")):
            with self.assertRaises(ValueError):
                counter.update(measurement)
            self.assertEqual(counter.soc, .5)
            self.assertEqual(counter.previous.time_s, 0)
        counter.update(sample(2))
        with self.assertRaises(ValueError):
            counter.update(sample(1))
        self.assertEqual(counter.previous.time_s, 2)

    def test_clamping_is_explicit_and_charge_accounting_is_preserved(self):
        counter = CoulombCounter(1, 3600, .1, sample(current=-1))
        result = counter.update(sample(3600, current=-1))
        self.assertEqual(result.soc, 0)
        self.assertAlmostEqual(result.soc_unclamped, -.9)
        self.assertTrue(result.boundary_clipped)
        self.assertEqual(result.net_discharged_Ah, 1)
        charging = CoulombCounter(1, 3600, .9, sample(current=1))
        result = charging.update(sample(3600, current=1))
        self.assertEqual(result.soc, 1)
        self.assertAlmostEqual(result.soc_unclamped, 1.9)
        self.assertTrue(result.boundary_clipped)

    def test_loaded_voltage_does_not_reinitialize_running_soc(self):
        counter = CoulombCounter.from_rest(self.reference, sample(), self.rest, capacity_Ah=3.5, max_gap_s=10)
        result = counter.update(sample(10, voltage=3.2, temperature=30))
        self.assertAlmostEqual(result.soc, .5)

    def test_invalid_measurements_and_estimator_configuration(self):
        for change in ({"time_s": -1}, {"cell_voltage_V": 0}, {"net_cell_current_A": float("nan")},
                       {"cell_temperature_C": float("inf")}, {"session_id": ""}):
            with self.assertRaises(ValueError):
                replace(sample(), **change)
        for capacity, gap, initial in ((0, 1, .5), (3.5, 0, .5), (True, 1, .5),
                                       (3.5, float("nan"), .5), (3.5, 1, 1.1)):
            with self.assertRaises(ValueError):
                CoulombCounter(capacity, gap, initial, sample())

    def test_mock_replay_provenance_and_outputs(self):
        source = BASE / "data/mock_cell_soc_charging_positive.csv"
        config = BASE / "profiles/mock_cell_soc_replay.json"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = process(source, config, output)
            self.assertEqual(report["data_kind"], "mock")
            self.assertEqual(report["samples"], 8)
            self.assertAlmostEqual(report["initial_soc"], .5)
            self.assertAlmostEqual(report["net_discharged_Ah"], 15 / 3600)
            self.assertAlmostEqual(report["final_soc"], .5 - 15 / 3600 / 3.5)
            self.assertEqual(report["boundary_clipped_samples"], 0)
            self.assertEqual(len((output / "ocv_lookup.csv").read_text().splitlines()), 1002)
            self.assertEqual((output / "replay_config.json").read_bytes(), config.read_bytes())
            self.assertIn("input_sha256", json.loads((output / "summary.json").read_text()))
        self.assertEqual(source.read_bytes(), before)

    def test_reject_command_csv_and_bad_replay_before_writing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.csv"
            path.write_text("time_s,cell_current_command_A\n0,1\n1,1\n")
            with self.assertRaises(ValueError):
                read_measurements(path)
            config = json.loads((BASE / "profiles/mock_cell_soc_replay.json").read_text())
            rows = read_measurements(BASE / "data/mock_cell_soc_charging_positive.csv")
            with self.assertRaises(ValueError):
                replay(rows, self.reference, dict(config, data_kind="simulator_pack"))
            with self.assertRaises(ValueError):
                replay(rows, self.reference, dict(config, max_gap_s=5))
            with self.assertRaises(ValueError):
                process(BASE / "data/mock_cell_soc_charging_positive.csv", BASE / "profiles/mock_cell_soc_replay.json",
                        Path(directory), path)
            self.assertFalse((Path(directory) / "cell_soc.csv").exists())


if __name__ == "__main__":
    unittest.main()
