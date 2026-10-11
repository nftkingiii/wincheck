# Wincheck

Wincheck is an agent that takes a Windows-specific bug report for a Python project, reproduces it on Windows, fixes it, and checks the fix. It won't change any code until it has a test that fails.

## How it works

The model drives each phase with tools. The harness controls when it moves to the next phase:

| Phase | What the model can do | Gate to the next phase |
|---|---|---|
| **read** | read files, list dirs, search | calls `start_reproduction` with a plan |
| **reproduce** | write **test files only**, run commands and tests | harness runs the submitted tests itself and every one must **fail** |
| **fix** | write **non-test files only** (tests are frozen) | harness runs the reproduction (must pass) and the whole test files it lives in (nothing that passed before may fail) |

If the bug doesn't reproduce, the agent calls `give_up` and makes no patch. If any test file changes during the fix phase, the harness restores it and rejects that attempt.

- Model: `claude-opus-5-5` through the Anthropic Python SDK, with a hand-written tool-use loop, adaptive thinking and streaming.
- Tracing: every run is a neatlogs `WORKFLOW` span. Each phase is an `AGENT` span, and each tool call and harness check is a `TOOL` span. The Anthropic calls are instrumented too.
- Secrets: API keys are removed from the environment of the project under test, so the model's commands can't read them.

## Evals

Each eval case is a real Windows bug that was fixed upstream. It is replayed from the commit before the fix (`<fix>^`). The agent sees only the issue text and that checkout. Two upstream fixes close no issue (`tox-str-convert`, `build-env`), so their issue text is a short symptom-only report in `wincheck/issues/`, and `score.json` records `issue_source: written`. Scoring uses the maintainers' own test from the fix commit: the target tests must fail before the agent runs and pass after it, and no other test in those files may start failing.

```
python -m wincheck cases
python -m wincheck eval click-3277 --baseline-only   # is the case valid on this machine? (no model calls)
python -m wincheck eval click-3277                   # run and score the agent
python -m wincheck run --repo PATH --issue-file ISSUE.md --python PATH\to\venv\python.exe
```

Each run writes `runs/<case>/<time>/` with `issue.md`, `baseline.json`, `transcript.jsonl`, `fix.patch`, `result.json` and `score.json`.

## Results

Latest agent run for each case on `windows-latest`. Every run, with links to its Actions log, is in [docs/evidence.md](docs/evidence.md).

| Case | Held out | Result |
|---|---|---|
| click-3277 | no | passed |
| tox-3222 | no | failed: 1 of 6 targets (kept an escape rule upstream changed) |
| click-tempfile-pager | yes | passed |
| pytest-pathlib | yes | passed (66 s, 9 turns) |
| build-env | yes | passed (347 s) |
| tox-str-convert | yes | failed: 18 of 20 targets, 2 regressions |

4 of 6 cases pass, including 3 of the 4 held-out ones.

## Partner tools

- **neatlogs**: every run is one trace. The run is a workflow span, each phase an agent span, and each tool call and harness check a tool span. The Anthropic calls are instrumented too. Runs are listed in [docs/evidence.md](docs/evidence.md).
- **Entire**: commits carry `Entire-Checkpoint` trailers. The first public checkpoint is [`01M4MT8VXPQRMM5SF9FWS0H8XE`](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a). Cloud sessions can't push `refs/entire/*`, so [`entire-import.yml`](.github/workflows/entire-import.yml) publishes checkpoints from a git bundle.
- **cfo.ai**: a 12-month plan built from measured run costs. $49 per fix and a $199/month team plan both clear a 70% margin, and 23 paying repos cover founder pay. See the [summary PDF](docs/business/wincheck-financial-plan.pdf) and the [workbook](docs/business/wincheck-12-month-plan.xlsx).

## Windows runner

The runs happen on GitHub Actions `windows-latest` (`.github/workflows/wincheck.yml`). The workflow can only be started by hand. Its API keys come from repository secrets (`ANTHROPIC_API_KEY`, `NEATLOGS_API_KEY`), and the run directory is uploaded as an artifact.
