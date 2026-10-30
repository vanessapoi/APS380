"""Isolated profile fixtures; never edit saved operator configuration."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_keyboard import prepare_keyboard, G29_PROFILE, RATES


class KeyboardProfileTests(unittest.TestCase):
    def test_independent_profiles_and_editable_rates(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root=Path(folder); source=root/'g29'; runtime=root/'runtime'; destination=root/'keyboard'
            def xml(path,text='<params/>'):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            xml(runtime/'categories/Historic.xml')
            xml(runtime/'cars/kc-2000gt/kc-2000gt.xml')
            (runtime/'cars/kc-2000gt/kc-2000gt.acc').write_bytes(b'fixture asset')
            xml(source/'drivers/human/human.xml')
            xml(source/'drivers/human/preferences.xml', '''<params><section name="Preferences"><section name="Drivers"><section name="1">
              <attstr name="throttle" val="AXIS2-0"/><attstr name="brake" val="AXIS3-0"/>
              <attstr name="left steer" val="AXIS0-0"/><attnum name="throttle min" val="0.987654"/>
              <attnum name="steer sensitivity" val="0.81"/></section></section></section></params>''')
            xml(source/'config/raceman/practice.xml')
            before={str(p):p.read_bytes() for p in source.rglob('*') if p.is_file()}
            config=root/'rates.json'; rates=dict(zip(RATES,(.4,.8,1.2,2.4)))
            config.write_text(json.dumps(rates))
            prepare_keyboard(config,destination,source,runtime)
            driver=ET.parse(destination/'drivers/human/preferences.xml').getroot().find("section[@name='Preferences']/section[@name='Drivers']/section[@name='1']")
            self.assertEqual(driver.find("attstr[@name='throttle']").get('val'),'Up Arrow')
            self.assertEqual(driver.find("attstr[@name='brake']").get('val'),'Down Arrow')
            self.assertEqual(driver.find("attstr[@name='left steer']").get('val'),'Left Arrow')
            self.assertEqual(driver.find("attnum[@name='steer sensitivity']").get('val'),'0.81')
            self.assertEqual(driver.find("attnum[@name='aps380 throttle rise per s']").get('val'),'0.4')
            self.assertEqual(driver.find("attnum[@name='aps380 brake fall per s']").get('val'),'2.4')
            # Reconfiguration changes only the copied keyboard preferences.
            rates['throttle_rise_per_s']=.2;config.write_text(json.dumps(rates))
            prepare_keyboard(config,destination,source,runtime)
            self.assertEqual(json.loads((destination/'keyboard_driving.json').read_text()),rates)
            self.assertEqual(before,{str(p):p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_protected_paths_and_invalid_configuration_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'g29';source.mkdir()
            config=root/'rates.json';config.write_text(json.dumps(dict.fromkeys(RATES,.5)))
            for target in (source,source/'nested',root,G29_PROFILE):
                with self.subTest(target=target),self.assertRaises(ValueError):
                    prepare_keyboard(config,target,source,root/'runtime')
            for bad in (0,-1,True,float('nan'),float('inf'),101):
                rates=dict.fromkeys(RATES,.5);rates[RATES[0]]=bad;config.write_text(json.dumps(rates))
                with self.subTest(rate=bad),self.assertRaises(ValueError):
                    prepare_keyboard(config,root/'keyboard',source,root/'runtime')
            self.assertFalse((root/'keyboard').exists())


if __name__=='__main__':unittest.main()
