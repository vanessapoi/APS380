from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from battery_model import process, read_telemetry
from ev_model import VehicleParameters, vehicle_power
from cell_scaling import CellParameters, scale_to_cell

BASE = Path(__file__).resolve().parent


def sample(t, v):
    return dict(time_s=t, speed_mps=v, throttle=0., brake=0.)


class OfflineModelTest(unittest.TestCase):
    def test_acceleration_energy_irregular_timestamps(self):
        params = VehicleParameters(rolling_coefficient=0, drag_area_m2=0, auxiliary_power_W=0)
        rows = process([sample(3, 0), sample(5, 4), sample(8, 10)], params)
        energy = sum(r['wheel_power_W'] * r['interval_s'] for r in rows)
        self.assertAlmostEqual(energy, .5 * params.mass_kg * 10**2)
        self.assertEqual(rows[1]['accel_mps2'], 2)
        self.assertLess(rows[1]['cell_current_command_A'], 0)

    def test_cruise(self):
        p = VehicleParameters()
        row = process([sample(0, 20), sample(1, 20)], p)[1]
        expected = (p.mass_kg*p.gravity_mps2*p.rolling_coefficient + .5*p.air_density_kg_m3*p.drag_area_m2*400)*20
        self.assertAlmostEqual(row['vehicle_battery_power_W'], expected/p.drive_efficiency+p.auxiliary_power_W)

    def test_braking_regeneration_and_cap(self):
        p = VehicleParameters(auxiliary_power_W=0, max_regen_wheel_power_W=5000)
        row = process([sample(0, 30), sample(1, 20)], p)[1]
        self.assertEqual(row['vehicle_battery_power_W'], -5000*p.regen_efficiency)
        self.assertGreater(row['friction_brake_power_W'], 0)
        self.assertGreater(row['cell_current_command_A'], 0)
        self.assertEqual(vehicle_power(25, -10, replace(p, regen_fraction=0))['vehicle_battery_power_W'], 0)

    def test_passive_coasting_is_not_regen(self):
        p = VehicleParameters(auxiliary_power_W=0)
        v = 20
        a = -(p.mass_kg*p.gravity_mps2*p.rolling_coefficient + .5*p.air_density_kg_m3*p.drag_area_m2*v*v)/p.mass_kg
        self.assertAlmostEqual(vehicle_power(v, a, p)['vehicle_battery_power_W'], 0)

    def test_stationary_and_first_sample(self):
        row = process([sample(0, 0)], VehicleParameters(auxiliary_power_W=0))[0]
        self.assertEqual(row['cell_current_command_A'], 0)
        self.assertEqual(row['interval_s'], 0)
        self.assertEqual(process([sample(0, 0)])[0]['vehicle_battery_power_W'], 300)

    def test_scaling_and_limits(self):
        p = CellParameters()
        self.assertAlmostEqual(scale_to_cell(75000, p)['cell_current_unclamped_A'], -3)
        for power, expected in [(1e6, -2), (-1e6, 1)]:
            row = scale_to_cell(power, p)
            self.assertEqual(row['cell_current_command_A'], expected)
            self.assertEqual(row['command_saturated'], 1)
            self.assertAlmostEqual(row['cell_power_command_W'], expected*3.6)
        self.assertEqual(scale_to_cell(75000, replace(p, discharge_limit_A=2))['cell_current_unclamped_A'], -3)

    def test_malformed_telemetry(self):
        cases = [[], [sample(-1, 0)], [sample(0, -1)], [sample(0, float('nan'))],
                 [sample(0, 1), sample(0, 2)], [sample(1, 1), sample(0, 2)],
                 [dict(sample(0, 1), brake=2)], [dict(sample(0, 1), throttle='oops')], [{}]]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                process(data)

    def test_bad_csv(self):
        for content in ['', 'time_s,speed_mps\n0,1\n',
                        'time_s,speed_mps,throttle,brake\n0,1,0,\n',
                        'time_s,speed_mps,throttle,brake\n0,inf,0,0\n']:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'bad.csv'
                path.write_text(content)
                with self.assertRaises(ValueError):
                    read_telemetry(path)

    def test_invalid_parameters(self):
        for cls, args in [(CellParameters, {'capacity_Ah': 0}), (CellParameters, {'charge_limit_A': -1}),
                          (VehicleParameters, {'drive_efficiency': 0}), (VehicleParameters, {'regen_fraction': 2}),
                          (VehicleParameters, {'mass_kg': float('nan')})]:
            with self.assertRaises(ValueError):
                cls(**args)

    def test_demo(self):
        rows = process(read_telemetry(BASE/'data/demo_synthetic.csv'))
        self.assertEqual(len(rows), 1201)
        self.assertTrue(all(-2 <= r['cell_current_command_A'] <= 1 for r in rows))
        self.assertTrue(any(r['cell_current_command_A'] < 0 for r in rows))
        self.assertTrue(any(r['cell_current_command_A'] > 0 for r in rows))


