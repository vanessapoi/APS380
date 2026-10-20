#!/usr/bin/env python3
"""Chapter 6 diagrams. Copyright (C) 2026 Bernhard Wymann.
Generator: GPL-2.0-or-later. Diagrams: GNU FDL 1.2-or-later, no invariant/cover sections.
Run with python3 -B; all plots are computed, not simulator traces.
"""
from generate_speed_figures import text, line, rect, path, car, curve, key, plot_frame
from generate_path_figures import document, dot, INK, MUTED, BLUE, TEAL, RED, AMBER


def diagram(name,title,description,body,height=560):
    document(name,title,description,body,height,generator='generate_pit_figures.py',eyebrow='PIT STOPS AND THE COMPLETE DRIVER')


def hermite(t,p,q,h,m=0,n=0):
    return (2*t**3-3*t*t+1)*p+(t**3-2*t*t+t)*h*m+(-2*t**3+3*t*t)*q+(t**3-t*t)*h*n


def route():
    points=[(0,0),(60,-10),(100,-10),(120,-14),(140,-10),(200,-10),(260,0)]
    samples=[]
    for (s,d),(end,e) in zip(points,points[1:]):
        samples.extend((s+(end-s)*i/40,hermite(i/40,d,e,end-s)) for i in range(41))
    x=lambda s:70+2.5*s
    body=text(24,96,'Illustrative right-side route. Plan-view longitudinal and lateral scales differ.',15,MUTED)
    body+=rect(40,117,720,58,'#f0f4f4')+rect(70,175,650,45,'#f7f0e4')
    body+=line(40,145,760,145,'#a7b9c0',1.4,'stroke-dasharray="7 8"')
    body+=line(70,221,720,221,'#bbc9cd',1.3)
    body+=curve([(x(s),145-4*d) for s,d in samples],TEAL)
    for i,(s,d) in enumerate(points):
        body+=dot(x(s),145-4*d,color=TEAL)+line(x(s),151-4*d,x(s),235,'#bbc9cd',1)
        body+=text(x(s),254,'p'+str(i),14,INK,True,anchor='middle')
    body+=text(88,308,'Offset d(s) (m): the function evaluated by the driver',16,BLUE,True)
    y=lambda d:345-8*d
    for d in [0,-5,-10,-15]:
        body+=line(70,y(d),720,y(d),'#e0e8ea',1)+text(56,y(d)+5,str(d),13,MUTED,anchor='end')
    body+=curve([(x(s),y(d)) for s,d in samples],TEAL)
    for s in [0,60,120,200,260]:body+=text(x(s),494,str(s),13,MUTED,anchor='middle')
    body+=text(390,520,'Distance from pit entry s (m)',15,MUTED,anchor='middle')
    body+=text(24,558,'Zero knot slopes make local parallel joins. The box point is p3; it does not itself stop the car.',14,MUTED)
    diagram('pit-route.svg','One route, seven useful milestones.',
            'An illustrative right-side pit route and its numerical distance-offset graph share seven labelled milestones: entry, lane-ready, box approach, box, departure, merge start and exit.',body,590)


def basis():
    body,x,y=plot_frame(0,1,-.25,1.1,[0,.25,.5,.75,1],[-.25,0,.5,1],'Normalized interval coordinate t','Basis function value')
    for label,f,color,dash,offset in [('H₀₀',lambda t:2*t**3-3*t*t+1,BLUE,'',95),('H₀₁',lambda t:-2*t**3+3*t*t,TEAL,'',260),('H₁₀',lambda t:t**3-2*t*t+t,AMBER,'6 4',425),('H₁₁',lambda t:t**3-t*t,RED,'6 4',590)]:
        body+=key(offset,91,label,color,dash)
        body+=curve([(x(i/100),y(f(i/100))) for i in range(101)],color,dash)
    body+=text(24,510,'Value weights multiply endpoint offsets. Slope weights multiply h times the endpoint slopes.',14,MUTED)
    diagram('pit-basis.svg','Four functions encode the endpoint conditions.',
            'The four cubic Hermite basis functions over zero to one. Two encode endpoint values and two encode normalized endpoint derivatives.',body)


def worked():
    body,x,y=plot_frame(0,20,0,5.5,[0,5,10,15,20],[0,1,2,3,4,5],'Distance s (m)','Offset d (m)')
    body+=text(24,92,'Example: d₀ = 0 m, d₁ = 5 m, h = 20 m, both endpoint slopes zero',15,MUTED)
    body+=curve([(x(i/5),y(hermite(i/100,0,5,20))) for i in range(101)],TEAL)
    body+=curve([(x(i/5),y(i/20)) for i in range(101)],MUTED,'5 5',1.5)
    body+=dot(x(5),y(.78125),'(5 m, 0.78125 m)',TEAL,-143,-40)
    body+=key(90,501,'Cubic Hermite',TEAL)+key(350,501,'Linear interpolation',MUTED,'5 5')
    body+=text(24,540,'The cubic matches the specified endpoint slopes. Linear interpolation has slope 0.25.',14,MUTED)
    diagram('pit-worked.svg','Same endpoints, different approach directions.',
            'Calculated cubic and linear interpolants from zero to five metres over twenty metres. The zero-slope Hermite cubic evaluates to 0.78125 metres at distance five metres.',body,570)


