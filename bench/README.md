# Benchmark harness

Measures **tokens per solved task** across arms (vanilla vs stoploss) on
seeded-bug tasks with deterministic test oracles.

## Quick smoke (no agent, free)
    python3 bench/run_bench.py --dry

## Real run
    python3 bench/run_bench.py --runner 'claude -p {prompt_file} --output-format json'

Verify the exact headless flags against current Claude Code docs first; pass
your verified command via --runner. Real runs cost real tokens.

## Publishable run
The two bundled tasks are smoke tests, not evidence. For credible numbers:

1. Add 20-30 tasks. Best source: SWE-bench Lite instances (each ships a
   fail-to-pass test = a real oracle). Each task dir needs `task.json`
   ({"name","description","test_cmd"}) plus the buggy source tree.
2. Run all arms with the SAME model and the SAME runner string.
3. Publish: results.csv, the raw workdirs, your exact runner string, model id,
   and date. If readers cannot reproduce it, it does not count.

## Honest limitations
- Oracle tasks favor any structured loop; they measure the fix loop, not
  open-ended "review my code" sessions. State this when publishing.
- Token parsing is best-effort across Claude Code output formats; a failed
  parse records 0 with a warning, never a fabricated number.
