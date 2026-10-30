"""Prepare an isolated keyboard profile without writing the G29 profile."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from configure_tesla import ROOT, RUNTIME, configure, section, attribute, write

KEYBOARD_PROFILE = ROOT/'.local/tesla-keyboard-profile'
G29_PROFILE = ROOT/'.local/tesla-profile'
KEYBOARD_CONFIG = ROOT/'aps380_torcs_starter/profiles/keyboard_driving.json'
RATES = ('throttle_rise_per_s', 'throttle_fall_per_s', 'brake_rise_per_s', 'brake_fall_per_s')


def prepare_keyboard(config=KEYBOARD_CONFIG, destination=KEYBOARD_PROFILE,
                     source=G29_PROFILE, runtime=RUNTIME):
    rates = json.loads(Path(config).read_text())
    if set(rates) != set(RATES):
        raise ValueError('Keyboard config must contain exactly the four pedal ramp rates')
    for name, value in rates.items():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 100:
            raise ValueError(f'{name} must be finite, >0 and <=100 pedal fractions/s')
    destination, source = Path(destination).resolve(), Path(source).resolve()
    # Reject equal, nested and ancestor destinations, including resolved aliases.
    protected = (source, G29_PROFILE.resolve())
    if any(destination == p or destination in p.parents or p in destination.parents for p in protected):
        raise ValueError('Keyboard profile must be separate from the protected G29 profile')
    if not source.is_dir():
        raise FileNotFoundError('Existing Tesla profile required; do not recalibrate or overwrite G29 settings')
    # Explicit destination prevents configure() from writing its default G29 path.
    local = configure(runtime=runtime, local=destination, existing=source)
    prefs_path = local/'drivers/human/preferences.xml'
    prefs = ET.parse(prefs_path).getroot()
    driver = section(section(section(prefs, 'Preferences'), 'Drivers'), '1')
    for name, value in (('throttle', 'Up Arrow'), ('brake', 'Down Arrow'),
                        ('left steer', 'Left Arrow'), ('right steer', 'Right Arrow'),
                        ('clutch', ''), ('up shift', ''), ('down shift', ''),
                        ('aps380 keyboard pedal ramp', 'yes')):
        attribute(driver, name, value)
    for name, value in rates.items():
        attribute(driver, 'aps380 '+name.replace('_per_s', ' per s').replace('_', ' '), value)
    write(prefs, prefs_path)
    (local/'keyboard_driving.json').write_text(json.dumps(rates, indent=2)+'\n')
    return local


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=KEYBOARD_CONFIG)
    args = parser.parse_args()
    print('Keyboard profile:', prepare_keyboard(args.config))
