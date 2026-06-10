---
name: stoploss
description: Bounded, convergence-enforced fix loop. Use whenever the user asks to review, audit, check, re-check, or find/fix bugs in a repository containing a .stoploss/ directory — or asks to set one up. Replaces open-ended re-auditing with a findings ledger whose policy is enforced by code.
---

# stoploss — a stop-loss for your fix loop

This project uses a findings ledger managed by the `stoploss` CLI
(`bin/stoploss` in this plugin; if `stoploss` is not on PATH, invoke it as
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/stoploss"`). The loop policy is enforced
by the CLI's exit codes, not by you. **Exit code 2 is law: stop, summarize,
end your turn.**

## Why you cannot declare success

`stoploss close F-3` runs the finding's own `verify` command and refuses to
close on failure. Your opinion that something is fixed is irrelevant — only
the verify command decides. Two failed verifications bench the finding and
HALT the loop. Only the human can `stoploss resume`.

## The audit pass (`/stoploss` on a fresh project)

1. If `.stoploss/` is missing, run `stoploss init` (it auto-detects gates).
2. Do ONE thorough review. For every real issue, register it:
   - **Best practice — test-first:** write a minimal FAILING test that proves
     the bug, commit it as the finding's verify command. Red now, green after
     the fix. This is what makes verification deterministic.
   - `stoploss add --json -` with
     `{"title","claim","location","severity","verify"}` on stdin.
     `verify` is a shell command (preferred) or `MANUAL: <how to check>`
     only when no command is possible.
3. Print `stoploss status` and STOP. The audit pass fixes nothing.

## The fix loop

For each batch the user names ("fix F-2 and F-5"):

1. `stoploss round` — if exit 2: report the HALT reason and stop.
2. `stoploss start F-2 F-5`
3. Fix F-2 only. Touch nothing unrelated.
4. `stoploss gate --quick` after edits (hooks also run this automatically).
5. `stoploss close F-2` — the CLI verifies. If it exits 2, read the failure,
   make ONE more attempt, close again. If it HALTs — stop.
6. MANUAL findings only: launch the `stoploss-verifier` subagent with the
   finding JSON + your diff. On PASS: `stoploss close F-2 --agent-verdict
   PASS`. On FAIL: `stoploss fail F-2`.
7. A fix that breaks something else: `stoploss add ... --caused-by F-2`.
   Anything you "noticed along the way" without a caused_by will be routed
   to backlog by the CLI — accept that silently. Never fix unregistered
   issues.
8. `stoploss status`, report, end turn.

## When the user says "check again"

Run `stoploss status`. Work the open ids. Do NOT re-read the codebase
hunting for new problems — that instinct is the exact failure mode this
system exists to kill.

## Context hygiene

On resume or in long sessions, seed yourself from `stoploss pack` plus
current file contents — never from old file versions in conversation
history.

## Audit Phase (Deterministic)

Before each push, run the deterministic audit instead of re-reading code:

1. `stoploss audit` — runs all configured auditors, ingests findings by fingerprint.
   Re-running on unchanged code returns 0 new (the endless-loop is impossible by design).

2. Work all open findings by id using the normal fix loop (round → start → fix → close).

3. For TRIAGE findings (from `type: triage` auditors, semantic candidates):
   Run the stoploss-verifier subagent on the candidate + diff. Then:
   - `stoploss triage <id> --verdict REAL` — enters the fix loop
   - `stoploss triage <id> --verdict NOISE` — dismissed forever (re-audits skip it)

4. `stoploss audit --check` — the push gate.
   Exits 0 ("READY TO PUSH") only when:
   - 0 open findings
   - 0 triage candidates awaiting verdict
   - 0 benched audit findings (fix approach failed twice)
   - this run ingested 0 new findings
   Exits 2 ("NOT READY") otherwise.

**Auditor contract (for project-side scripts):**
- Print one JSON finding per line: `{"title","claim","location","severity","verify","key"?,"evidence"?}`
- Print `{"audit_complete": true}` as the last line
- Read `STOPLOSS_CHANGED_FILES` env var (newline-joined changed paths) for diff-scoping
- type `deterministic` → findings land as open; type `triage` → findings land as triage
