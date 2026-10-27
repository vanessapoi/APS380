"""Fixture-only checks for portable Tesla setup; no simulator is launched."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_tesla import configure
from run_tesla_ai import prepare_profile


def xml(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<params name="fixture"/>')


class PortableSetupTests(unittest.TestCase):
    def test_explicit_runtime_needs_no_windows_profile_and_does_not_change_donor(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            runtime = root/'runtime'
            existing = root/'existing'
            xml(runtime/'categories/Historic.xml')
            donor = runtime/'cars/kc-2000gt/kc-2000gt.xml'
            xml(donor)
            (donor.parent/'kc-2000gt.acc').write_bytes(b'fixture model')
            for name in ('drivers/human/human.xml', 'drivers/human/preferences.xml', 'config/raceman/practice.xml'):
                xml(existing/name)
            original = donor.read_bytes()
            with patch.dict(os.environ, {}, clear=True):
                local = configure(runtime=runtime, local=root/'manual', existing=existing)
            car = ET.parse(runtime/'cars/aps380-model3-rwd/aps380-model3-rwd.xml').getroot()
            self.assertEqual(car.find("section[@name='Electric Powertrain']/attstr[@name='enabled']").get('val'), 'yes')
            self.assertTrue((runtime/'cars/aps380-model3-rwd/aps380-model3-rwd.acc').exists())
            self.assertEqual(donor.read_bytes(), original)
            self.assertEqual(local, root/'manual')

    def test_native_ai_driver_path_and_practice_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manual = root/'manual'
            runtime = root/'runtime'
            xml(manual/'config/raceman/practice.xml')
            native = root/'binary/aps380_ai.so'
            native.parent.mkdir()
            native.write_bytes(b'fixture native driver')
            local = root/'ai'
            prepare_profile(local, runtime=runtime, manual_profile=manual, driver_binary=native)
            self.assertEqual((runtime/'drivers/aps380_ai/aps380_ai.so').read_bytes(), native.read_bytes())
            race = ET.parse(local/'race.xml').getroot()
            self.assertEqual(race.find("section[@name='Drivers']/section[@name='1']/attstr[@name='module']").get('val'), 'aps380_ai')
            self.assertEqual(race.find("section[@name='Practice']/attnum[@name='laps']").get('val'), '2')
            visible = ET.parse(local/'config/raceman/practice.xml').getroot()
            self.assertEqual(visible.find("section[@name='Practice']/attstr[@name='display mode']").get('val'), 'normal')


if __name__ == '__main__':
    unittest.main()
