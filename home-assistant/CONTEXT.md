# Home Assistant Dashboard

Runs on the local PC. Presents live monitoring, historical trends and Clips from the Correlator, and is where a person records Review Decisions. It never opens the Correlator's database: everything goes through the Correlator's web service. Reachable from the PC itself only, for now.

## Architecture

A Home Assistant container in the Frigate stack. Its sidebar entry "FluentPet Board" shows the Correlator's own pages (live view, Review Queue, history), and it polls a few figures from the Correlator as sensors for its own cards and automations.

- **config/configuration.yaml**: the sidebar entry and the sensors.
- **config/dashboards/**: the dashboard shown by the sidebar entry.
- Everything else in **config/** is Home Assistant's own runtime data (not committed).

## Language

**Review Queue**:
The list of Ambiguous Presses that have no Review Decision yet, shown with their Clips so a person can decide each one.
_Avoid_: Inbox, backlog, pending list
