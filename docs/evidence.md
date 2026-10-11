# Evidence

What each claim rests on. Every entry links to something a reviewer can open.

## neatlogs (agent tracing)
| Date | What | Evidence |
|---|---|---|
| 2026-10-11 | Agent runs export traces (`neatlogs export on` in the log) | [run 38112274222](https://github.com/nftkingiii/wincheck/actions/runs/38112274222) |

## Entire (checkpoints, graph)
| Date | What | Evidence |
|---|---|---|

## cfo.ai (business plan)
| Date | What | Evidence |
|---|---|---|

## Agent results
| Date | Run | Result |
|---|---|---|
| 2026-10-11 | click-3277 baseline (Windows) | [valid: target test fails before the fix](https://github.com/nftkingiii/wincheck/actions/runs/38109826173) |
| 2026-10-11 | click-3277 agent, before PR #3 | [failed: fixed the symptom, but bypassed `click.echo`](https://github.com/nftkingiii/wincheck/actions/runs/38110138668) |
| 2026-10-11 | tox-3222 agent, before PR #3 | [failed: 2/6 targets](https://github.com/nftkingiii/wincheck/actions/runs/38110804249) |
| 2026-10-11 | click-3277 agent, after PR #3 | [**passed**](https://github.com/nftkingiii/wincheck/actions/runs/38112253078) |
| 2026-10-11 | tox-3222 agent, after PR #3 | [failed: 1/6 targets (kept an escape rule upstream changed)](https://github.com/nftkingiii/wincheck/actions/runs/38112263577) |
| 2026-10-11 | click-tempfile-pager agent (held out), after PR #3 | [**passed**](https://github.com/nftkingiii/wincheck/actions/runs/38112274222) |
