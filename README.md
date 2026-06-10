# STOPLOSS — Stop-Loss for Your Coding Agent

> **Bounded, convergence-enforced fix loops for Claude Code.**  
> Policy lives in code. The model can't lie its way past a failing test.

---

## The Problem

You ask Claude Code to fix a bug. It fixes it. You ask it to review again. It finds something new. You ask again. It finds something else. Each round burns 50–200K tokens, and the loop never converges — because **nothing stops it**.

The root cause: Claude's "I verified it works" is a claim, not evidence. Without a hard oracle, the fix loop is open-ended by design.

```
without stoploss:
  you: "fix the failing test"
  claude: *edits code* "done, all good ✓"
  you: "check again"
  claude: *re-audits* "found 2 more issues"
  you: "check again"
  claude: *re-audits* "found 1 more issue"
  ... (loop continues until you stop it)

with stoploss:
  you: "fix F-1"
  claude: stoploss close F-1   ← verify command RUNS; refuses if it fails
  loop only continues if the test actually passes
  "check again" → injects ledger state, not a free re-audit
```

---

## How It Works

STOPLOSS adds a **findings ledger** with **code-enforced policy** between Claude and its fix loop:

1. **Audit pass:** Claude registers findings with a verify command per finding.
2. **Fix rounds:** Claude fixes findings by ID. Closing requires the verify to pass — the model cannot declare success.
3. **Deterministic audit:** Configured auditor scripts emit JSONL findings. Same code → same findings. The endless loop is structurally impossible.
4. **Push gate:** `stoploss audit --check` exits 0 only when truly clean.

All policy is enforced by code, not prompts. The model can't reason its way around a failing test.

---

## Policy Rules (enforced, not suggested)

| Rule | What it prevents |
|---|---|
| **Close = verify runs** | Model cannot declare success without the verify command passing |
| **Two-strike bench** | Two failed closes → finding benched (independent) or loop halted (regression) |
| **Monotonic convergence** | Open findings must shrink each round, or the loop halts |
| **Review noise filter** | New findings after audit round without `caused_by` → backlog (not open) |
| **Regression chain cap** | Fix-of-fix-of-fix chains capped at depth 2 |
| **Severity floor** | After round 3, only critical/major findings enter the loop |
| **Max rounds** | Hard cap; only a human can resume |
| **No self-restart** | Halted loops require `stoploss resume` — the model cannot call it |
| **Session block** | `Stop` hook blocks session end with open or pending findings |
| **Prompt injection** | "check again" / "בדוק שוב" → ledger state injected instead of re-audit |

---

## Token Savings

STOPLOSS ships with a reproducible benchmark harness (`bench/`). Rather than citing a fixed number, you can measure it on your own codebase.

The mechanism is structural: the verify-fix loop terminates when the test passes, not when Claude decides it's done. Open-ended re-audits ("check again" × 5) are blocked by the `UserPromptSubmit` hook — each one would have burned 50–200K tokens depending on context size.

Run `stoploss report` after a session to see tokens-per-closed-finding for your actual workflow.

---

## Installation

### Prerequisites
- Python 3.8+ (no external dependencies — stdlib only)
- Claude Code CLI

### Option A: Copy skill (recommended, no plugin system needed)

```bash
# Copy skill to Claude Code's global skills directory
cp -r skills/stoploss/ ~/.claude/skills/stoploss/

# Put the CLI on your PATH
cp bin/stoploss /usr/local/bin/stoploss
chmod +x /usr/local/bin/stoploss
```

**Windows (PowerShell):**
```powershell
Copy-Item -Recurse skills\stoploss\ "$env:USERPROFILE\.claude\skills\stoploss\"
Copy-Item bin\stoploss "$env:USERPROFILE\.claude\bin\stoploss"
```

