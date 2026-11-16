"""Opt-in mock composition; shares the bias observer and Rint estimator."""
from live_cell_state import LiveRintPolicy


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
