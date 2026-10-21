"""Regression checks for native EV telemetry identity and energy accounting."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from run_ev import BASE, NUMERIC, process_ev, read_ev


class NativeEvTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ev.csv'
        self.profile_path = BASE/'profiles/tesla_model3_rwd.json'
        self.spec = json.loads(self.profile_path.read_text())
        identity = self.spec['id']+'-'+hashlib.sha256(self.profile_path.read_bytes()).hexdigest()[:12]
        self.rows = []
        for i in range(3):
            row = dict.fromkeys(NUMERIC, 0.)
            energy = 40000-i*.1
            row.update(time_s=i, speed_mps=10, longitudinal_mps=10,
                       pack_power_W=360, pack_voltage_V=355, pack_current_A=360/355,
                       soc=energy/50000, pack_energy_Wh=energy,
                       discharge_Wh=i*.1, profile_id=identity, car_id=self.spec['car_id'])
            self.rows.append(row)

    def write(self):
        with self.path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=self.rows[0])
            writer.writeheader()
            writer.writerows(self.rows)

    def test_energy_is_from_counters_not_collisions(self):
        self.rows[1].update(speed_mps=0, longitudinal_mps=0, damage=100, collision=1)
        self.rows[2].update(speed_mps=0, longitudinal_mps=0, damage=100)
        self.write()
        _, rows = read_ev(self.path, self.profile_path)
        result = process_ev(rows)
        self.assertEqual(result[1]['impact_flag'], 1)
        self.assertAlmostEqual(result[1]['interval_pack_power_W'], 360)
        self.assertEqual(sum(r['charge_Wh'] for r in rows), 0)

    def test_rejects_wrong_car_or_profile(self):
        for key in ('car_id', 'profile_id'):
            original = self.rows[1][key]
            self.rows[1][key] = 'wrong'
            self.write()
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                read_ev(self.path, self.profile_path)
            self.rows[1][key] = original

    def test_rejects_nonfinite_and_nonincreasing_time(self):
        for value in (float('nan'), 0):
            self.rows[1]['time_s'] = value
            self.write()
            with self.assertRaises(ValueError):
                read_ev(self.path, self.profile_path)

    def test_rejects_power_or_energy_inconsistency(self):
        for key in ('pack_current_A', 'pack_energy_Wh', 'motor_power_W'):
            original = self.rows[1][key]
            self.rows[1][key] += 10
            self.write()
            with self.assertRaisesRegex(ValueError, 'consistency'):
                read_ev(self.path, self.profile_path)
            self.rows[1][key] = original

    def test_rejects_counter_reset_and_nonconservation(self):
        for value in (-1, 100):
            self.rows[1]['discharge_Wh'] = value
            self.write()
            with self.assertRaises(ValueError):
                read_ev(self.path, self.profile_path)

    def test_rejects_legacy_recording(self):
        self.path.write_text('time_s,speed_mps,throttle,brake\n0,0,0,0\n1,5,1,0\n')
        with self.assertRaisesRegex(ValueError, 'Native EV telemetry required'):
            read_ev(self.path, self.profile_path)


if __name__ == '__main__':
    unittest.main()
