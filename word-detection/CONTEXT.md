# Word Detection

Runs on the local PC. Custom audio pipeline that consumes the mic feed and identifies which Word was spoken, using fingerprint matching against known reference clips rather than general ML classification (each FluentPet button plays the exact same pre-recorded clip every time).

## Architecture

A Python service that runs as a container in the Frigate stack. It listens to the stream, matches it against the Reference Clips, and publishes each Word it hears to the MQTT broker. It also carries out Enrolment for the Enrolment page, which reaches it through the Correlator's web service, and starts using new Reference Clips without a restart.

- **word_detection/**: the service and its Enrolment, plus a command-line Enrolment tool and a tool for checking matches in a recording.
- **references/**: the Reference Clips, one folder per Word (not committed: they are made by Enrolment, for one mic in one place).
- **data/**: an Enrolment Recording waiting to be saved (not committed).
- **Dockerfile**, **requirements.txt**: how the container is built.

## Language

**Word**:
The semantic unit announced when a button is pressed; identified by matching the mic feed against a known reference clip.
_Avoid_: Sound, utterance, phrase

**Reference Clip**:
A recording of one button's Word, captured through the wall-mounted mic in its mounted position, that the mic feed is matched against. A Word may have several.
_Avoid_: Sample, template, fingerprint

**Enrolment**:
Pressing a button on purpose to capture its Reference Clips. Repeated whenever a button is re-recorded or the mic is moved. The Reference Clips captured for a Word replace the ones it had; Words not pressed keep theirs.
_Avoid_: Training, calibration

**Enrolment Recording**:
The stretch of the mic feed captured during Enrolment, usually of every button pressed in turn, from which Reference Clips are cut. Only one exists at a time. While it is being captured no Word is reported, so Enrolment never produces a Press.
_Avoid_: Calibration clip, upload, sample recording

**Span**:
A marked portion of an Enrolment Recording holding one button's sound, labelled with its Word. It becomes a Reference Clip when the Enrolment is saved.
_Avoid_: Selection, highlight, region, segment

**Uncertain Match**:
A sound that resembles a Reference Clip without matching it confidently. It is still reported, with its best-guess Word, so that no Press is silently lost. Distinct from an Ambiguous Press, which is about who pressed, not which Word.
_Avoid_: Near-miss, weak match, false positive
