#!/usr/bin/env python3
"""Chapter 5 traffic diagrams; Python standard library only.

Copyright (C) 2026 Bernhard Wymann. Generator: GPL-2.0-or-later.
Generated diagrams: GNU FDL 1.2 or later, no invariant/cover sections.
"""
import math
from generate_speed_figures import text, line, rect, path, car, curve, key, plot_frame
from generate_path_figures import document, road, dot, INK, MUTED, BLUE, TEAL, RED, AMBER


def diagram(name,title,description,body,height=540):
    document(name,title,description,body,height,generator='generate_traffic_figures.py',eyebrow='COLLISION AVOIDANCE AND OVERTAKING')


def gap():
    a,b,y=110,545.2,220
    body=text(24,98,'Use bumper-to-bumper space in the local road frame.',16,MUTED)
    body+=road('M55 220 H740',70)+car(a,y,90,.4)+car(b,y,90,.4)
    body+=text(a,164,'Our car',17,RED,True,anchor='middle')+text(b,164,'Leader',17,BLUE,True,anchor='middle')
    body+=line(a+25.6,267,a+25.6,300,MUTED,1)+line(b-25.6,267,b-25.6,300,MUTED,1)
    body+=line(a+25.6,283,b-25.6,283,TEAL,2)
    body+=text((a+b)/2,313,'Gap g = 30 m',18,TEAL,True,anchor='middle')
    body+=line(a+40,y,a+100,y,RED,2,'marker-end="url(#red)"')
    body+=line(b+40,y,b+90,y,BLUE,2,'marker-end="url(#blue)"')
    body+=text(96,376,'Our speed: 20 m/s',17,RED,True)+text(475,376,'Leader speed: 15 m/s',17,BLUE,True)
    body+=text(96,412,'Desired gap: 5 m + 1 s × 20 m/s = 25 m',17,INK)
    body+=text(96,444,'Following target: 15 + 0.5 × (30 − 25) = 17.5 m/s',17,TEAL)
    body+=text(24,506,'Worked example: 4 m cars. Center separation includes both half-lengths.',15,MUTED)
    diagram('traffic-gap.svg','Choose a gap, then adjust the speed.',
            'Two four-metre cars with a thirty-metre gap illustrate desired time-gap feedback. Own speed twenty and leader speed fifteen give a following target of seventeen point five metres per second.',body)


def wrap():
    body=text(24,98,'A 1000 m lap. Travel direction is to the right in this local view.',16,MUTED)
    body+=road('M55 250 H745',90)
    body+=line(400,178,400,322,INK,2,'stroke-dasharray="5 5"')
    body+=text(400,153,'Start / finish',17,INK,True,anchor='middle')
    body+=car(250,250,90,.45)+car(550,250,90,.45)
    body+=text(250,202,'Us: s = 990 m',17,RED,True,anchor='middle')
    body+=text(550,202,'Other: s = 10 m',17,BLUE,True,anchor='middle')
    body+=line(250,354,550,354,TEAL,2,'marker-end="url(#teal)"')
    body+=text(400,386,'20 m ahead across the line',18,TEAL,True,anchor='middle')
    body+=text(100,442,'Raw difference: 10 − 990 = −980 m',17,MUTED)
    body+=text(100,473,'Wrapped difference: −980 + 1000 = +20 m',17,TEAL)
    body+=text(24,517,'A lap counter ranks the race. Nearby traffic needs physical separation.',15,MUTED)
    diagram('traffic-wrap.svg','The start line is not a gap in the road.',
            'A car ten metres before the start line sees a car ten metres after it twenty metres ahead, despite the negative raw difference in lap coordinates.',body,550)


def footprint():
    body=''
    for offset,angle in [(16,0),(408,45)]:
        b=rect(0,0,376,365,'#fff','#dfe6e7',12)
        b+=text(20,35,'Aligned with the road' if angle==0 else 'Rotated by 45°',20,bold=True)
        b+=rect(70,80,236,210,'#f0f4f4')
        b+=line(70,80,70,290,'#bbc9cd')+line(306,80,306,290,'#bbc9cd')
        b+=line(35,172,35,111,BLUE,1.8,'marker-end="url(#blue)"')
        b+=text(16,199,'Road',13,BLUE)
        # Rectangle L=4, W=2 at 28 drawing units per metre.
        pts=[]
        for x,y in [(-28,-56),(28,-56),(28,56),(-28,56)]:
            a=math.radians(angle);pts.append((188+x*math.cos(a)-y*math.sin(a),185+x*math.sin(a)+y*math.cos(a)))
        b+=car(188,185,angle,.85)+curve(pts+[pts[0]],AMBER,'4 3',1.5)
        left=min(p[0] for p in pts);right=max(p[0] for p in pts)
        b+=line(left,269,right,269,TEAL,2)+line(left,259,left,279,TEAL,1)+line(right,259,right,279,TEAL,1)
        width=2*math.cos(math.radians(angle))+4*math.sin(math.radians(angle))
        b+=text(188,318,f'Projected width: {width:.2f} m',18,TEAL,True,anchor='middle')
        b+=text(20,345,'Same 4 m × 2 m rectangular body.',15,MUTED)
        body+=f'<g transform="translate({offset} 90)">{b}</g>'
    body+=text(24,500,'Use body yaw and dimensions. A stopped car still has a footprint.',16,MUTED)
    diagram('traffic-footprint.svg','Orientation changes occupied space.',
            'Equal road panels compare a four-by-two-metre car aligned with the road and rotated forty-five degrees. Projected width changes from two to four point two four metres independently of speed.',body)


