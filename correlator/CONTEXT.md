# Correlator

Runs on the local PC. Custom app that joins Frigate's presence/zone events with Word Detection's Word events (by timestamp) into Press records, resolves Presser attribution, and owns the database that is the source of truth for the longitudinal study.

## Architecture

Empty — implementation begins in Phase 4 (see `temp/phased-plan.md`).

## Language

**FluentPet Board**:
The physical board with buttons mapped to Words, used by the pet.
_Avoid_: Device, panel

**Press**:
An instance of a button being activated, producing a Word.
_Avoid_: Click, activation, trigger

**Presser**:
The subject (human or pet) attributed as having caused a Press.
_Avoid_: User, actor

**Ambiguous Press**:
A Press whose Presser can't be confidently determined from Frigate's classification; flagged for manual review rather than guessed.
_Avoid_: Unknown press, unresolved press

**Utterance**:
An ordered sequence of Presses occurring within a short time window, treated as one meaningful unit for the study (e.g. "want" + "outside").
_Avoid_: Sequence, phrase, sentence

**Connect Board**:
FluentPet's network-connected board variant with its own API for press signals. Integration deferred to a future phase — board not yet owned, capabilities unconfirmed.
_Avoid_: Smart board
