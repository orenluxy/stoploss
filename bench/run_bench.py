#!/usr/bin/env python3
"""
stoploss benchmark harness - tokens-per-solved-task, reproducibly.

Arms:
  vanilla   - plain "fix until tests pass" prompt
  stoploss  - the ledger-driven flow

For each (task x arm): copy the task to a fresh workdir, run the agent once
headlessly, then run the task's test_cmd as the oracle. Token usage is parsed
from the runner's JSON output (best effort - field names may vary by Claude
Code version; unknown formats degrade to usage=0 with a warning, never to
fake numbers).

Usage:
  python3 bench/run_bench.py                       # all tasks, both arms
  python3 bench/run_bench.py --tasks py-mean-bug --arms vanilla
  python3 bench/run_bench.py --runner 'claude -p {prompt_file} --output-format json'
  python3 bench/run_bench.py --dry                 # validate harness, no agent

Check the exact headless flags against current Claude Code docs before a
publishable run; pass your verified command via --runner.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "bin" / "stoploss"
DEFAULT_RUNNER = "claude -p {prompt_file} --output-format json"

VANILLA_PROMPT = """\
This repository contains one or more bugs. Fix the code so that the command
`{test_cmd}` passes. Run it to verify; keep fixing until it is green, then stop.
Do not refactor or change anything unrelated to making the tests pass.
"""

STOPLOSS_PROMPT = """\
This repository uses the stoploss findings ledger (already initialized).
The CLI is: python3 "{engine}"

Follow this flow exactly:
1. Run the test command `{test_cmd}` once. For each distinct failure, register
   one finding:  python3 "{engine}" add --json -   with
   {{"title","claim","location","severity","verify"}} where verify is a test
   command that fails now and must pass after the fix.
2. python3 "{engine}" round
3. For each finding: python3 "{engine}" start <id>; fix ONLY that issue;
   python3 "{engine}" close <id>  (it verifies itself; obey exit code 2).
4. When `{test_cmd}` is green and all findings are closed, print
   python3 "{engine}" status and stop.
If any stoploss command exits 2 with HALT: summarize and stop immediately.
"""


def deep_get_usage(obj, acc):
    """Recursively harvest token usage fields from arbitrary runner JSON."""
    if isinstance(obj, dict):
        for k in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens"):
            v = obj.get(k)
            if isinstance(v, (int, float)):
                acc[k] = acc.get(k, 0) + int(v)
        if isinstance(obj.get("total_cost_usd"), (int, float)):
            acc["total_cost_usd"] = acc.get("total_cost_usd", 0.0) + obj["total_cost_usd"]
        for v in obj.values():
            deep_get_usage(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            deep_get_usage(v, acc)


def run_one(task_dir, arm, runner_tpl, dry):
    task = json.loads((task_dir / "task.json").read_text())
    work = Path(tempfile.mkdtemp(prefix=f"sl-bench-{task['name']}-{arm}-"))
    shutil.copytree(task_dir, work, dirs_exist_ok=True)

    if arm == "stoploss":
        subprocess.run([sys.executable, str(ENGINE), "init"],
                       cwd=work, capture_output=True, text=True)
        prompt = STOPLOSS_PROMPT.format(engine=ENGINE, test_cmd=task["test_cmd"])
    else:
        prompt = VANILLA_PROMPT.format(test_cmd=task["test_cmd"])
    pf = work / "_prompt.txt"
    pf.write_text(prompt)

    usage, rc_runner, elapsed = {}, None, 0.0
    if not dry:
        cmd = runner_tpl.format(prompt_file=str(pf))
        t0 = time.time()
        r = subprocess.run(cmd, shell=True, cwd=work,
                           capture_output=True, text=True, timeout=1800)
        elapsed = time.time() - t0
        rc_runner = r.returncode
        try:
            deep_get_usage(json.loads(r.stdout), usage)
        except Exception:
            print(f"  [warn] runner output not JSON-parseable for "
                  f"{task['name']}/{arm}; tokens recorded as 0")

    oracle = subprocess.run(task["test_cmd"], shell=True, cwd=work,
                            capture_output=True, text=True)
    solved = oracle.returncode == 0

    rounds = 0
    ledger = work / ".stoploss" / "ledger.json"
    if ledger.exists():
        try:
            rounds = json.loads(ledger.read_text()).get("round", 0)
        except Exception:
            pass

    return {
        "task": task["name"], "arm": arm, "solved": solved,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cost_usd": round(usage.get("total_cost_usd", 0.0), 4),
        "rounds": rounds, "runner_rc": rc_runner,
        "seconds": round(elapsed, 1), "workdir": str(work),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default=DEFAULT_RUNNER,
                    help="agent command; {prompt_file} is substituted")
    ap.add_argument("--tasks", nargs="*", default=None)
    ap.add_argument("--arms", nargs="*", default=["vanilla", "stoploss"])
    ap.add_argument("--dry", action="store_true",
                    help="skip the agent; validate harness mechanics only")
    ap.add_argument("--out", default=str(HERE / "results.csv"))
    args = ap.parse_args()

    task_dirs = sorted(d for d in (HERE / "tasks").iterdir() if d.is_dir())
    if args.tasks:
        task_dirs = [d for d in task_dirs if d.name in args.tasks]
    if not task_dirs:
        sys.exit("no tasks found")

    rows = []
    for td in task_dirs:
        for arm in args.arms:
            print(f"== {td.name} / {arm} ==")
            rows.append(run_one(td, arm, args.runner, args.dry))
            r = rows[-1]
            print(f"   solved={r['solved']} tokens={r['tokens_in']}+"
                  f"{r['tokens_out']} rounds={r['rounds']} {r['seconds']}s")

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nresults -> {args.out}\n")

    for arm in args.arms:
        sub = [r for r in rows if r["arm"] == arm]
        solved = [r for r in sub if r["solved"]]
        tok = sum(r["tokens_in"] + r["tokens_out"] for r in sub)
        line = (f"{arm:9} solved {len(solved)}/{len(sub)}  total tokens {tok:,}")
        if solved and tok:
            line += f"  -> {tok // len(solved):,} tokens per solved task"
        print(line)
    print("\nHeadline metric: tokens per solved task. Publish results.csv, the "
          "raw workdirs, and your exact --runner string for reproducibility.")


if __name__ == "__main__":
    main()
