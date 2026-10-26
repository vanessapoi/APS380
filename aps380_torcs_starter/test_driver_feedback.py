import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest

from driver_feedback import DriverFeedback,HUD_HELLO,HUD_VALUE_COUNT
from test_torcs_live import PROFILE,CONFIG,packet,accept
from torcs_live import LiveProcessor,LiveReceiver


class DriverFeedbackTest(unittest.TestCase):
    def test_normal_near_and_directional_exceedance(self):
        for demand,expected in ((.5,0),(.9,1),(1.,1),(1.1,2),(-.9,1),(-1.1,3)):
            feedback=DriverFeedback()
            alarm,utilization,excess=feedback.evaluate(demand,1,1,10)
            self.assertEqual(alarm,expected)
            self.assertAlmostEqual(utilization,abs(demand))
            self.assertAlmostEqual(excess,max(abs(demand)-1,0))

    def test_asymmetric_zero_bounds_and_numerical_boundary(self):
        self.assertEqual(DriverFeedback().evaluate(-.3,1,.2,10)[0],3)
        self.assertEqual(DriverFeedback().evaluate(1e-20,0,1,10)[0],2)
        self.assertEqual(DriverFeedback().evaluate(0,0,0,10)[0],0)
        self.assertEqual(DriverFeedback().evaluate(1+1e-12,1,1,10)[0],1)
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):DriverFeedback().evaluate(value,1,1,10)

    def test_red_hold_prevents_flicker_then_clears(self):
        feedback=DriverFeedback()
        self.assertEqual(feedback.evaluate(2,1,1,10)[0],2)
        self.assertEqual(feedback.evaluate(.2,1,1,10.5)[0],2)
        self.assertEqual(feedback.evaluate(.2,1,1,11.01)[0],0)

    def test_wire_contains_unclipped_and_limited_demand(self):
        p=LiveProcessor(PROFILE,CONFIG)
        accept(p,packet(p,power=1e6,session=f'{os.getpid()}-trial-0'))
        parts=DriverFeedback().encode(p,os.getpid(),10.002).decode().split()
        self.assertEqual(parts[0],'APS380HUD1')
        values=list(map(float,parts[5:]))
        self.assertEqual(len(values),HUD_VALUE_COUNT)
        self.assertEqual(values[1],1)
        self.assertEqual(values[2],2)
        self.assertAlmostEqual(values[14],4.2)
        self.assertEqual(values[15],1)
        self.assertAlmostEqual(values[22],3.2)

    def test_stale_and_new_session_do_not_show_healthy_alarm(self):
        p=LiveProcessor(PROFILE,CONFIG)
        accept(p,packet(p,power=1e6,session=f'{os.getpid()}-trial-0'))
        f=DriverFeedback();f.encode(p,os.getpid(),10.002)
        values=list(map(float,f.encode(p,os.getpid(),11).decode().split()[5:]))
        self.assertEqual(values[1:3],[2,0])
        accept(p,packet(p,session=f'{os.getpid()}-new-0'))
        values=list(map(float,f.encode(p,os.getpid(),10.002).decode().split()[5:]))
        self.assertEqual(values[2],0)

    def test_real_udp_visual_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            receiver=LiveReceiver(0,Path(folder)/'trial');receiver.processor.shared_clock=False
            receiver.start()
            hud=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);hud.bind(('127.0.0.1',0));hud.settimeout(2)
            try:
                address=('127.0.0.1',receiver.port)
                hud.sendto(HUD_HELLO+str(os.getpid()).encode(),address)
                data,_=hud.recvfrom(4096)
                self.assertTrue(data.startswith(b'APS380HUD1 '))
                hud.sendto(json.dumps(packet(receiver.processor,power=1e6,
                    session=f'{os.getpid()}-trial-0')).encode(),address)
                data,_=hud.recvfrom(4096)
                values=list(map(float,data.decode().split()[5:]))
                self.assertEqual(values[2],2)
                hud.sendto(HUD_HELLO+f'{os.getpid()} 1 2 1'.encode(),address)
                deadline=time.perf_counter()+2
                while receiver.hud_stats['rendered_acks']==0 and time.perf_counter()<deadline:time.sleep(.01)
                self.assertEqual(receiver.hud_stats['discharge_alert_acks'],1)
            finally:
                receiver.stop_event.set();receiver.worker.join(2)
                receiver.socket.close();receiver.log.close();hud.close()


if __name__=='__main__':unittest.main()
