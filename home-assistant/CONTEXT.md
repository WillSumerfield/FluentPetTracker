# Home Assistant Dashboard

Runs on the local PC. Presents the live picture, each day's Clips and the study's figures from the Correlator, and is where a person records Review Decisions. It never opens the Correlator's database: everything goes through the Correlator's web service. Reachable from the PC and, over the private network the household's devices share, from a phone through the Home Assistant app.

## Architecture

A Home Assistant container in the Frigate stack. Its sidebar lists the Correlator's own pages, and it polls a few figures from the Correlator as sensors for its own automations.

- **Daily Summary**: one day's Clips on a timeline, the player, and where each Press is given its Review Decision.
- **Review**: the Review Queue, one Press at a time.
- **Live Feed**: the camera's picture and sound, as it happens.
- **Metrics**: the study's figures per day, week, month or whole study, the cat and the human always in separate charts.
- **Enrolment**: recording the board through the mic feed and turning it into Reference Clips. The work is Word Detection's.

- **config/configuration.yaml**: the features switched on, the sidebar entries and the sensors.
- **config/dashboards/**: one dashboard per sidebar entry.
- Everything else in **config/** is Home Assistant's own runtime data (not committed).

## Language

**Review Queue**:
The Ambiguous Presses that have no Review Decision yet, oldest first, each shown with its Clip so a person can decide it.
_Avoid_: Inbox, backlog, pending list

**Utterance Alert**:
The message sent to a person's phone when an Exchange closes holding at least one Utterance the pipeline attributed to the cat, or at least one still awaiting review. It lists those Utterances in order, the ones awaiting review marked as such, and leads to the Exchange's Clip. A Review Decision never causes one.
_Avoid_: Press notification, push, ping
