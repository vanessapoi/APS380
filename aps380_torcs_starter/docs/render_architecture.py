"""Render report-ready overview figures; detailed connections are in the companion Markdown."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.backends.backend_pdf import PdfPages

OUT = Path(__file__).resolve().parent
BLUE = '#e7f1fb'
ORANGE = '#fff0d9'
GREEN = '#e6f4eb'


def box(ax,x,y,w,h,title,body,color=BLUE):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.06',linewidth=1.2,edgecolor='#34516b',facecolor=color))
    ax.text(x+w/2,y+h-.25,title,ha='center',va='top',fontsize=11,fontweight='bold',color='#17344b')
    ax.text(x+w/2,y+h-.62,body,ha='center',va='top',fontsize=9,linespacing=1.35,color='#20384b')


def arrow(ax,start,end,label='',future=False,rad=0):
    ax.add_patch(FancyArrowPatch(start,end,arrowstyle='-|>',mutation_scale=12,linewidth=1.3,
        linestyle='--' if future else '-',color='#476277',connectionstyle=f'arc3,rad={rad}'))
    if label:
        ax.text((start[0]+end[0])/2,(start[1]+end[1])/2+.08,label,ha='center',va='bottom',fontsize=8,
                bbox=dict(facecolor='white',edgecolor='none',pad=1))


def canvas(title,subtitle):
    fig,ax=plt.subplots(figsize=(16,10))
    ax.set_xlim(0,16);ax.set_ylim(0,10);ax.axis('off')
    ax.text(.25,9.7,title,fontsize=20,fontweight='bold',color='#17344b')
    ax.text(.25,9.25,subtitle,fontsize=10,color='#476277')
    return fig,ax


def offline():
    fig,ax=canvas('APS380 • Milestone 1: working offline software',
        'Solid arrows = implemented files/functions. All currents are saved requests; no hardware or live simulator control.')
    box(ax,.3,7.1,3.1,1.65,'Original TORCS CSV','Genuine simulator recording\nSource preserved unchanged\nNo battery measurements')
    box(ax,4.2,7.1,3.5,1.65,'TORCS adapter','km/h → m/s; original lap time\nAudit exclusions and boundaries\nSeparate continuous segments')
    box(ax,.3,4.55,3.1,1.65,'Synthetic CSV','Repeatable demo generator\nSame normalized schema')
    box(ax,4.2,4.55,3.5,1.65,'Validation + intervals','Strictly increasing time; finite data\nΔv/Δt and mean interval speed\nNo derivatives across breaks')
    box(ax,8.6,7.1,3.3,1.65,'Optional conditioning','Local-linear speed smoothing\nRecorded timestamps retained\nOffline comparison path only')
    box(ax,8.6,4.55,3.3,1.65,'EV power model','Inertia + rolling + aerodynamic load\nDrive / regen efficiency; auxiliaries\nBraking allocation and regen cap')
    box(ax,8.6,2.05,3.3,1.65,'Cell scaling + limits','Cell / pack nominal energy ratio\nOptional experiment reduction\nSeparate signed current limits')
    box(ax,12.65,2.05,3,1.65,'Outputs','CSV, plots, parameter snapshots\nRaw versus limited demand\nClipping and energy metrics',GREEN)
    box(ax,4.2,2.05,3.5,1.65,'Configuration','Unit-labelled vehicle parameters\nCell capacity, voltage and limits\nExplicit scaling assumptions',ORANGE)
    box(ax,12.65,7.1,3,1.65,'Verification + studies','19 tests at this revision\nSensitivity / braking comparisons\nNo physical calibration claim',GREEN)
    arrow(ax,(3.4,7.9),(4.2,7.9),'M1')
    arrow(ax,(5.95,7.1),(5.95,6.2),'M2')
    arrow(ax,(3.4,5.35),(4.2,5.35),'M3')
    arrow(ax,(7.7,5.35),(8.6,5.35),'M4')
    arrow(ax,(7.7,5.9),(8.6,7.4),'M5')
    arrow(ax,(10.25,7.1),(10.25,6.2),'M6')
    arrow(ax,(10.25,4.55),(10.25,3.7),'M7')
    arrow(ax,(11.9,2.9),(12.65,2.9),'M8')
    arrow(ax,(7.7,3.4),(8.6,4.75),'M9')
    arrow(ax,(7.7,2.8),(8.6,2.8),'M10')
    arrow(ax,(14.15,7.1),(14.15,3.7),'M11')
    ax.text(.3,.8,'Cell current: negative = discharge; positive = charge. First sample has zero integration duration.',fontsize=11)
    ax.text(.3,.35,'Every connection and component is explained in SOFTWARE_ARCHITECTURE.md. Figure revision: October 8, 2026.',fontsize=10,color='#476277')
    return fig


def future():
    fig,ax=canvas('APS380 • intended closed-loop software architecture',
        'Dashed arrows = planned integration. This overview groups internal connections; exact F1–F24 links are in the companion document.')
    box(ax,.3,7.0,3.1,1.8,'G29 + TORCS','Driver input → vehicle physics\nTelemetry export\nVehicle power / torque limit hook')
    box(ax,4.35,7.0,3.5,1.8,'Python demand pipeline','Input / validation → EV model\nPack-to-cell scaling\nRequested signed cell power')
    box(ax,4.35,4.2,3.5,1.85,'Python battery decisions','SOC from measured net current\nSeparate charge / discharge SOP\nCommon allowable-power limiter')
    box(ax,.3,4.2,3.1,1.85,'Vehicle feedback mapping','Use the same allowed-power result\nAccount for effective cell scale\nDo not multiply all driver inputs')
    box(ax,4.35,1.55,3.5,1.7,'Host serial + logging','Send signed current / state requests\nReceive timestamped V/I/T and faults\nLog commands and measurements')
    box(ax,8.8,4.2,3.5,1.85,'ESP32 DevKit firmware','Local limits; ARM/DISARM; heartbeat\nSensor acquisition; load mapping\nDisconnect control; fault reporting',ORANGE)
    box(ax,12.95,7.0,2.7,1.8,'PCB sensing','Net cell voltage / current\nTemperature acquisition\nI²C / ADC as selected',ORANGE)
    box(ax,12.95,4.2,2.7,1.85,'BK 8500 + PSU','eLoad: compatible serial CC\nPSU: manual initially\nRemote PSU control optional',ORANGE)
    box(ax,12.95,1.55,2.7,1.7,'Cell + bench network','PSU supplies; load draws\nMeasure actual net cell current\nControlled isolation',ORANGE)
    box(ax,8.8,1.55,3.5,1.7,'Independent PCB protection','Fuse + V/I/T trip mechanisms\nEmergency stop; default-open isolation\nIndependent of host / ESP32',GREEN)
    arrow(ax,(3.4,7.9),(4.35,7.9),'F2 telemetry',True)
    arrow(ax,(6.1,7.0),(6.1,6.05),'F3–F5 demand',True)
    arrow(ax,(4.35,5.1),(3.4,5.1),'F10',True)
    arrow(ax,(1.85,6.05),(1.85,7.0),'F11 feedback',True)
    arrow(ax,(6.1,4.2),(6.1,3.25),'F9 / F12',True)
    arrow(ax,(7.15,3.25),(7.15,4.2),'F6 / F8',True)
    arrow(ax,(7.85,2.85),(8.8,4.5),'F14 commands',True)
    arrow(ax,(8.8,4.2),(7.85,2.1),'F15 V/I/T',True)
    arrow(ax,(12.95,7.25),(12.3,5.75),'F16',True)
    arrow(ax,(12.3,5.1),(12.95,5.1),'F17 / F18',True)
    arrow(ax,(14.3,4.2),(14.3,3.25),'F20 / F21',True)
    arrow(ax,(15.75,2.4),(15.75,7.9),'F22',True)
    arrow(ax,(12.3,4.25),(12.95,3.15),'F19',True)
    arrow(ax,(12.3,2.25),(12.95,2.25),'F23',True)
    arrow(ax,(10.55,3.25),(10.55,4.2),'F24 status',True)
    ax.text(.3,.9,'F1 is G29 input inside the simulator block. F7 is SOP → limiter inside battery decisions. F13 is measurement logging.',fontsize=10)
    ax.text(.3,.5,'Physical branch / isolation arrows provide context, not a wiring schematic. PSU bias must be verified, never assumed.',fontsize=10)
    ax.text(.3,.12,'Python owns high-level decisions; ESP32 owns local execution; PCB protection must work independently. Revision: October 8, 2026.',fontsize=10,color='#476277')
    return fig


def main():
    with PdfPages(OUT/'APS380_software_block_diagrams.pdf') as pdf:
        for name,build in [('milestone1_software_diagram',offline),('planned_system_diagram',future)]:
            fig=build()
            fig.savefig(OUT/f'{name}.svg',bbox_inches='tight')
            fig.savefig(OUT/f'{name}.png',dpi=160,bbox_inches='tight')
            pdf.savefig(fig,bbox_inches='tight')
            plt.close(fig)


if __name__ == '__main__':
    main()
