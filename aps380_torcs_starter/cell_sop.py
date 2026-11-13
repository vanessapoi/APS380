"""Unvalidated MOCK Rint discharge SOP. No measurement or hardware interfaces.

Application SOC is fractional; discharge current here is a positive magnitude.
The existing signed cell convention remains charging-positive elsewhere.
"""
from dataclasses import asdict,dataclass
import math

from cell_soc import finite,load_reference
from cell_scaling import scale_to_cell


@dataclass(frozen=True)
class RintParameters:
    r0_ohm: float
    minimum_voltage_V: float
    maximum_discharge_A: float
    capacity_Ah: float
    soc_reserve_fraction: float
    soc_budget_horizon_s: float
    temperature_min_C: float
    temperature_max_C: float
    ocv_margin_V: float
    r0_margin_ohm: float
    soc_margin_fraction: float
    parameter_status: str

    def __post_init__(self):
        if self.parameter_status!='unvalidated_mock_assumptions':
            raise ValueError('This estimator only accepts explicitly unvalidated mock assumptions')
        for k,v in asdict(self).items():
            if k!='parameter_status':finite(k,v)
        for k in ('r0_ohm','minimum_voltage_V','capacity_Ah','soc_budget_horizon_s'):
            if getattr(self,k)<=0:raise ValueError(k+' must be positive')
        if self.maximum_discharge_A<0:raise ValueError('Current limit must be nonnegative')
        if min(self.ocv_margin_V,self.r0_margin_ohm,self.soc_margin_fraction)<0:
            raise ValueError('Assumption margins must be nonnegative')
        if not 0<=self.soc_reserve_fraction<1 or not 0<=self.soc_margin_fraction<=1:
            raise ValueError('SOC reserve/margin must be fractions')
        if self.temperature_min_C>=self.temperature_max_C:raise ValueError('Temperature interval must increase')
        if not math.isfinite(self.r0_ohm+self.r0_margin_ohm):raise ValueError('Resistance overflow')


class RintEstimator:
    def __init__(self,parameters,reference=None):
        self.p=parameters;self.reference=reference or load_reference()
        r=self.reference;p=self.p
        # Existing +/-2 C candidate qualification is itself unvalidated. Do not
        # silently extend a ~25 C OCV curve over the cell's full rated range.
        if (p.temperature_min_C<r.temperature_C-r.temperature_tolerance_C or
                p.temperature_max_C>r.temperature_C+r.temperature_tolerance_C):
            raise ValueError('Assumed model range exceeds candidate OCV temperature qualification')
        if p.ocv_margin_V>=r.voltage(0):raise ValueError('OCV margin removes all available voltage')

    def estimate(self,soc,temperature_C):
        finite('SOC fraction',soc);finite('mock temperature',temperature_C)
        if not 0<=soc<=1:raise ValueError('SOC must be a fraction in [0,1]')
        p=self.p
        low_soc=max(0.,soc-p.soc_margin_fraction)
        ocv=self.reference.voltage(soc)
        guarded_ocv=self.reference.voltage(low_soc)-p.ocv_margin_V
        resistance=p.r0_ohm+p.r0_margin_ohm
        valid=p.temperature_min_C<=temperature_C<=p.temperature_max_C
        voltage_current=max(0.,(guarded_ocv-p.minimum_voltage_V)/resistance)
        soc_current=max(0.,3600*p.capacity_Ah*(low_soc-p.soc_reserve_fraction)/p.soc_budget_horizon_s)
        allowed=min(p.maximum_discharge_A,voltage_current,soc_current) if valid else 0.
        # P(I)=U*I-R*I^2 is not monotonic beyond its maximum-power point.
        at_power=min(allowed,(guarded_ocv/resistance)/2)
        terminal=guarded_ocv-at_power*resistance
        power=max(0.,terminal*at_power)
        for name,value in (('voltage current',voltage_current),('SOC current',soc_current),('SOP',power)):
            finite(name,value)
        reason=('TEMPERATURE_OUTSIDE_ASSUMED_MODEL_RANGE' if not valid else
                'SOC_RESERVE' if soc_current==0 else
                'VOLTAGE_FLOOR' if voltage_current==0 else 'CONSTRAINED_RINT_ESTIMATE')
        return dict(sop_cell_soc_fraction=soc,sop_mock_temperature_C=temperature_C,
            sop_ocv_candidate_V=ocv,sop_guarded_ocv_V=guarded_ocv,
            sop_r0_assumed_ohm=p.r0_ohm,sop_r0_guarded_ohm=resistance,
            sop_max_discharge_A=allowed,sop_current_at_max_power_A=at_power,
            sop_terminal_at_max_power_V=terminal,sop_max_discharge_W=power,
            sop_voltage_constraint_A=voltage_current,sop_soc_budget_constraint_A=soc_current,
            sop_model_valid=valid,sop_reason=reason,sop_physically_validated=False,
            sop_parameter_status=p.parameter_status,
            sop_horizon_scope='Instantaneous Rint voltage; horizon limits charge budget only; no RC/thermal prediction')


