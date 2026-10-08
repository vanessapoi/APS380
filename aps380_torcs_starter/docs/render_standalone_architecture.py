"""Standalone architecture poster. Existing diagrams are not modified."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parent
fig, ax = plt.subplots(figsize=(24, 19))
ax.set_xlim(0,24); ax.set_ylim(0,19); ax.axis('off')
BLUE='#e8f2fc'; ORANGE='#fff0da'; GREEN='#e8f4e9'; GREY='#f1f3f5'


def text(x,y,s,size=11,weight='normal',ha='left',color='#17344b'):
    ax.text(x,y,s,fontsize=size,fontweight=weight,ha=ha,va='top',color=color,linespacing=1.4)


def box(x,y,w,h,title,body,color=BLUE):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.06',facecolor=color,edgecolor='#4c6578',linewidth=1.2))
    text(x+.16,y+h-.17,title,12,'bold')
    text(x+.16,y+h-.55,body,10.5)


def edge(points,label,at,future=True,physical=False):
    color='#8a5720' if physical else '#476277'
    for a,b in zip(points[:-2],points[1:-1]):
        ax.plot([a[0],b[0]],[a[1],b[1]],color=color,linewidth=1.4,linestyle='--' if future else '-')
    ax.add_patch(FancyArrowPatch(points[-2],points[-1],arrowstyle='-|>',mutation_scale=13,
        color=color,linewidth=1.4,linestyle='--' if future else '-'))
    ax.text(*at,label,fontsize=10,ha='center',va='center',color=color,
        bbox=dict(facecolor='white',edgecolor='none',pad=2),linespacing=1.2)

text(.25,18.8,'APS380 • Driver-in-the-loop battery test platform',25,'bold')
text(.25,18.25,'Standalone software architecture | October 8, 2026 | Positive cell current = discharge; negative = charge',13)
text(.25,17.86,'Solid arrows: working offline files/functions. Dashed arrows: planned integration. Brown arrows: physical effects / protection, not a wiring schematic.',11)
text(.25,17.42,'WORKING NOW — Milestone 1: recorded telemetry → estimated EV demand → signed, bounded single-cell request',15,'bold')
box(.3,14.9,4.1,2.05,'1  Input recordings','Genuine TORCS CSV: source unchanged\nSynthetic CSV: controlled examples\nNo live TORCS or battery connection')
box(5.1,14.9,4.1,2.05,'2  Adapter + validation','curLapTime → seconds; speedX / 3.6\naccel → throttle; brake → brake\nSplit resets / gaps; report exclusions\nNo invented time or stitched laps')
box(9.9,14.9,4.1,2.05,'3  EV demand model','Δv/Δt + interval-average speed\nInertia + rolling + aerodynamic load\nDrive losses, auxiliaries, regen cap\nOptional offline smoothing for studies')
box(14.7,14.9,4.1,2.05,'4  Cell scaling + limits','Nominal cell / pack energy ratio\nOptional experiment reduction factor\nSeparate charge / discharge limits\nLimits are offline examples')
box(19.5,14.9,4.1,2.05,'5  Evidence and outputs','CSV: requested versus limited current\nPlots and effective configuration\n19 tests; smoothing / energy studies\nNo physical current is commanded',GREEN)
for a,b,label in [(4.4,5.1,'CSV'),(9.2,9.9,'SI data'),(14,14.7,'EV watts'),(18.8,19.5,'Cell amps')]:
    edge([(a,15.85),(b,15.85)],label,((a+b)/2,16.15),future=False)
text(.3,14.43,'Configuration is explicit. Each continuous segment is processed independently. The first sample assumes zero acceleration and has zero energy-integration duration.',11)
text(.3,13.94,'PLANNED CLOSED LOOP — Python decides demand and capability; ESP32 executes locally; PCB protection remains independent',15,'bold')

box(.3,10.45,4.1,2.55,'TORCS + Logitech G29','G29 USB input → steering / pedals\nTORCS C/C++ simulates vehicle motion\nExports timestamped driving telemetry\nApplies vehicle power / torque limits\nExporter and feedback hook unverified')
box(6.05,10.45,5.1,2.55,'Python: demand + feedback','Validate telemetry → EV power → cell scale\nUse one allowable-power decision for:\n• signed cell-current request\n• equivalent vehicle power / torque limit\nDo not scale steering or all pedals together')
box(6.05,6.65,5.1,2.35,'Python: battery state + serial','SOC (state of charge): net current counting\nMeasured V / I / T + SOC → separate SOP\nSOP = available charge / discharge power\nUSB serial sends requests; receives status\nLogs commands separately from measurements')
box(14,10.45,4.2,2.55,'ESP32 DevKit firmware','Validate host requests against local limits\nARM / DISARM; heartbeat timeout; faults\nAcquire sensors; map current to eLoad\nDrive disconnect through driver circuitry\nReport actual measurements and state',ORANGE)
box(20.1,10.45,3.5,2.55,'PCB measurements','Cell voltage and temperature\nBidirectional NET cell current\nProposed I²C monitor / ADC\nINA228 / ADS1115 not final\nPins / addresses not assigned',ORANGE)
box(14,6.65,4.2,2.35,'Independent PCB protection','Fuse; over / undervoltage protection\nOvercurrent / temperature trips\nEmergency stop; default-open isolation\nWorks without Python or ESP32\nMay expose a fault-status signal',GREEN)
box(20.1,6.65,3.5,2.35,'Instruments + cell','BK 8500: CC load draws current\nPSU supplies current; manual first\nCombined branches stress 18650\nNet current must be measured\nControlled battery disconnect',ORANGE)
edge([(4.4,12.2),(6.05,12.2)],'Driving telemetry\nCSV first; UDP later',(5.23,12.62))
edge([(6.05,11.15),(4.4,11.15)],'Allowed vehicle power\nProposed localhost UDP',(5.23,10.83))
edge([(8,9),(8,10.45)],'Measured V + separate SOP\nfeed the common limiter',(8,9.72))
edge([(10,10.45),(10,9)],'Demand / decisions\nfeed logs',(10.15,9.6))
edge([(11.15,12.2),(14,12.2)],'USB serial: signed amps,\nARM / DISARM, heartbeat',(12.57,12.65))
edge([(14,11.0),(12.4,11.0),(12.4,7.75),(11.15,7.75)],'USB serial: timestamped\nV / I / T, state and faults',(12.45,9.4))
edge([(20.1,12),(18.2,12)],'Sensor samples\nI²C / ADC',(19.15,12.5))
edge([(18.2,10.9),(19.15,10.9),(19.15,8.3),(20.1,8.3)],'BK: verified serial interface\nPSU remote control optional',(19.05,9.55))
edge([(18.2,10.55),(18.65,10.1),(18.65,7.2),(20.1,7.2)],'GPIO via driver\nDisconnect request',(18.75,7.75))
edge([(18.2,6.95),(20.1,6.95)],'Independent\nphysical trip',(19.15,6.65),physical=True)
edge([(16.1,9),(16.1,10.45)],'Fault indication if available\nProtection does not wait for MCU',(16.1,9.7))
edge([(23.8,7.8),(23.8,11.4),(23.6,11.4)],'Physical cell\nconditions',(23.2,9.6),physical=True)

text(.3,5.98,'ON-PAGE DESIGN NOTES — definitions, assumptions and unresolved interfaces',15,'bold')
box(.3,2.58,5.45,2.98,'Vehicle and current equations','a = Δv / Δt; v = mean interval speed\nPwheel = (m a + m g Crr + ½ ρ CdA v²) v\nDrive: Pbattery = Pwheel / ηdrive + Paux\nBraking: −capped recovery × ηregen + Paux\nk = (Vnom × capacityAh / packWh) × scale\nPcell = k × Pbattery; Ioffline = Pcell / Vnom\nClamp to [−Icharge_limit, +Idischarge_limit]',GREY)
box(6.2,2.58,5.45,2.98,'Live battery decisions and feedback','SOCnext = SOC − Imeasured Δt / (3600 Ah)\nUse measured NET current, not commands\nSOP supplies separate charge / discharge bounds\nAllowed power also respects cell current limits\nIrequest = Pallowed / valid measured voltage\nUse the SAME effective k for vehicle feedback\nHandle zero demand and sign transitions explicitly',GREY)
box(12.1,2.58,5.45,2.98,'PSU / eLoad mapping is conditional','Icell = IeLoad − IPSU at the common network\nOnly if constant PSU bias is verified:\nIeLoad_request = Ibias + Icell_request\nPSU current limit is not measured PSU current\nLoad requests must be nonnegative / achievable\nZero software amps do not guarantee zero current\nProtection must prevent unintended PSU charging',GREY)
box(18,2.58,5.6,2.98,'Implementation boundaries','Python has no hardware commands today\nUSB serial format / timing remain to be designed\nBK interface / isolation / low-voltage limits unverified\nPSU model unknown; remote control is optional\nA GUI and a separate BMS module are not required\nLocal watchdog does not replace PCB protection\nPC → eLoad is only a fallback if ESP32 link fails',GREY)
box(.3,.25,11.35,1.9,'What the current profiles establish','Genuine-source ingestion and repeatable equations / limits are verified. Power is estimated, not measured.\nThe likely source-car model uses 1150 kg and body CdA = 0.672 m²; wings, grade and slip are omitted.\nSmoothing and experiment scaling are explicit study choices; a 0.2 factor sacrifices nominal C-rate equivalence.\nExample current limits are not approved cell ratings. This architecture is not a wiring or protection schematic.',GREEN)
box(12.1,.25,11.5,1.9,'Next milestones','Select and justify a demonstration profile → verify sensor/action timing → record this team’s TORCS / G29 data.\nChoose the exact cell and approved envelope → mock USB serial → validate ESP32 sensing and instrument control.\nThen add measured-current SOC, separate SOP limits and vehicle derating from the common power calculation.\nIndependent PCB protection requires its own implementation and validation throughout hardware development.',GREEN)

for suffix in ('svg','png','pdf'):
    fig.savefig(OUT/f'APS380_standalone_architecture.{suffix}',dpi=180,bbox_inches='tight',facecolor='white')
plt.close(fig)
print('Created standalone SVG, PNG and single-page PDF; earlier artifacts untouched.')