class TorcsAdapterTest(unittest.TestCase):
    @staticmethod
    def raw(t, speed=36, **extra):
        return dict(curLapTime=t, speedX=speed, accel=.5, brake=.2, **extra)

    def test_units_and_recorded_clock(self):
        from torcs_adapter import adapt_rows
        segments, report = adapt_rows([self.raw(3), self.raw(3.022)])
        self.assertEqual(segments[0][0], sample(3, 10) | {'throttle': .5, 'brake': .2})
        self.assertEqual(segments[0][1]['time_s'], 3.022)
        self.assertEqual(report['retained_samples'], 2)

    def test_breaks_not_stitched(self):
        from torcs_adapter import adapt_rows
        cases = [([3, .01], {}), ([3, 3], {}), ([3, 4], {}),
                 ([3, 3.02], {'trackName': 'new'}),
                 ([3, 3.02], {'distRaced': 0})]
        for times, extra in cases:
            with self.subTest(times=times, extra=extra):
                segments, report = adapt_rows([
                    self.raw(times[0], trackName='old', distRaced=10),
                    self.raw(times[1], **(dict(trackName='old', distRaced=11) | extra))])
                self.assertEqual([len(x) for x in segments], [1, 1])
                self.assertEqual(len(report['boundaries']), 1)

    def test_exclusions_break_derivative_chain(self):
        from torcs_adapter import adapt_rows
        segments, report = adapt_rows([self.raw(-.02), self.raw(0),
                                      self.raw(.02, -1), self.raw(.04)])
        self.assertEqual([len(x) for x in segments], [1, 1])
        self.assertEqual(len(report['excluded_rows']), 2)

    def test_invalid_source(self):
        from torcs_adapter import adapt_rows
        for rows in [[], [{}], [self.raw(float('nan'))], [dict(self.raw(0), accel=2)]]:
            with self.assertRaises(ValueError):
                adapt_rows(rows)

    def test_source_audit_and_preservation(self):
        from torcs_adapter import adapt_file
        source = BASE/'data/Torcs_Sample_Data.csv'
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            report = adapt_file(source, folder)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report['source_samples'], 5000)
            self.assertEqual(report['retained_samples'], 4950)
            self.assertEqual([x['samples'] for x in report['segments']], [2151, 1982, 817])
            for entry in report['segments']:
                rows = process(read_telemetry(Path(folder)/entry['normalized_csv']))
                self.assertEqual(len(rows), entry['samples'])
                self.assertEqual(rows[0]['interval_s'], 0)


class ConditioningComparisonTest(unittest.TestCase):
    def test_irregular_linear_speed_preserved(self):
        from telemetry_conditioning import smooth_speed
        data = [sample(t, 2+3*t) for t in [0, .02, .05, .07, .1]]
        result = smooth_speed(data, .2)
        for a,b in zip(data,result):
            self.assertEqual(a['time_s'], b['time_s'])
            self.assertAlmostEqual(a['speed_mps'], b['speed_mps'])
        self.assertEqual(smooth_speed(data, 0), data)
        self.assertEqual(data[0]['speed_mps'], 2)

    def test_smoothing_reduces_alternating_noise(self):
        from telemetry_conditioning import smooth_speed
        data = [sample(i*.02, 10 + (.2 if i%2 else -.2)) for i in range(30)]
        smoothed = smooth_speed(data, .2)
        before = max(abs(r['accel_mps2']) for r in process(data))
        after = max(abs(r['accel_mps2']) for r in process(smoothed))
        self.assertLess(after, before)
        for bad in [-1, float('nan')]:
            with self.assertRaises(ValueError):
                smooth_speed(data, bad)

    def test_experiment_scale_and_energy_metrics(self):
        from compare_profiles import metrics
        p = CellParameters(experiment_scale=.2)
        self.assertAlmostEqual(scale_to_cell(75000, p)['cell_current_unclamped_A'], -.6)
        rows = process([sample(0,20),sample(2,20)], cell=p)
        m = metrics(rows)
        self.assertAlmostEqual(m['command_discharge_Wh'], -rows[1]['cell_power_command_W']*2/3600)
        self.assertAlmostEqual(m['command_rms_A'], abs(rows[1]['cell_current_command_A']))
        with self.assertRaises(ValueError):
            CellParameters(experiment_scale=0)


class SensitivityTest(unittest.TestCase):
    def test_time_weighted_error_and_event_shift(self):
        from analyze_telemetry import fidelity
        raw = [dict(sample(0,10),interval_s=0,accel_mps2=0),
               dict(sample(1,9),interval_s=1,accel_mps2=-1),
               dict(sample(3,5),interval_s=2,accel_mps2=-2)]
        changed = [dict(r) for r in raw]
        changed[1]['speed_mps'] += 3
        changed[1]['accel_mps2'] = -3
        result = fidelity(raw,changed)
        self.assertAlmostEqual(result['speed_rms_error_mps'], 3**.5)
        self.assertEqual(result['strongest_decel_time_shift_s'], -2)
        self.assertEqual(fidelity(raw,raw)['max_speed_error_mps'],0)


if __name__ == '__main__':
    unittest.main()
