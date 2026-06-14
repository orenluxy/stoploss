# Graph Report - STOPLOSS  (2026-06-10)

## Corpus Check
- 11 files · ~9,329 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 133 nodes · 209 edges · 11 communities
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 6 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a5b04ea7`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]

## God Nodes (most connected - your core abstractions)
1. `sl()` - 22 edges
2. `STOPLOSS — Stop-Loss for Your Coding Agent` - 17 edges
3. `run()` - 16 edges
4. `init()` - 13 edges
5. `write_auditor()` - 13 edges
6. `run_audit()` - 13 edges
7. `add()` - 12 edges
8. `stoploss — a stop-loss for your fix loop` - 7 edges
9. `_make_clean_audit()` - 6 edges
10. `window_sums()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `test_counts()` --calls--> `window_sums()`  [INFERRED]
  bench/tasks/py-window-bug/tests/test_window.py → bench/tasks/py-window-bug/window.py
- `test_values()` --calls--> `window_sums()`  [INFERRED]
  bench/tasks/py-window-bug/tests/test_window.py → bench/tasks/py-window-bug/window.py
- `test_full_window()` --calls--> `window_sums()`  [INFERRED]
  bench/tasks/py-window-bug/tests/test_window.py → bench/tasks/py-window-bug/window.py
- `test_mean_basic()` --calls--> `mean()`  [INFERRED]
  bench/tasks/py-mean-bug/tests/test_stats.py → bench/tasks/py-mean-bug/stats.py
- `test_mean_single()` --calls--> `mean()`  [INFERRED]
  bench/tasks/py-mean-bug/tests/test_stats.py → bench/tasks/py-mean-bug/stats.py

## Communities (11 total, 0 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.11
Nodes (31): load_sl(), _make_clean_audit(), Thin wrapper for tests that need a simple run(cmd) call., Write a fake auditor script that emits JSONL findings + optional sentinel., Init stoploss in tmp_path and return the loaded module., Run `stoploss audit` with the given auditors list in config., Basic: one deterministic finding lands as open with source audit:<name>., Re-running audit on same code → 0 new (dedup by fingerprint). (+23 more)

### Community 1 - "Community 1"
Cohesion: 0.17
Nodes (27): add(), init(), Policy tests for the stoploss engine. Run: python3 -m pytest tests/ -q, Independent audit finding (no caused_by) fails twice → benched (backlog), NO db., Regression (has caused_by) fails twice → HALT (original behavior)., Round 1, one open finding (no pending) → hook stop exits 2., Round 1, zero open/triage/pending → hook stop exits 0., One open finding → audit --check exits 2. (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (24): Auditor Scripts (project-defined), Benchmark, code:block1 (without stoploss:), code:json ({), code:bash (stoploss triage F-5 --verdict REAL   # enters the fix loop a), code:block12 (stoploss init                     create .stoploss/ state, a), code:json ({), code:bash (python -m pytest tests -q) (+16 more)

### Community 3 - "Community 3"
Cohesion: 0.36
Nodes (6): mean(), Tiny stats helpers (contains seeded bugs for the benchmark)., variance(), test_mean_basic(), test_mean_single(), test_variance_constant()

### Community 4 - "Community 4"
Cohesion: 0.25
Nodes (8): code:bash (# Copy skill to Claude Code's global skills directory), code:powershell (Copy-Item -Recurse skills\stoploss\ "$env:USERPROFILE\.claud), code:json ({), code:block5 (/plugin install stoploss), Installation, Option A: Copy skill (recommended, no plugin system needed), Option B: Plugin install (if supported by your Claude Code version), Prerequisites

### Community 5 - "Community 5"
Cohesion: 0.25
Nodes (7): Audit Phase (Deterministic), Context hygiene, stoploss — a stop-loss for your fix loop, The audit pass (`/stoploss` on a fresh project), The fix loop, When the user says "check again", Why you cannot declare success

### Community 6 - "Community 6"
Cohesion: 0.38
Nodes (5): Sums of every contiguous window of size k., window_sums(), test_counts(), test_full_window(), test_values()

### Community 7 - "Community 7"
Cohesion: 0.33
Nodes (5): Benchmark harness, Honest limitations, Publishable run, Quick smoke (no agent, free), Real run

### Community 8 - "Community 8"
Cohesion: 0.6
Nodes (4): deep_get_usage(), main(), Recursively harvest token usage fields from arbitrary runner JSON., run_one()

### Community 9 - "Community 9"
Cohesion: 0.4
Nodes (5): code:bash (# 1. Audit pass — register findings with failing verify comm), code:bash (# Run all configured auditors (diff-scoped to changed files)), The classic fix loop, The deterministic audit (pre-push), Workflow

## Knowledge Gaps
- **57 isolated node(s):** `Recursively harvest token usage fields from arbitrary runner JSON.`, `Tiny stats helpers (contains seeded bugs for the benchmark).`, `Sums of every contiguous window of size k.`, `Policy tests for the stoploss engine. Run: python3 -m pytest tests/ -q`, `Thin wrapper for tests that need a simple run(cmd) call.` (+52 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `STOPLOSS — Stop-Loss for Your Coding Agent` connect `Community 2` to `Community 9`, `Community 4`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `Installation` connect `Community 4` to `Community 2`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `sl()` connect `Community 1` to `Community 0`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **What connects `Recursively harvest token usage fields from arbitrary runner JSON.`, `Tiny stats helpers (contains seeded bugs for the benchmark).`, `Sums of every contiguous window of size k.` to the rest of the system?**
  _57 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.08 - nodes in this community are weakly interconnected._