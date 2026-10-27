"""Numerical rejection and timing regressions; no hardware or live transport."""
from dataclasses import fields
import math
import unittest

from battery_model import process, validate_telemetry
from cell_scaling import CellParameters, scale_to_cell
from ev_model import VehicleParameters, vehicle_power
from numerical_validation import TimingPolicy
from run_ev import NUMERIC, process_ev


def telemetry(time, speed=0):
    return dict(time_s=time, speed_mps=speed, throttle=0, brake=0)


def native(time, discharge=0):
    row = dict.fromkeys(NUMERIC, 0.0)
    row.update(time_s=time, pack_voltage_V=355., pack_power_W=360.,
               pack_current_A=360/355, pack_energy_Wh=40000-discharge,
               soc=(40000-discharge)/50000, discharge_Wh=discharge)
    return row


class ScalingNumericalTest(unittest.TestCase):
    def test_reject_invalid_power_before_clipping(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, False,
                      '75000', None, complex(1, 0), 10**1000):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                scale_to_cell(value)

    def test_reject_invalid_parameter_types_and_nonfinite_values(self):
        for cls in (CellParameters, VehicleParameters):
            for item in fields(cls):
                for value in (True, '1', None, float('nan'), float('inf'), -float('inf'), 10**1000):
                    with self.subTest(cls=cls.__name__, field=item.name, value=type(value).__name__):
                        with self.assertRaises(ValueError):
                            cls(**{item.name: value})

    def test_reject_scaling_overflow_at_each_stage(self):
        cases = [
            (1, CellParameters(nominal_voltage_V=1e308)),  # V*Ah
            (1, CellParameters(equivalent_pack_energy_Wh=1e-308)),  # ratio
            (10, CellParameters(nominal_voltage_V=1, capacity_Ah=1, equivalent_pack_energy_Wh=1e-308)),
            (1e6, CellParameters(experiment_scale=1e308)),
            (10, CellParameters(nominal_voltage_V=1e-308, capacity_Ah=1e308, equivalent_pack_energy_Wh=1)),
            (1, CellParameters(nominal_voltage_V=1e-300, capacity_Ah=1e-100)),  # ratio underflow
        ]
        for power, params in cases:
            with self.subTest(power=power, params=params), self.assertRaises(ValueError):
                scale_to_cell(power, params)

    def test_zero_directional_limits_and_finite_saturation(self):
        params = CellParameters(charge_limit_A=0)
        self.assertEqual(scale_to_cell(-75000, params)['cell_current_command_A'], 0)
        self.assertEqual(scale_to_cell(75000, params)['cell_current_command_A'], -2)
        params = CellParameters(discharge_limit_A=0)
        self.assertEqual(scale_to_cell(75000, params)['cell_current_command_A'], 0)
        self.assertEqual(scale_to_cell(-75000, params)['cell_current_command_A'], 1)
        for power in (0, 75000, -75000, 1e300, -1e300):
            result = scale_to_cell(power)
            self.assertTrue(all(math.isfinite(value) for value in result.values()))
        self.assertEqual(scale_to_cell(1e300)['cell_current_command_A'], -2)
        with self.assertRaises(ValueError):
            CellParameters(charge_limit_A=-1)
        with self.assertRaises(ValueError):
            CellParameters(experiment_scale=0)

    def test_valid_scaling_keeps_exact_legacy_equations(self):
        # Independently specified engineering examples, not a copy of the code.
        cases = [(0, 1, 0, 0, 0, 0, 0),
                 (300, 1, -.0432, -.012, -.012, -.0432, 0),
                 (75000, 1, -10.8, -3, -2, -7.2, 1),
                 (150000, 1, -21.6, -6, -2, -7.2, 1),
                 (-38700, 1, 5.5728, 1.548, 1, 3.6, 1),
                 (75000, .2, -2.16, -.6, -.6, -2.16, 0),
                 (-38700, .2, 1.11456, .3096, .3096, 1.11456, 0)]
        keys = ('cell_power_requested_W', 'cell_current_unclamped_A',
                'cell_current_command_A', 'cell_power_command_W', 'command_saturated')
        for power, scale, *expected in cases:
            result = scale_to_cell(power, CellParameters(experiment_scale=scale))
            for key, value in zip(keys, expected):
                self.assertAlmostEqual(result[key], value)


