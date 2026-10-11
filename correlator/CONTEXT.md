# Correlator

Runs on the local PC. Custom app that joins Frigate's presence/zone events with Word Detection's Word events (by timestamp) into Press records, resolves Presser attribution, and owns the database that is the source of truth for the longitudinal study.

## Architecture

A Python service that runs as a container in the Frigate stack. It listens to both event streams on the MQTT broker, writes the database, and asks Frigate for each Clip.

- **correlator/**: the service, plus a tool that prints what the database holds.
- **data/**: the database and the Clips (not committed).
- **Dockerfile**, **requirements.txt**: how the container is built.

## Language

**FluentPet Board**:
The physical board with buttons mapped to Words, used by the pet.
_Avoid_: Device, panel

**Press**:
An instance of a button being activated, producing a Word. A Press whose Word came from an Uncertain Match is still a Press, and carries that flag.
_Avoid_: Click, activation, trigger

**Presser**:
The subject (human or pet) attributed as having caused a Press.
_Avoid_: User, actor

**Ambiguous Press**:
A Press with no single candidate Presser: either both the human and the pet were in the Board Zone, or nobody was. Flagged for manual review rather than guessed.
_Avoid_: Unknown press, unresolved press

**Utterance**:
An ordered sequence of Presses occurring within a short time window, treated as one meaningful unit for the study (e.g. "want" + "outside").
_Avoid_: Sequence, phrase, sentence

**Clip**:
The video of one Utterance, cut from Frigate's recording: it starts shortly before the first Press and ends when the Utterance closes. Every Utterance has exactly one Clip.
_Avoid_: Recording, footage, video segment

**Observation Window**:
A continuous stretch of time during which the whole pipeline was live, so any Press would have been captured and attributed. The study reports usage per observed time, not per calendar day.
_Avoid_: Uptime, session, recording period

**Connect Board**:
FluentPet's network-connected board variant with its own API for press signals. Integration deferred to a future phase — board not yet owned, capabilities unconfirmed.
_Avoid_: Smart board