def continuity():
    body=text(24,97,'Two intervals: 0 → 5 m over 20 m, then 5 → 0 m over 30 m; zero knot slopes.',15,MUTED)
    x=lambda s:88+660*s/50
    for order,lo,hi,ticks,label,top in [(0,0,5.5,[0,2.5,5],'Offset d (m)',150),(1,-.3,.4,[-.25,0,.375],'Slope d′ (m/m)',330),(2,-.09,.09,[-.075,0,.075],'Second derivative d″ (1/m)',510)]:
        y=lambda v:top+110-(v-lo)/(hi-lo)*110
        body+=text(88,top-15,label,15,BLUE,True)
        for value in ticks:
            body+=line(88,y(value),748,y(value),'#e0e8ea',1)+text(76,y(value)+4,f'{value:g}',12,MUTED,anchor='end')
        body+=line(x(20),top,x(20),top+110,MUTED,1,'stroke-dasharray="4 5"')
        for start,h,p,q,color in [(0,20,0,5,BLUE),(20,30,5,0,TEAL)]:
            vals=[]
            for i in range(101):
                t=i/100
                v=hermite(t,p,q,h) if order==0 else ((q-p)*6*t*(1-t)/h if order==1 else (q-p)*6*(1-2*t)/h**2)
                vals.append((x(start+t*h),y(v)))
            body+=curve(vals,color)
        if order==2:
            for value,color in [(-.075,BLUE),(-1/30,TEAL)]:body+=f'<circle cx="{x(20)}" cy="{y(value)}" r="4" fill="#fffdfa" stroke="{color}" stroke-width="2"/>'
        for s in [0,10,20,30,40,50]:body+=text(x(s),top+129,str(s),12,MUTED,anchor='middle')
    body+=text(373,135,'Join at s = 20 m',14,MUTED)
    body+=text(24,673,'Value and slope agree. Open circles mark different one-sided second-derivative limits.',14,MUTED)
    diagram('pit-continuity.svg','C¹ continuity does not promise C² continuity.',
            'Three calculated plots show offset and slope continuous across the twenty-metre join, while the second derivative has distinct left and right limits. Horizontal axes show distance in metres.',body,700)


def capture():
    body=text(24,96,'Illustrative 4 m × 2 m rectangular car in a 12 m × 5 m box.',15,MUTED)
    body+=rect(100,200,600,250,'#f0f4f4','#bbc9cd')
    body+=rect(200,250,400,150,'#e3f1eb')
    body+=line(200,163,600,163,TEAL,1.5)+text(400,146,'Longitudinal center range',17,TEAL,True,anchor='middle')
    for x in [200,600]:body+=line(x,157,x,438,TEAL,1,'stroke-dasharray="5 5"')
    body+=text(100,187,'Inner edge',14,MUTED)
    body+='<defs><pattern id="pitwall" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M-2 8 L8 -2 M2 10 L10 2" stroke="#bbc9cd" stroke-width="2"/></pattern></defs>'
    body+=rect(100,450,600,14,'url(#pitwall)')+line(100,450,700,450,INK,2)
    body+=car(400,350,90,1.54)
    body+=rect(300,300,200,100,'none',AMBER)+dot(400,350,color=TEAL)
    body+=text(520,314,'Center',15,TEAL,True)+line(515,319,407,346,TEAL,1)
    body+=text(24,507,'Position alone is insufficient: both body-frame speeds must be below 1 m/s.',15,MUTED)
    body+=text(24,535,'The pit must be free and requested. Barrier clearance remains a separate requirement.',14,MUTED)
    diagram('pit-capture.svg','Stop inside the assigned capture region.',
            'An aligned rectangular car inside an illustrative pit box. Dashed lines bound the allowed longitudinal center range, the outer barrier is hatched, and text states the service-request, occupancy and speed conditions.',body,565)


def ownership():
    rows=[('Racing','Traffic chooses lateral intent; track and traffic restrict speed.','Recovery can override a stuck car when nearby space is clear.'),
          ('Pit travel','The pit spline owns steering. Apply road, pit, box and traffic speed caps.','Main-road edge clamps must not pull the car out of the pit lane.'),
          ('Stopping and service','Stop deliberately, request service, then wait for the engine’s release.','Recovery must not mistake the intentional stop for being stuck.'),
          ('Exit and rejoin','Keep the pit route after service. Check the corridor before merging.','Once the body is on the main road, reset traffic into a checked return.')]
    body=''
    for i,(title,a,b) in enumerate(rows):
        y=100+125*i
        body+=rect(24,y,752,105,'#fff','#dfe6e7',12)+text(44,y+30,title,20,BLUE,True)
        body+=text(44,y+60,a,15,MUTED)+text(44,y+86,b,15,MUTED)
        if i<3:body+=line(400,y+108,400,y+122,TEAL,1.8,'marker-end="url(#teal)"')
    body+=text(24,625,'One control owner per update; handoffs reset remembered manoeuvres.',16,MUTED)
    diagram('pit-ownership.svg','Bring the components together deliberately.',
            'Four panels explain control ownership during racing, pit travel, stopping and service, and exit and rejoining. The final handoff resets remembered traffic manoeuvres.',body,650)


if __name__=='__main__':
    for generate in (route,basis,worked,continuity,capture,ownership):generate()
    print('Generated six Chapter 6 route, spline, service and integration diagrams.')