def vehicle_mapping(cell_power_W,cell,profile,row):
    """Invert the documented experiment scaling, not a real series/parallel pack.

    Bound rated motor availability, NOT SOP/already-derated delivered power;
    the latter would create a feedback oscillation and miss auxiliary losses.
    """
    finite('cell SOP',cell_power_W)
    if cell_power_W<0:raise ValueError('Discharge SOP must be nonnegative')
    k=-scale_to_cell(1.,cell)['cell_power_requested_W']
    u=profile['unvalidated'];rated=profile['published']['motor_max_power_W']
    torque=profile['published']['motor_max_torque_Nm'];eta=u['drive_efficiency'];aux=u['auxiliary_power_W']
    for name,value in (('rated power',rated),('rated torque',torque),('efficiency',eta),('auxiliary power',aux),
                       ('neutral pedal',u['neutral_pedal']),('speed ceiling',u['max_speed_mps'])):
        finite(name,value)
    for name in ('throttle','brake','speed_mps','soc','motor_power_W'):finite(name,row[name])
    if not 0<=u['neutral_pedal']<1:raise ValueError('Invalid neutral pedal')
    if not 0<eta<=1 or aux<0 or min(rated,torque,k)<=0:raise ValueError('Invalid vehicle conversion basis')
    pack=cell_power_W/k
    finite('inverse scaled pack power',pack)
    motor=min(rated,max(0.,eta*(pack-aux)))
    w=max(0.,finite('motor omega',row['motor_radps']))
    pedal=max(0.,min(1.,(row['throttle']-u['neutral_pedal'])/(1-u['neutral_pedal'])))
    request=min(torque,rated/max(w,1.))*w*pedal
    if row['brake']>.05 or row['speed_mps']>=u['max_speed_mps'] or row['soc']<=0:request=0.
    return dict(sop_cell_per_pack_scale=k,sop_pack_allowable_W=pack,
        sop_motor_allowable_W=motor,sop_motor_requested_unlimited_W=request,
        sop_motor_delivered_W=row['motor_power_W'],sop_vehicle_fraction=motor/rated,
        sop_auxiliary_budget_satisfied=pack>=aux,
        sop_conversion_basis='Existing equivalent-energy experiment scale, configured efficiency/auxiliary load; not a physical pack topology')


class RintPolicy:
    label='RINT SOP: MOCK ASSUMPTIONS + CANDIDATE OCV; NOT PHYSICAL PROTECTION'
    def __init__(self,parameters,mock_soc,mock_temperature_C):
        self.estimator=RintEstimator(parameters)
        self.mock_soc=mock_soc;self.mock_temperature_C=mock_temperature_C
        self.estimator.estimate(mock_soc,mock_temperature_C) # Reject invalid numeric state before launch.
        self.cell=None;self.profile=None

    def configure(self,cell,profile):self.cell,self.profile=cell,profile

    def describe(self):
        return dict(policy='rint',parameters=asdict(self.estimator.p),
            mock_state=dict(soc_fraction=self.mock_soc,temperature_C=self.mock_temperature_C),
            soc_source='Supplied MOCK cell SOC estimate, not native pack SOC or a measured-cell observer',
            ocv_reference=self.estimator.reference.reference_id,
            scaling=asdict(self.cell) if self.cell else None,physical_safety_authorization=False)

    def evaluate_row(self,row):
        if self.cell is None:raise ValueError('Rint mapping requires actual receiver scaling/profile')
        try:
            result=self.estimator.estimate(self.mock_soc,self.mock_temperature_C)
        except ValueError as exc:
            # Keep the diagnostic schema stable without logging NaN or inventing SOC.
            result=self.estimator.estimate(0.,self.estimator.reference.temperature_C)
            for key in ('sop_terminal_at_max_power_V','sop_voltage_constraint_A','sop_soc_budget_constraint_A',
                        'sop_current_at_max_power_A'):
                result[key]=None
            result.update(sop_cell_soc_fraction=None,sop_mock_temperature_C=None,
                sop_ocv_candidate_V=None,sop_guarded_ocv_V=None,sop_model_valid=False,
                sop_max_discharge_A=0.,sop_max_discharge_W=0.,sop_reason=str(exc))
        result.update(vehicle_mapping(result['sop_max_discharge_W'],self.cell,self.profile,row))
        # The existing protocol transmits nine decimal places. Round availability
        # down here so its formatting cannot increase the SOP-derived ceiling.
        result['sop_unquantized_vehicle_fraction']=result['sop_vehicle_fraction']
        result['sop_vehicle_fraction']=math.floor(result['sop_vehicle_fraction']*1e9)/1e9
        return result['sop_cell_soc_fraction'],result['sop_vehicle_fraction'],result
