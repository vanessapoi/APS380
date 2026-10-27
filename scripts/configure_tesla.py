"""Prepare a workspace-local Tesla reference experiment using existing TORCS assets."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import wave
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TORCS = ROOT/'external/torcs-1.3.10'
RUNTIME = TORCS/'runtime'
PROFILE = ROOT/'aps380_torcs_starter/profiles/tesla_model3_rwd.json'


def section(root, name):
    found = root.find(f"section[@name='{name}']")
    return found if found is not None else ET.SubElement(root, 'section', name=name)


def attribute(root, name, value, unit=None):
    tag = 'attstr' if isinstance(value, str) else 'attnum'
    found = root.find(f"{tag}[@name='{name}']")
    if found is None:
        found = ET.SubElement(root, tag, name=name)
    found.attrib.clear()
    found.set('name', name)
    found.set('val', str(value))
    if unit:
        found.set('unit', unit)


def write(root, path):
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def configure(runtime=RUNTIME, local=None, existing=None):
    """Prepare assets and preferences; defaults preserve the Windows workflow."""
    runtime = Path(runtime)
    spec = json.loads(PROFILE.read_text())
    p, r, u = spec['published'], spec['reference_choices'], spec['unvalidated']
    # The generated category permits the configured EV values instead of ICE limits.
    category = ET.parse(runtime/'categories/Historic.xml').getroot()
    category.set('name', 'APS380 EV')
    for item in category.iter('attnum'):
        if 'min' in item.attrib:
            item.set('min', '-1000000000')
        if 'max' in item.attrib:
            item.set('max', '1000000000')
    attribute(section(category, 'Car'), 'category', 'APS380 EV')
    # Engine inertia cannot be zero in generic TORCS mechanics.
    write(category, runtime/'categories/APS380 EV.xml')
    car_id = spec['car_id']
    target = runtime/'cars'/car_id
    target.mkdir(exist_ok=True)
    donor = runtime/'cars/kc-2000gt'
    for asset in donor.iterdir():
        if asset.is_file() and asset.suffix != '.xml':
            shutil.copy2(asset, target/asset.name)
    car = ET.parse(donor/'kc-2000gt.xml').getroot()
    car.set('name', 'APS380 Model 3 RWD reference (proxy body)')
    # TORCS requires the main model basename to match its car directory.
    if (target/'kc-2000gt.acc').exists():
        shutil.copy2(target/'kc-2000gt.acc', target/f'{car_id}.acc')
    # Retain road/tire sounds without a combustion engine sample.
    with wave.open(str(target/'aps380-ev-silent.wav'), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b'\0\0'*22050)
    attribute(section(car, 'Sound'), 'engine sample', 'aps380-ev-silent.wav')
    c = section(car, 'Car')
    for name, value, unit in [
        ('category', 'APS380 EV', None), ('body length', p['length_m'], 'm'),
        ('body width', p['width_m'], 'm'), ('body height', p['height_m'], 'm'),
        ('mass', r['curb_mass_kg']+r['driver_mass_kg']-.001, 'kg'),
        ('GC height', u['cg_height_m'], 'm'),
        ('front-rear weight repartition', u['front_weight_fraction'], None),
        ('fuel tank', 20, 'l'), ('initial fuel', 1, 'l')]:
        attribute(c, name, value, unit)
    for name, value in [('Cx', u['drag_coefficient']), ('front area', u['frontal_area_m2']),
                        ('front Clift', 0), ('rear Clift', 0)]:
        attribute(section(car, 'Aerodynamics'), name, value, 'm2' if name == 'front area' else None)
    engine = section(car, 'Engine')
    for name, value, unit in [('tickover', 0, 'rpm'), ('revs limiter', 18000, 'rpm'),
                              ('revs maxi', 19000, 'rpm'), ('fuel cons factor', 0, None),
                              ('brake coefficient', 0, None), ('inertia', u['motor_inertia_kgm2'], 'kg.m2')]:
        attribute(engine, name, value, unit)
    points = section(engine, 'data points')
    points.clear()
    points.set('name', 'data points')
    for i, rpm in enumerate((0, 1000, 3000, 5000, 8000, 12000, 18000, 20000), 1):
        point = section(points, str(i))
        attribute(point, 'rpm', rpm, 'rpm')
        attribute(point, 'Tq', min(p['motor_max_torque_Nm'], p['motor_max_power_W']/max(rpm*3.141592653589793/30, 1)))
    gearbox = section(car, 'Gearbox')
    attribute(gearbox, 'shift time', 0.01)
    gears = section(gearbox, 'gears')
    gears.clear()
    gears.set('name', 'gears')
    for name, ratio in [('r', -1), ('1', 1), ('2', 0), ('3', 0), ('4', 0), ('5', 0), ('6', 0)]:
        attribute(section(gears, name), 'ratio', ratio)
        attribute(section(gears, name), 'efficiency', 1)
    attribute(section(car, 'Drivetrain'), 'type', 'RWD')
    attribute(section(car, 'Rear Differential'), 'ratio', p['reduction_ratio'])
    attribute(section(car, 'Rear Differential'), 'type', 'FREE')
    attribute(section(car, 'Rear Differential'), 'efficiency', 1)
    attribute(section(car, 'Steer'), 'steer lock', 30, 'deg')
    attribute(section(car, 'Brake System'), 'max pressure', u['brake_pressure_kPa'], 'kPa')
    for axle, sign in [('Front', 1), ('Rear', -1)]:
        attribute(section(car, axle+' Axle'), 'xpos', sign*p['wheelbase_m']/2, 'm')
        for side, lateral in [('Right', -1), ('Left', 1)]:
            wheel = section(car, f'{axle} {side} Wheel')
            for name, value, unit in [('ypos', lateral*p['track_m']/2, 'm'),
                                      ('mu', u['tire_mu'], None), ('tire width', r['tire_width_mm'], 'mm'),
                                      ('tire height-width ratio', r['tire_aspect_percent'], '%'),
                                      ('rim diameter', r['rim_in'], 'in'), ('ride height', 140, 'mm')]:
                attribute(wheel, name, value, unit)
            suspension = section(car, f'{axle} {side} Suspension')
            attribute(suspension, 'spring', u['spring_Npm'], 'N/m')
            for damping in ('slow bump', 'slow rebound', 'fast bump', 'fast rebound'):
                attribute(suspension, damping, u['damper_Nspm'], 'N/m/s')
            brake = section(car, f'{axle} {side} Brake')
            attribute(brake, 'disk diameter', p['front_rotor_m' if axle == 'Front' else 'rear_rotor_m'], 'm')
    electric = section(car, 'Electric Powertrain')
    identifier = spec['id']+'-'+hashlib.sha256(PROFILE.read_bytes()).hexdigest()[:12]
    values = {'enabled': 'yes', 'profile id': identifier,
              'max torque Nm': p['motor_max_torque_Nm'], 'max power W': p['motor_max_power_W'],
              'nominal voltage V': p['pack_nominal_voltage_V'],
              'capacity Wh': u['capacity_Wh'], 'initial SOC': u['initial_soc'],
              'drive efficiency': u['drive_efficiency'], 'regen efficiency': u['regen_efficiency'],
              'auxiliary power W': u['auxiliary_power_W'], 'max regen shaft power W': u['max_regen_shaft_power_W'],
              'lift off torque Nm': u['lift_off_torque_Nm'], 'max speed mps': u['max_speed_mps']}
    values['neutral pedal'] = u.get('neutral_pedal', .05)
    for name, value in values.items():
        attribute(electric, name, value)
    write(car, target/f'{car_id}.xml')

    # Isolate settings in the workspace and retain the user's calibrated wheel.
    local = Path(local) if local is not None else ROOT/'.local/tesla-profile'
    existing = Path(existing) if existing is not None else Path(os.environ['LOCALAPPDATA'])/'torcs'
    if not local.exists():
        shutil.copytree(existing, local)
    human_path = local/'drivers/human/human.xml'
    human = ET.parse(human_path).getroot()
    drivers = section(section(human, 'Robots'), 'index')
    for driver in list(drivers):
        if driver.tag == 'section' and driver.get('name') != '1':
            drivers.remove(driver)
    attribute(section(drivers, '1'), 'car name', car_id)
    attribute(section(drivers, '1'), 'skill level', 'pro')
    write(human, human_path)
    prefs_path = local/'drivers/human/preferences.xml'
    prefs = ET.parse(prefs_path).getroot()
    driver = section(section(section(prefs, 'Preferences'), 'Drivers'), '1')
    for name, value in [('transmission', 'auto'), ('auto reverse', 'no'), ('ABS on', 'yes'), ('ASR on', 'yes')]:
        attribute(driver, name, value)
    write(prefs, prefs_path)
    race_path = local/'config/raceman/practice.xml'
    race = ET.parse(race_path).getroot()
    entry = section(section(race, 'Drivers'), '1')
    attribute(entry, 'module', 'human')
    attribute(entry, 'idx', 1)
    attribute(section(race, 'Drivers'), 'focused idx', 1)
    practice = section(race, 'Practice')
    attribute(practice, 'laps', 20)
    attribute(practice, 'distance', 0, 'km')
    attribute(practice, 'fuel consumption factor', 0)
    attribute(practice, 'tire factor', 0)
    attribute(practice, 'damage factor', 1)
    write(race, race_path)
    (runtime/'telemetry').mkdir(exist_ok=True)
    (runtime/'telemetry'/f'{identifier}.json').write_bytes(PROFILE.read_bytes())
    print(f'Prepared {identifier}\nLocal profile: {local}\nCar XML: {target/car_id}.xml')
    return local


if __name__ == '__main__':
    configure()
