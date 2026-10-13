# Correlator

Runs on the local PC. Custom app that joins Frigate's presence/zone events with Word Detection's Word events (by timestamp) into Press records, resolves Presser attribution, and owns the database that is the source of truth for the longitudinal study.

## Architecture

Two containers in the Frigate stack, built from the same code. The recording service listens to both event streams on the MQTT broker, writes the database, and asks Frigate for each Clip. The web service serves the dashboard pages and the API behind them; the only thing it writes is a Review Decision.

- **correlator/**: the recording service, the web service with its pages, and a tool that prints what the database holds. One page, Enrolment, belongs to Word Detection: the web service only passes its requests on.
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

**Review Decision**:
A person's answer, after watching the Clip, to who caused a Press: the cat, the human, or nobody (the Press is discarded as not real). It overrides the automatic Presser in the study's figures, never erases it, and can be withdrawn. Any Press can be given one, not only an Ambiguous Press.
_Avoid_: Override, correction, label

**Exchange**:
A run of Presses with no long quiet gap between them, whoever pressed. It can hold Utterances by the cat and by the human, one after the other. The Exchange is what gets recorded; its Utterances follow from who is counted as the Presser of each Press.
_Avoid_: Session, burst, conversation

**Utterance**:
An ordered sequence of Presses by one Presser inside an Exchange, treated as one meaningful unit for the study (e.g. "want" + "outside"). It ends where the Exchange ends or where the Presser changes. An Ambiguous Press with no Review Decision counts as a change of Presser, so a Review Decision can join two Utterances into one or split one in two. A discarded Press belongs to no Utterance and ends none.
_Avoid_: Sequence, phrase, sentence

**Clip**:
The video of one Exchange, cut from Frigate's recording: it starts shortly before the first Press and ends when the Exchange closes. Every Exchange has exactly one Clip.
_Avoid_: Recording, footage, video segment

**Observation Window**:
A continuous stretch of time during which the whole pipeline was live, so any Press would have been captured and attributed. A pause between Utterances is only measured inside one Observation Window.
_Avoid_: Uptime, session, recording period

**Counted Day**:
A day with more than four hours inside Observation Windows. Figures given "per day" are plain counts averaged over Counted Days only; a day observed for less is shown but left out of the average.
_Avoid_: Valid day, full day

**Reply**:
An Utterance that is the next one said after an Utterance by the other Presser, starting within five minutes of it.
_Avoid_: Response, answer

**Connect Board**:
FluentPet's network-connected board variant with its own API for press signals. Integration deferred to a future phase — board not yet owned, capabilities unconfirmed.
_Avoid_: Smart board
