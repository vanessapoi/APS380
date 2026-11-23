"""Opt-in mock composition; shares the bias observer and Rint estimator."""
from live_cell_state import LiveRintPolicy


def propulsion_run_observed(rows):
    """A valid zero-SOP run is operation, not a missing propulsion test.

    Require a native acknowledgement of a command generated from a RUNNING,
    VALID model. Startup zero, unavailable model and unacknowledged values fail.
    """
    sent={r['vehicle_limit_sent_sequence']:r['vehicle_limit_requested_fraction'] for r in rows
        if 'vehicle_limit_sent_sequence' in r and r.get('bias_controller_state')=='RUNNING'
        and r.get('cell_observer_state')=='VALID' and r.get('sop_model_valid') is True}
    return any(r.get('vehicle_limit_state')=='ACTIVE' and r.get('vehicle_limit_ack_sequence') in sent
        and abs(r['vehicle_limit_applied_fraction']-sent[r['vehicle_limit_ack_sequence']])<=1e-9 for r in rows)


class BiasRintPolicy(LiveRintPolicy):
    label='BATTERY BIAS LIVE MOCK SOC / RINT; NOT PHYSICAL PROTECTION'

    def __init__(self, service):
        stream=service.cell_stream
        if stream is None:raise ValueError('Bias feedback requires the existing cell observer')
        super().__init__(stream.parameters,stream.initial_soc,25.,stream.observer)
        self.estimator=stream.estimator
        self.service=service
        self.was_running=False

    def describe(self):
        return dict(super().describe(),policy='battery-bias-rint-mock',
            soc_source='Existing Battery Bias independent MOCK cell sensor observer')

    def evaluate_row(self,row):
        soc,fraction,details=super().evaluate_row(row)
        snapshot=self.service.latest
        state=snapshot['state']
        if details['cell_observer_state']=='STALE':
            fraction=0.
            details.update(sop_vehicle_fraction=0.,sop_model_valid=False,
                sop_waiting_for_measurement=True,sop_reason='MOCK_CELL_SAMPLE_STALE; zero availability pending fresh acquisition')
        details.update(cell_measurement_source='battery_bias_mock_sensor',
            cell_voltage_source='mock_sensor_voltage',cell_temperature_source='mock_sensor_temperature',
            bias_controller_state=state,bias_controller_fault=snapshot.get('fault',''))
        if state=='RUNNING':self.was_running=True
        else:
            fraction=0.
            details.update(sop_vehicle_fraction=0.,sop_model_valid=False,
                sop_waiting_for_measurement=not self.was_running and state in ('DISARMED','READY'),
                sop_reason='BIAS_'+state+'; propulsion unavailable')
        return soc,fraction,details
