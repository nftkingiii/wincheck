# Evidence

What each claim rests on. Every entry links to something a reviewer can open.

## neatlogs (agent tracing)
| Date | What | Evidence |
|---|---|---|
| 2026-10-11 | Agent runs export traces (`neatlogs export on` in the log) | [run 38112274222](https://github.com/nftkingiii/wincheck/actions/runs/38112274222) |
| 2026-10-11 | Each eval run is one trace (wincheck_eval → prepare_project, baseline, wincheck_run with read/reproduce/fix phases, score) | [run 38120573968](https://github.com/nftkingiii/wincheck/actions/runs/38120573968) |

## Entire (checkpoints, graph)
| Date | What | Evidence |
|---|---|---|
| 2026-10-11 | First public checkpoint (01M4MT8VXPQRMM5SF9FWS0H8XE): README results section | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4MVMWV80NVTQG1FRX2K6YCB: README Partner tools section | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4MW81P89C81Z8V9TPERQMZH: one neatlogs trace per eval run | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4NY9M8KY269DEEQSYES5J4Q: before-and-after and failed-action evidence | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4PDB1Y3B7EDXGJX5NYMC9HY: MCP server | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4PDBKFPYB54GN93ZE6MKFWC: Try it yourself section | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4PEB0J3JVHJKH3M5MXKFBT9: harness test suite | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |
| 2026-10-11 | Checkpoint 01M4PEBK08DQQS2AVDA33NEGC5: tests in CI on Windows and Linux | [session](https://entire.io/gh/nftkingiii/wincheck/session/06c56b38-4221-5994-b5c1-a8a55c86ae0a) |

## cfo.ai (business plan)
| Date | What | Evidence |
|---|---|---|
| 2026-10-11 | 12-month plan (Oct 2026 to Sep 2027) built by cfo.ai's Ari from measured run costs ($1.50 per successful fix, cautious) | [summary PDF](business/wincheck-financial-plan.pdf) |
| 2026-10-11 | Prices clear 70% margin: $49 per fix (96.9%), $199/month team plan (92.5%), $29 extra fix (94.8%) | [summary PDF](business/wincheck-financial-plan.pdf), page 1 |
| 2026-10-11 | Break-even: 1 team covers running costs, 23 cover founder pay, 56 cover founder pay plus a contract engineer | [summary PDF](business/wincheck-financial-plan.pdf), page 2 |
| 2026-10-11 | September 2027 base case: 30 paying repos, $5,970/month revenue, $4,938 peak funding need; Downside needs $17,500 | [summary PDF](business/wincheck-financial-plan.pdf), pages 1 and 3 |
| 2026-10-11 | Full live model export: assumptions, monthly forecast, scenario comparison, early-hire stress tests | [workbook](business/wincheck-12-month-plan.xlsx) |

## Agent results
| Date | Run | Result |
|---|---|---|
| 2026-10-11 | click-3277 baseline (Windows) | [valid: target test fails before the fix](https://github.com/nftkingiii/wincheck/actions/runs/38109826173) |
| 2026-10-11 | click-3277 agent, before PR #3 | [failed: fixed the symptom, but bypassed `click.echo`](https://github.com/nftkingiii/wincheck/actions/runs/38110138668) |
| 2026-10-11 | tox-3222 agent, before PR #3 | [failed: 2/6 targets](https://github.com/nftkingiii/wincheck/actions/runs/38110804249) |
| 2026-10-11 | click-3277 agent, after PR #3 | [**passed**](https://github.com/nftkingiii/wincheck/actions/runs/38112253078) |
| 2026-10-11 | tox-3222 agent, after PR #3 | [failed: 1/6 targets (kept an escape rule upstream changed)](https://github.com/nftkingiii/wincheck/actions/runs/38112263577) |
| 2026-10-11 | click-tempfile-pager agent (held out), after PR #3 | [**passed**](https://github.com/nftkingiii/wincheck/actions/runs/38112274222) |
| 2026-10-11 | pytest-pathlib agent (held out), first try | [not run: the harness counted an inner pytest's temp-dir test as a second target, so the case was rejected before the agent started (no model calls)](https://github.com/nftkingiii/wincheck/actions/runs/38117084071) |
| 2026-10-11 | pytest-pathlib agent (held out), after the target fix in PR #8 | [**passed** in 66 s, 9 turns](https://github.com/nftkingiii/wincheck/actions/runs/38117351420) |
| 2026-10-11 | tox-3222 baseline (Windows), after the target fix in PR #8 | [valid](https://github.com/nftkingiii/wincheck/actions/runs/38117352662) |
| 2026-10-11 | tox-str-convert agent (held out, written bug report) | [failed: 18/20 targets (single-quoted UNC paths still collapse) and 2 regressions (UNC paths quoted mid-argument)](https://github.com/nftkingiii/wincheck/actions/runs/38117085629) |
| 2026-10-11 | build-env agent (held out, written bug report) | [**passed**, agent time 347 s](https://github.com/nftkingiii/wincheck/actions/runs/38117086919) |
| 2026-10-11 | pytest-pathlib agent (held out), re-run with one trace per run | [**passed**](https://github.com/nftkingiii/wincheck/actions/runs/38120573968) |

## Before and after
Two click-3277 agent runs on the same bug. Between them, PR #3 steered the agent toward root-cause fixes that go through existing code paths.

| | Before PR #3 | After PR #3 |
|---|---|---|
| Run | [38110138668](https://github.com/nftkingiii/wincheck/actions/runs/38110138668) | [38112253078](https://github.com/nftkingiii/wincheck/actions/runs/38112253078) |
| Result | failed | **passed** |
| What the agent did | fixed the symptom with a new `_echo_lf` helper that bypassed `click.echo` | fixed it inside the existing code path: the output, trailing newline included, is encoded with the stream's encoding (`get_best_encoding(_default_text_stdout())`) and written as bytes through the existing `echo()`, which skips Windows newline translation. No new helper, and `click.echo` isn't bypassed |
| Turns | 14 | 17 |
| Agent time | 88.3 s | 81.1 s |
| Output tokens | 5,391 | 6,278 |

neatlogs tracing, before and after PR #13:

| | Before PR #13 | After PR #13 |
|---|---|---|
| Traces per eval run | 4 separate traces (prepare_project, baseline, wincheck_run, score) | 1 `wincheck_eval` trace with everything nested inside it |
| Run | [38117085629](https://github.com/nftkingiii/wincheck/actions/runs/38117085629) (tox-str-convert) | [38120573968](https://github.com/nftkingiii/wincheck/actions/runs/38120573968) |

## A failed action and what the agent did next
From the tox-str-convert run ([38117085629](https://github.com/nftkingiii/wincheck/actions/runs/38117085629); the run's artifact has `transcript.jsonl`):

1. The agent ran `pytest tests/config`. Collection crashed with `ModuleNotFoundError: No module named 'argcomplete'`.
2. On the next turn it re-ran with `--ignore=tests/config/cli/test_argcomplete.py`.
3. That run showed failures in `test_cli_ini.py`. The agent ran `git stash` on its change and re-ran those tests, to check whether the failures were there before its fix.

A failure at the harness level: the first pytest-pathlib run ([38117084071](https://github.com/nftkingiii/wincheck/actions/runs/38117084071)) was rejected by the baseline gate before any model call, because the harness counted an inner pytest's temp-dir test as a second target. PR #8 fixed the target count, and the next run [passed](https://github.com/nftkingiii/wincheck/actions/runs/38117351420).

## Harness tests
27 tests in `tests/`, with no network and no API key. CI runs them on windows-latest and ubuntu-latest ([run 38177162062](https://github.com/nftkingiii/wincheck/actions/runs/38177162062)).

They cover:
- phase gates: nothing is written while reading, only test files in reproduce, only non-test files in fix, and no paths outside the project
- secret scrubbing: API keys and tokens never reach the project under test
- pytest parsing: per-test outcomes from the summary, including Windows backslash ids
- the PR #8 target count: an inner pytest's temp-dir tests are not counted
- MCP output parsing: the CLI's JSON is read even with the neatlogs log line after it
- 6 scripted end-to-end runs of the real agent loop: fixed, fix before reproduction (refused), passing reproduction (rejected), give up (no patch), a fix that doesn't work (unverified), and a test rewritten through the shell in the fix phase (restored)

Gate check: disabling each gate makes at least one test fail.

Known limitation: a parametrized test id that contains " - " is cut off by `parse_summary`.