Then wire the three hooks into `~/.claude/settings.json` (or your project's `.claude/settings.json`):

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "python /path/to/stoploss hook prompt"}]
    }],
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{"type": "command", "command": "python /path/to/stoploss hook posttool"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "python /path/to/stoploss hook stop"}]
    }]
  }
}
```

> **Windows note:** Use `python` (not `python3`) and forward slashes in the path.

### Option B: Plugin install (if supported by your Claude Code version)

```
/plugin install stoploss
```

---

## Per-Project Setup

In any project you want to track:

```bash
stoploss init
```

This creates `.stoploss/` with a ledger and config. Auto-detects your test runner (pytest, jest, etc.). Add `.stoploss/` to `.gitignore` — it's developer-local state.

---

## Workflow

### The classic fix loop

```bash
# 1. Audit pass — register findings with failing verify commands
stoploss add \
  --title "null pointer in payment handler" \
  --claim "line 42 dereferences before nil-check" \
  --location "src/payment.py:42" \
  --severity critical \
  --verify "pytest tests/test_payment.py::test_nil_input"

stoploss status
# Round 0 | open 1 | closed 0 | backlog 0 | pending []

# 2. Fix rounds
stoploss round          # advances to round 1; halts if loop isn't converging
stoploss start F-1      # mark as in-progress
# ... edit code ...
stoploss close F-1      # runs verify command; refuses if it fails
# F-1 closed (verified). Open: 0, pending: []

# 3. Someone types "check again" → hook injects:
# [stoploss] Round 1, open: none, pending: []. Do NOT free-audit.
```

### The deterministic audit (pre-push)

```bash
# Run all configured auditors (diff-scoped to changed files)
stoploss audit
# audit: 3 new, 0 reopened. open=3, triage=0.

# Fix findings by id (same fix loop as above)
# ...

# Re-run — same code → 0 new findings (dedup by fingerprint)
stoploss audit
# audit: 0 new, 0 reopened.   ← convergence proof

# Green push signal
stoploss audit --check
# READY TO PUSH: audit clean — 0 open / 0 triage / 0 benched, no new findings.
```

---

## Auditor Scripts (project-defined)

STOPLOSS is generic. Projects supply their own auditor scripts that emit JSONL findings:

```python
# example auditor (any language that prints to stdout)
import json, os

changed = os.environ.get("STOPLOSS_CHANGED_FILES", "").splitlines()
for f in changed:
    if "child_process" in open(f).read():
        print(json.dumps({
            "key": f"no-child-process:{f}",
            "title": f"child_process used in {f}",
            "claim": "spawn/exec found — forbidden in K8s worker process",
            "location": f,
            "severity": "critical",
            "verify": f'grep -c "child_process" {f} | grep -q "^0$"',
        }))