def closing():
    body,x,y=plot_frame(0,6,0,75,[0,1,2,3,4,5,6],[0,15,30,45,60,75],'Time t (s)','Predicted gap g(t) (m)')
    body+=curve([(x(t/20),y(40-10*t/20)) for t in range(81)],RED)
    body+=curve([(x(t/20),y(40)) for t in range(121)],BLUE,'6 4')
    body+=curve([(x(t/20),y(40+5*t/20)) for t in range(121)],TEAL)
    body+=key(95,91,'Closing: u = +10 m/s',RED)+key(335,91,'Equal: u = 0',BLUE,'6 4')+key(530,91,'Separating: u = −5 m/s',TEAL)
    body+=dot(x(4),y(0),'4 s to close this gap',RED,-14,-19)
    body+=text(24,506,'Initial gap 40 m. Speeds held constant; the driver must react before contact.',15,MUTED)
    diagram('traffic-closing.svg','Closing speed gives a time estimate.',
            'Constant-speed gap curves begin at forty metres. Closing at ten metres per second reaches zero after four seconds; equal speeds keep the gap, and a faster leader increases it.',body)


def corridor():
    body=''
    for offset,blocked in [(16,False),(408,True)]:
        b=rect(0,0,376,385,'#fff','#dfe6e7',12)
        b+=text(20,35,'Both sides occupied' if blocked else 'A candidate on the left',20,bold=True)
        b+=rect(70,80,240,225,'#f0f4f4')
        b+=line(70,80,70,305,'#bbc9cd')+line(310,80,310,305,'#bbc9cd')
        b+=line(190,80,190,305,'#a7b9c0',1.4,'stroke-dasharray="7 8"')
        b+=rect(133,92,44,202,'#e3f1eb' if not blocked else '#f7e9db',radius=5)
        if blocked:b+=rect(203,92,44,202,'#f7e9db',radius=5)
        b+=car(190,271,0,.29)+text(214,288,'Us',14,RED,True)
        b+=car(190,138,0,.29)+text(214,141,'Leader',14,BLUE,True)
        if blocked:
            b+=car(155,227,0,.29)+car(225,227,0,.29)
            b+=text(20,341,'No usable side: keep following.',15,MUTED)
        else:
            b+=line(179,247,155,198,TEAL,2,'marker-end="url(#teal)"')+dot(155,193,'Target',TEAL,-28,-17)
            b+=text(20,341,'Reserve room for our body and margin.',15,MUTED)
        b+=text(20,366,'Check the transition and approaching cars.',14,MUTED)
        body+=f'<g transform="translate({offset} 90)">{b}</g>'
    body+=text(24,514,'Shading marks candidate side space; it is not a predicted vehicle trajectory.',15,MUTED)
    diagram('traffic-corridor.svg','Empty road ahead is only part of the check.',
            'Two matching road panels show a left-side passing candidate and a situation with cars occupying both sides. The driver must account for the full transition corridor, the road edges and other cars.',body,550)


def targets():
    body=''
    for offset,bend in [(16,False),(408,True)]:
        b=rect(0,0,376,365,'#fff','#dfe6e7',12)
        b+=text(20,35,'On a straight' if not bend else 'On a left bend',20,bold=True)
        if bend:
            cx,cy,r=88,128,145
            q=(cx+r/math.sqrt(2),cy+r/math.sqrt(2));t=(q[0]-20/math.sqrt(2),q[1]-20/math.sqrt(2))
            b+=road('M60 273 H88 A145 145 0 0 0 233 128 V90',64)
            b+=dot(cx,cy,'Curve center',MUTED,-65,-12)
            b+=dot(*q,'Q',BLUE,15,12)+dot(*t,'Q + d n',TEAL,-52,-15)
            b+=line(*q,*t,TEAL,2,'marker-end="url(#teal)"')
            b+=text(20,329,'Use the tangent at Q, after the arc.',15,MUTED)
        else:
            b+=road('M218 260 V100',90)
            b+=car(218,263,0,.32)
            b+=dot(218,158,'Q',BLUE,15,5)+dot(190,158,'Q + d n',TEAL,-108,5)
            b+=line(214,158,195,158,TEAL,2,'marker-end="url(#teal)"')
            b+=text(20,329,'The normal points to the road’s left.',15,MUTED)
        b+=text(20,353,'Positive d moves the target left.',15,TEAL)
        body+=f'<g transform="translate({offset} 90)">{b}</g>'
    body+=text(24,505,'The offset changes the steering target. It does not prescribe the car’s sideways speed.',15,MUTED)
    diagram('traffic-target.svg','Move the point in the road’s normal direction.',
            'A straight and a left curve show a positive offset applied to the centerline target along its local left normal. On the left bend this points toward the curve center.',body)


