# Word Detection

Runs on the local PC. Custom audio pipeline that consumes the mic feed and identifies which Word was spoken, using fingerprint matching against known reference clips rather than general ML classification (each FluentPet button plays the exact same pre-recorded clip every time).

## Architecture

A Python service that runs as a container in the Frigate stack. It listens to the stream, matches it against the Reference Clips, and publishes each Word it hears to the MQTT broker.

- **word_detection/**: the service, plus the Enrolment tool and a tool for checking matches in a recording.
- **references/**: the Reference Clips, one folder per Word.
- **Dockerfile**, **requirements.txt**: how the container is built.

## Language

**Word**:
The semantic unit announced when a button is pressed; identified by matching the mic feed against a known reference clip.
_Avoid_: Sound, utterance, phrase

**Reference Clip**:
A recording of one button's Word, captured through the wall-mounted mic in its mounted position, that the mic feed is matched against. A Word may have several.
_Avoid_: Sample, template, fingerprint

**Enrolment**:
Pressing a button on purpose to capture its Reference Clips. Repeated whenever a button is re-recorded or the mic is moved.
_Avoid_: Training, calibration

**Uncertain Match**:
A sound that resembles a Reference Clip without matching it confidently. It is still reported, with its best-guess Word, so that no Press is silently lost. Distinct from an Ambiguous Press, which is about who pressed, not which Word.
_Avoid_: Near-miss, weak match, false positive
