# Project decision guidance

Before making major architecture, modelling, control, hardware-interface or implementation-scope decisions, read [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) in this directory and inspect the relevant current code and documentation.

Treat the established architecture decisions in that context as the project baseline. Current explicit user instructions take precedence; when they change the architecture, update the context consistently, including responsibility lists, communication tables and milestones. Do not silently replace established decisions with older proposals or assumptions. Distinguish intended architecture from implemented and verified behaviour.

In particular:

- The PC connects directly to both the eLoad and PSU; Python owns instrument communication and signed cell-current demand mapping.
- SOC and SOP calculations run on the PC using measured cell data.
- The ESP32 provides sensing, timestamped measurements/status, local supervision and isolation coordination; it is not an instrument-command bridge.
- Independent hardware protection remains separate from PC and firmware control.

Consult the project context before changing these boundaries, adding major subsystems or choosing a different feedback/control strategy. Keep tests and documentation aligned with any authorized change.