class VehicleNumericalTest(unittest.TestCase):
    def test_direct_calls_reject_invalid_speed_and_acceleration(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, '1', None):
            for speed, accel in ((value, 0), (1, value)):
                with self.subTest(speed=speed, accel=accel), self.assertRaises(ValueError):
                    vehicle_power(speed, accel)
        with self.assertRaises(ValueError):
            vehicle_power(-1, 0)

    def test_reject_power_and_force_overflow_even_with_regen_cap(self):
        cases = [(1e200, 0, VehicleParameters()),
                 (1e150, 0, VehicleParameters()),
                 (1, -10, VehicleParameters(mass_kg=1e308)),
                 (1, 1, VehicleParameters(drive_efficiency=1e-308)),
                 (1, 0, VehicleParameters(air_density_kg_m3=1e308, drag_area_m2=1e308))]
        for speed, accel, params in cases:
            with self.subTest(speed=speed, accel=accel), self.assertRaises(ValueError):
                vehicle_power(speed, accel, params)

    def test_reject_overflow_from_finite_telemetry(self):
        for rows in ([telemetry(0), telemetry(1e-320, 1)],
                     [telemetry(0, 1e308), telemetry(1, 1e308)]):
            with self.assertRaises(ValueError):
                process(rows)

    def test_numeric_csv_strings_remain_supported_but_booleans_do_not(self):
        self.assertEqual(validate_telemetry([dict(time_s='0', speed_mps='1', throttle='0', brake='0')]),
                         [dict(time_s=0., speed_mps=1., throttle=0., brake=0.)])
        for field in ('time_s', 'speed_mps', 'throttle', 'brake'):
            with self.assertRaises(ValueError):
                process([dict(telemetry(0), **{field: True})])


class TimingNumericalTest(unittest.TestCase):
    def test_invalid_timing_configuration(self):
        for value in (0, -1, True, float('nan'), float('inf'), '1'):
            for name in ('min_interval_s', 'max_gap_s'):
                with self.assertRaises(ValueError):
                    TimingPolicy(**{name: value})
        with self.assertRaises(ValueError):
            TimingPolicy(min_interval_s=2, max_gap_s=1)

    def test_optional_inclusive_bounds_and_default_gap_compatibility(self):
        timing = TimingPolicy(min_interval_s=1, max_gap_s=2)
        for dt in (1, 2):
            self.assertEqual(timing.interval(0, dt), dt)
            self.assertEqual(process([telemetry(0), telemetry(dt)], timing=timing)[1]['interval_s'], dt)
        for dt in (.5, 3):
            with self.assertRaises(ValueError):
                process([telemetry(0), telemetry(dt)], timing=timing)
        self.assertEqual(process([telemetry(0), telemetry(1e6)])[1]['interval_s'], 1e6)
        self.assertEqual(process([telemetry(3)], timing=timing)[0]['interval_s'], 0)

    def test_invalid_intervals_and_inputs_are_not_mutated(self):
        for dt in (0, -1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                TimingPolicy().interval(0, dt)
        rows = [telemetry(0), telemetry(3)]
        original = [dict(row) for row in rows]
        with self.assertRaises(ValueError):
            process(rows, timing=TimingPolicy(max_gap_s=1))
        self.assertEqual(rows, original)

    def test_native_direct_processing_checks_timing(self):
        for times in ((0, 0), (1, 0)):
            with self.assertRaises(ValueError):
                process_ev([native(times[0]), native(times[1])])
        for dt in (.5, 3):
            with self.assertRaises(ValueError):
                process_ev([native(0), native(dt)], timing=TimingPolicy(min_interval_s=1, max_gap_s=2))
        self.assertEqual(process_ev([native(3)])[0]['interval_s'], 0)
        self.assertAlmostEqual(process_ev([native(0), native(2, .2)])[1]['interval_pack_power_W'], 360)

    def test_native_direct_processing_rejects_invalid_and_overflowed_results(self):
        cases = [[native(0), native(1e-320, .1)],
                 [native(0), native(1, 1e308)],
                 [dict(native(0), longitudinal_mps=-1e308), dict(native(1), longitudinal_mps=1e308)],
                 [dict(native(0), pack_power_W=float('nan'))],
                 [dict(native(0), time_s=True)]]
        for rows in cases:
            original = [dict(row) for row in rows]
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                process_ev(rows)
            self.assertEqual(rows, original)


if __name__ == '__main__':
    unittest.main()
