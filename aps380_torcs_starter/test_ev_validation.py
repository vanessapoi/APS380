"""Analytical checks for conditional replay and contiguous interval reporting."""
import unittest

from validate_ev_drive import contiguous_intervals, phase_summary, replay_electrical


class DriveValidationTest(unittest.TestCase):
    def test_constant_power_integrates_known_energy(self):
        rows = [{'time_s': t, 'motor_power_W': 1000} for t in (0, .4, 2)]
        result = replay_electrical(rows, .8, .5, 200, 50000, 400)
        self.assertAlmostEqual(result['net_Wh'], (1000/.8+200)*2/3600)
        self.assertEqual(result['recovered_Wh'], 0)

    def test_regeneration_subtracts_auxiliary_load(self):
        rows = [{'time_s': t, 'motor_power_W': -1000} for t in (0, 2)]
        result = replay_electrical(rows, .8, .5, 200, 50000, 400)
        self.assertAlmostEqual(result['recovered_Wh'], 300*2/3600)
        self.assertEqual(result['discharge_Wh'], 0)

    def test_capacity_and_voltage_do_not_change_fixed_trace_energy(self):
        rows = [{'time_s': t, 'motor_power_W': 1000} for t in (0, 2)]
        a = replay_electrical(rows, .8, .5, 200, 50000, 400)
        b = replay_electrical(rows, .8, .5, 200, 100000, 200)
        self.assertEqual(a['net_Wh'], b['net_Wh'])
        self.assertAlmostEqual(a['soc_drop_percentage_points']/2, b['soc_drop_percentage_points'])
        self.assertAlmostEqual(a['peak_discharge_current_A']*2, b['peak_discharge_current_A'])

    def test_qualifying_intervals_are_not_stitched_across_gap(self):
        rows = [{'qualifies': q} for q in (True, True, True, False, True)]
        self.assertEqual(contiguous_intervals(rows, lambda r: r['qualifies']), [[1, 2], [4]])

    def test_phase_summary_preserves_duration_and_energy(self):
        rows = []
        for i in range(4):
            rows.append({'time_s': i, 'longitudinal_mps': 10,
                         'throttle': .3, 'brake': .2 if i == 2 else 0,
                         'motor_power_W': 1000, 'accel_mps2': 0,
                         'discharge_Wh': i*.2, 'charge_Wh': i*.05})
        phases = phase_summary(rows)
        self.assertEqual(sum(x['duration_s'] for x in phases), 3)
        self.assertAlmostEqual(sum(x['discharge_Wh'] for x in phases), .6)
        self.assertAlmostEqual(sum(x['recovered_Wh'] for x in phases), .15)
        self.assertEqual([x['phase'] for x in phases], ['near_steady', 'brake_pedal_active', 'near_steady'])


if __name__ == '__main__':
    unittest.main()
