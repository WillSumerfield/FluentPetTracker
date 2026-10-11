# Word Detection

Runs on the local PC. Custom audio pipeline that consumes the mic feed and identifies which Word was spoken, using fingerprint matching against known reference clips rather than general ML classification (each FluentPet button plays the exact same pre-recorded clip every time).

## Architecture

Empty — implementation begins in Phase 3 (see `temp/phased-plan.md`).

## Language

**Word**:
The semantic unit announced when a button is pressed; identified by matching the mic feed against a known reference clip.
_Avoid_: Sound, utterance, phrase