def phases():
    body=''
    configs=[('1 / Follow',100,175,245,175,'Match speed while sharing a lane.'),
             ('2 / Pass',200,124,245,175,'Hold the chosen side alongside.'),
             ('3 / Become clear',287,124,135,175,'Wait for rear-to-front clearance.'),
             ('4 / Return',287,175,112,175,'Check the corridor before moving back.')]
    for i,(title,ux,uy,px,py,caption) in enumerate(configs):
        b=rect(0,0,376,310,'#fff','#dfe6e7',12)
        b+=text(20,35,title,20,bold=True)
        b+=rect(32,89,312,172,'#f0f4f4')
        b+=line(32,89,344,89,'#bbc9cd')+line(32,261,344,261,'#bbc9cd')
        b+=line(32,175,344,175,'#a7b9c0',1.2,'stroke-dasharray="7 8"')
        b+=car(ux,uy,90,.3)+car(px,py,90,.3)
        b+=text(ux,max(110,uy-26),'Us',14,RED,True,anchor='middle')+text(px,py+35,'Pace',14,BLUE,True,anchor='middle')
        b+=text(20,292,caption,14,MUTED)
        body+=f'<g transform="translate({16+392*(i%2)} {90+330*(i//2)})">{b}</g>'
    body+=text(24,773,'Separate schematic snapshots; travel is to the right. Returning is a decision, too.',15,MUTED)
    diagram('traffic-phases.svg','Remember where you are in the manoeuvre.',
            'Four equal road panels show the tutorial car following, passing alongside in the left lane, becoming fully clear, and returning to the centerline. Each scene is a schematic snapshot, not recorded motion.',body,800)


def holding():
    body=''
    for offset,cancelled in [(16,False),(408,True)]:
        b=rect(0,0,376,410,'#fff','#dfe6e7',12)
        b+=text(20,35,'Withdraw the stale request' if cancelled else 'A frozen target still steers',19,bold=True)
        b+=rect(70,80,240,255,'#f0f4f4')
        b+=line(70,80,70,335,'#bbc9cd')+line(310,80,310,335,'#bbc9cd')
        b+=line(190,80,190,335,'#a7b9c0',1.2,'stroke-dasharray="7 8"')
        b+=car(190,225,-8,.32)+text(216,230,'Us',14,RED,True)
        b+=car(110,300,0,.32)+text(83,355,'Rear car',13,BLUE,True)
        b+=line(110,270,110,197,BLUE,2,'marker-end="url(#blue)"')
        if cancelled:
            b+=line(105,125,115,135,MUTED,1.4)+line(105,135,115,125,MUTED,1.4)
            b+=text(77,108,'Withdrawn',13,MUTED)
            b+=dot(206,130,'Hold',TEAL,15,-15)
            b+=line(195,196,205,138,TEAL,2,'marker-end="url(#teal)"')
            b+=text(20,385,'Hold our lane and oppose the drift.',15,MUTED)
        else:
            b+=dot(110,130,'Stale target',RED,-27,-20)
            b+=line(174,199,117,141,RED,2,'marker-end="url(#red)"')
            b+=text(20,385,'The car is still being asked to move left.',15,MUTED)
        body+=f'<g transform="translate({offset} 90)">{b}</g>'
    body+=text(24,538,'Same pose and approaching car. The holding correction uses actual lateral velocity.',15,MUTED)
    body+=text(24,565,'Arrows are references: withdrawing a target does not stop vehicle motion instantly.',15,MUTED)
    diagram('traffic-hold.svg','Cancel the request, not just its rate of change.',
            'Matching panels show a car already turning left and another car approaching in that lane. A frozen left-side target continues the request. Withdrawing it and using a lane-holding correction opposes drift while waiting for a checked return.',body,590)


if __name__=='__main__':
    for generate in (gap,wrap,footprint,closing,corridor,targets,phases,holding):generate()
    print('Generated eight Chapter 5 traffic diagrams with explicit geometry and units.')
