# Documentation claim auditor

Version 0.1.0. An offline, deterministic, standard-library-only CLI for Python
3.9 or later. It compares documentation about the checked capability with
static Python call patterns. No network, LLM, telemetry, or output-file writes.

## Usage

```sh
python3 -m pip install .
emotion-recognition-claim-audit audit .
python3 -m emotion_recognition_claim_audit audit . --json --verbose
emotion-recognition-claim-audit audit . --ignore tests/ --ignore vendor/ --fail-on medium
emotion-recognition-claim-audit --version
```

The repository defaults to the current directory. Repeat the ignore option for
relative path prefixes. JSON output is an array with verdict and message fields
on every finding. Verbose decisions go to stderr. Exit 0 means no finding meets
the threshold; exit 2 means findings meet it; exit 1 means a usage or IO error.
The default threshold is high; medium also fails test-only claims.

## Scope and rules

The scanner reads the root README and Markdown below docs, plus Markdown test
fixtures under tests directories. Triple-backtick fenced blocks are excluded;
inline code counts as prose. Python modules are searched recursively, excluding
Git metadata, bytecode caches, and virtual environments. Each evidence route
must be complete within a single module. Imports and local function/class
shadowing are resolved statically. Denial spans are removed before claims.
Matching is case-insensitive exact substring matching, without stemming or
hyphen normalization. Longest-first matching with span blanking makes each
occurrence match once under its longest phrase.

```text
documented-emotion-recognition-claim-false (HIGH; test-only MEDIUM)
documented-no-emotion-recognition-claim-false (HIGH)
```

A supported claim passes. A denial without contradictory source evidence passes,
including a repository without Python sources. No phrases also passes.

## Differentiation

```text
sentiment-claim-audit
mood-recognition-claim-audit
face-claim-audit
speech-recognition-claim-audit
```

The first checks text polarity, while this tool checks discrete-affect
classification. The second checks a music track's mood, while this tool checks
a person's emotion. The third checks finding or identifying faces, while this
tool checks classifying the emotion on them. The fourth checks transcription,
while this tool checks the speaker's expressed affect.

## Evidence and limitations

This is static pattern matching, not semantic judgement. Exact phrases are
required; restatements are missed. Sentiment polarity deliberately does not
count: a positive/negative score is not a discrete emotion. Facial landmarks,
face detectors, music mood classifiers, generic predictors, subprocess commands,
imports, references, comments, and strings alone do not establish the feature.

An emotion-model pipeline call counts as evidence, although it does not prove
the classified label is correct. The task must be text classification and the
literal model name must contain the required keyword. The following call forms
also count when imported and paired as required:

```text
transformers.pipeline("text-classification", model="example-emotion")
DeepFace.analyze(image, actions=["emotion"])
FER().detect_emotions(image)
HumeClient().expression_measurement.batch.start_inference_job(...)
x.detect_emotion(...)
```

The facial analyzer requires the stated action. Its call does not prove the
classified label is correct. A detector construction paired with a detect call
shows feature use, not label correctness. Client constructions require a call
through the expression-measurement attribute. Generic method names on unrelated
objects count too, because their spelling is shared. Bare generic calls require
a from-import; locally defined functions and classes shadow imported routes.

These exact phrases can also describe a person recognizing or detecting someone
else's emotions, and the final phrase can describe a human skill instead of
software behaviour. The scanner cannot distinguish those meanings:

```text
recognize emotions
recognizes emotions
detect emotions
detect emotion
emotion recognition
she recognizes emotions better than words
```

## Development

```sh
python3 -m unittest discover
python3 -m build
```

Both source and wheel distributions use setuptools. The source distribution
includes the discoverable test suite. MIT licensed.