print(json.dumps({"audit_complete": True}))
```

Configure auditors in `.stoploss/config.json`:

```json
{
  "diff_base": "origin/main",
  "max_audit_findings": 50,
  "auditors": [
    {"name": "syntax",     "cmd": "node scripts/audit/syntax.mjs",     "type": "deterministic"},
    {"name": "tests",      "cmd": "node scripts/audit/tests.mjs",      "type": "deterministic"},
    {"name": "candidates", "cmd": "node scripts/audit/candidates.mjs", "type": "triage"}
  ]
}
```

**Auditor contract:**
- Print one JSON finding per line (required: `title`, `claim`, `location`, `severity`, `verify`; optional: `key`, `evidence`)
- Print `{"audit_complete": true}` as the very last line — omitting it causes STOPLOSS to treat the auditor as crashed
- Read `STOPLOSS_CHANGED_FILES` env var (newline-joined repo-relative paths) to diff-scope your checks
- `type: deterministic` → findings land as `open`; `type: triage` → findings land as `triage` (require human verdict via `stoploss triage`)
- Re-running on unchanged code must produce zero new findings (use the `key` field for stable fingerprints)

---

## Triage Findings

For semantic rules that require judgment:

```bash
stoploss triage F-5 --verdict REAL   # enters the fix loop as open
stoploss triage F-5 --verdict NOISE  # dismissed forever — future audits skip it
```

Use the `stoploss-verifier` subagent (`agents/stoploss-verifier.md`) to get automated PASS/FAIL verdicts on manual findings.

---

## Full Command Reference

```
stoploss init                     create .stoploss/ state, auto-detect gates
stoploss add ...                  register a finding (see --help for flags)
stoploss start F-1 F-2            mark findings as in-progress
stoploss close F-1                close a finding — RUNS its verify command
stoploss fail F-1                 record a manual failure (two strikes → bench)
stoploss round                    advance one round; halts on non-convergence
stoploss resume --rounds N        HUMAN-ONLY: clear halt, grant N more rounds
stoploss audit                    run all configured auditors, ingest findings
stoploss audit --check            push gate: exits 0 only when clean
stoploss triage F-1 --verdict ... REAL (→ open) or NOISE (→ dismissed forever)
stoploss gate [--quick]           run gates manually (quick = lint only)
stoploss verify F-1               re-run a finding's verify command
stoploss status                   print round, counts, open/triage findings
stoploss list                     list all findings
stoploss pack                     dump ledger + rules as JSON (for context injection)
stoploss report                   token accounting from session transcripts
```

Exit codes: `0` = OK | `2` = policy halt / gate failure / session blocked.

---

## Configuration Reference

`.stoploss/config.json` (auto-generated by `stoploss init`, edit as needed):

```json
{
  "gates_quick": ["ruff check .", "npx eslint src/"],
  "gates_full":  ["python -m pytest -x -q", "npm test"],
  "diff_base":   "origin/main",
  "max_audit_findings": 50,
  "max_rounds": 5,
  "severity_floor_round": 3,
  "max_chain": 2,
  "auditors": [],
  "prompt_patterns": [
    "\\bcheck( it)? again\\b", "\\bre-?check\\b", "\\breview\\b", "\\baudit\\b",
    "\\bfind (more )?bugs\\b"
  ]
}
```

Hebrew prompt patterns (`"בדוק"`, `"אודיט"` etc.) are included in `DEFAULT_PATTERNS` in the CLI and applied when no custom patterns are configured.

---

## Hooks

Three hooks are wired at install time:

| Hook | Trigger | Effect |
|---|---|---|
| `UserPromptSubmit` | "check again", "audit", "review" etc. | Injects ledger state; blocks free re-audit |
| `PostToolUse` (Edit/Write) | After any file edit | Runs quick gates (lint/typecheck) |
| `Stop` | Session end | Blocks if open findings, triage, or pending verifications exist |

All hooks **silently no-op when no `.stoploss/` directory is found** — safe to install globally across all projects.

---

## Tests

```bash
python -m pytest tests -q
# 29 passed
```

All policy rules are covered. Tests use temporary directories with fake auditor scripts — no external dependencies, no network.

---

## Benchmark

```bash
cd bench
python run_bench.py
```

Runs two sample tasks (mean-calculation bug, sliding-window bug) with and without STOPLOSS and reports tokens-per-closed-finding. Add your own tasks to `bench/tasks/` to measure on your codebase.

---

## Design Principles

**Policy in code, not prompts.** A prompt saying "verify your work" can be ignored or rationalized. `stoploss close` runs the verify command and refuses on failure — no argument.

**The model cannot declare done.** The finding's own verify command is the oracle. `stoploss close F-1` runs `pytest test_payment.py::test_nil_input` and exits 2 if it fails — regardless of what Claude thinks.

**Halts are human decisions.** The model can detect a stuck loop but cannot restart it. Only `stoploss resume --rounds N` clears a halt, and it must be run by a human in the terminal.

**No external dependencies.** Pure Python 3 stdlib. Works offline. Single file (`bin/stoploss`, ~700 lines). No pip install.

**Generic core, project-specific auditors.** STOPLOSS knows nothing about your stack. You supply auditor scripts that understand your rules. The core stays stable; your checks evolve with your codebase.

**Convergence is structural, not behavioral.** The same auditor run on unchanged code produces the same findings (dedup by fingerprint). There is no code path that generates infinitely many findings from a static codebase. The endless loop is impossible by construction.

---

## License

MIT — Copyright 2026 Oren Luxy
