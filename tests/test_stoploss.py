"""Policy tests for the stoploss engine. Run: python3 -m pytest tests/ -q"""
import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "bin" / "stoploss"
BIN = ENGINE  # alias for direct-import tests


def run(cmd, workdir=None):
    """Thin wrapper for tests that need a simple run(cmd) call."""
    cwd = workdir or Path(os.getcwd())
    rc, out = sl(cwd, cmd)
    assert rc == 0, out


def sl(workdir, *args, stdin=None):
    r = subprocess.run([sys.executable, str(ENGINE), *args], cwd=workdir,
                       input=stdin, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def add(workdir, sev="major", verify="true", caused_by=None, title="t"):
    args = ["add", "--title", title, "--claim", "c", "--location", "f:s",
            "--severity", sev, "--verify", verify]
    if caused_by:
        args += ["--caused-by", caused_by]
    return sl(workdir, *args)


def init(tmp_path):
    rc, out = sl(tmp_path, "init")
    assert rc == 0, out
    return tmp_path


def test_close_is_gated_by_verify_command(tmp_path):
    init(tmp_path)
    add(tmp_path, verify="false")          # F-1: verify always fails, no caused_by
    rc, out = sl(tmp_path, "close", "F-1")
    assert rc == 2 and "FAILED (attempt 1/2)" in out
    rc, out = sl(tmp_path, "close", "F-1")  # second strike -> benched, NO halt
    assert rc == 2
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text())
    assert db["halted"] is None, f"expected no halt for independent finding, got: {db['halted']}"
    assert db["findings"][0]["status"] == "backlog"


def test_close_passes_when_verify_passes(tmp_path):
    init(tmp_path)
    add(tmp_path, verify="true")
    rc, out = sl(tmp_path, "close", "F-1")
    assert rc == 0 and "closed (verified)" in out


def test_manual_close_requires_agent_verdict(tmp_path):
    init(tmp_path)
    add(tmp_path, verify="MANUAL: eyeball it")
    rc, out = sl(tmp_path, "close", "F-1")
    assert rc != 0 and "MANUAL" in out
    rc, out = sl(tmp_path, "close", "F-1", "--agent-verdict", "PASS")
    assert rc == 0


def test_noise_rule_after_audit_round(tmp_path):
    init(tmp_path)
    add(tmp_path)                                  # F-1 in round 0 -> open
    sl(tmp_path, "round")
    rc, out = add(tmp_path, title="organic-new")   # round 1, no caused_by
    assert "backlog" in out and "review noise" in out


def test_regression_with_caused_by_stays_open_but_chain_caps(tmp_path):
    init(tmp_path)
    add(tmp_path)                                  # F-1
    sl(tmp_path, "round")
    rc, out = add(tmp_path, caused_by="F-1")       # F-2 chain 1 -> open
    assert "open" in out
    rc, out = add(tmp_path, caused_by="F-2")       # F-3 chain 2 -> open
    assert "open" in out
    rc, out = add(tmp_path, caused_by="F-3")       # F-4 chain 3 -> backlog
    assert "backlog" in out and "chain" in out


def test_monotonic_halt_with_regression_exemption(tmp_path):
    init(tmp_path)
    add(tmp_path)                       # F-1
    add(tmp_path)                       # F-2
    rc, out = sl(tmp_path, "round")     # round 1, last=2
    assert rc == 0
    sl(tmp_path, "close", "F-1")        # open: 1
    rc, out = add(tmp_path, caused_by="F-2")   # regression in round 1 -> open: 2
    rc, out = sl(tmp_path, "round")     # effective = 2 - 1 exempt = 1 < 2 -> ok
    assert rc == 0, out
    # now stagnate: nothing closed, advance again
    rc, out = sl(tmp_path, "round")
    assert rc == 2 and "not converging" in out


def test_drained_ledger_does_not_halt_as_stagnation(tmp_path):
    """0 open twice in a row is 'done', not 'stuck'. Before the guard, the round after a fully
    drained one halted on 0 >= 0 and needed a human resume (measured 2026-07-29)."""
    init(tmp_path)
    add(tmp_path)                        # F-1
    rc, out = sl(tmp_path, "round")      # round 1, last=1
    assert rc == 0, out
    sl(tmp_path, "close", "F-1")         # open: 0
    rc, out = sl(tmp_path, "round")      # 0 < 1 -> fine, last=0
    assert rc == 0, out
    rc, out = sl(tmp_path, "round")      # 0 >= 0, but nothing open -> must NOT halt
    assert rc == 0, f"drained ledger must not halt; got {rc}: {out}"
    # real stagnation (open count that refuses to shrink) still halts —
    # covered by test_monotonic_halt_with_regression_exemption above.


def test_severity_floor_in_late_rounds(tmp_path):
    init(tmp_path)
    add(tmp_path)            # keep one open so rounds can advance
    sl(tmp_path, "round")
    sl(tmp_path, "close", "F-1")
    sl(tmp_path, "round")
    add(tmp_path, caused_by=None)  # noise -> backlog, fine
    # force round 3 by closing nothing won't work (monotonic), so resume-style:
    rc, out = sl(tmp_path, "resume", "--rounds", "5")
    assert rc == 0
    sl(tmp_path, "round")
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text())
    while db["round"] < 3:
        sl(tmp_path, "resume", "--rounds", "5")
        sl(tmp_path, "round")
        db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text())
    rc, out = add(tmp_path, sev="style", caused_by="F-1")
    assert "backlog" in out and "severity floor" in out


def test_max_rounds_halts_and_only_human_resume_clears(tmp_path):
    init(tmp_path)
    for i in range(9):
        add(tmp_path, title=f"t{i}")
    closed = 0
    rc = 0
    while rc == 0:
        rc, out = sl(tmp_path, "round")
        if rc == 0:
            closed += 1
            sl(tmp_path, "close", f"F-{closed}")
    assert "HALT" in out
    rc2, out2 = sl(tmp_path, "round")          # still halted
    assert rc2 == 2 and "HALTED" in out2
    rc3, _ = sl(tmp_path, "resume", "--rounds", "2")
    assert rc3 == 0
    rc4, out4 = sl(tmp_path, "round")
    assert rc4 == 0, out4


def test_stop_hook_blocks_on_pending_and_respects_guard(tmp_path):
    init(tmp_path)
    add(tmp_path)
    sl(tmp_path, "start", "F-1")
    payload = json.dumps({"cwd": str(tmp_path)})
    rc, out = sl(tmp_path, "hook", "stop", stdin=payload)
    assert rc == 2 and "pending" in out
    guard = json.dumps({"cwd": str(tmp_path), "stop_hook_active": True})
    rc, out = sl(tmp_path, "hook", "stop", stdin=guard)
    assert rc == 0
    sl(tmp_path, "close", "F-1")
    rc, out = sl(tmp_path, "hook", "stop", stdin=payload)
    assert rc == 0


def test_prompt_hook_injects_ledger_on_recheck_phrases(tmp_path):
    init(tmp_path)
    add(tmp_path)
    payload = json.dumps({"cwd": str(tmp_path), "prompt": "please check again"})
    rc, out = sl(tmp_path, "hook", "prompt", stdin=payload)
    assert rc == 0 and "Do NOT free-audit" in out and "F-1" in out
    payload = json.dumps({"cwd": str(tmp_path), "prompt": "תבדוק שוב את הקוד"})
    rc, out = sl(tmp_path, "hook", "prompt", stdin=payload)
    assert "F-1" in out


def test_add_via_json_stdin(tmp_path):
    init(tmp_path)
    blob = json.dumps({"title": "x", "claim": "y", "location": "a:b",
                       "severity": "critical", "verify": "true"})
    rc, out = sl(tmp_path, "add", "--json", "-", stdin=blob)
    assert rc == 0 and "F-1 -> open" in out


def test_add_finding_helper_applies_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("init")
    import importlib.machinery, importlib.util, sys
    # Load the module fresh for this test (file has no .py extension)
    mod_name = "stoploss_p1t1"
    loader = importlib.machinery.SourceFileLoader(mod_name, str(BIN))
    spec = importlib.util.spec_from_loader(mod_name, loader)
    sl_mod = importlib.util.module_from_spec(spec)
    loader.exec_module(sl_mod)

    s = sl_mod.store_or_die()
    db, cfg = s.ledger, s.config

    # Advance to round 2 (post-audit)
    db["round"] = 2
    s.save_ledger(db)
    db = s.ledger  # re-read

    # manual add (not audit) after round 0 with no caused_by -> backlog (noise rule)
    fid, status, note = sl_mod.add_finding(db, cfg,
        {"title": "x", "claim": "c", "location": "f.js:1", "severity": "major",
         "verify": "MANUAL: x"},
        source="manual")
    assert status == "backlog", f"expected backlog, got {status}"
    assert "noise" in note.lower()

    # audit-sourced add bypasses noise rule -> open
    fid2, status2, note2 = sl_mod.add_finding(db, cfg,
        {"title": "y", "claim": "c", "location": "f.js:2", "severity": "major",
         "verify": "MANUAL: y"},
        source="audit:k8s")
    assert status2 == "open", f"expected open, got {status2}"


def test_fingerprint_is_path_and_line_stable(tmp_path):
    import importlib.machinery, importlib.util
    mod_name = "stoploss_fp"
    loader = importlib.machinery.SourceFileLoader(mod_name, str(BIN))
    spec = importlib.util.spec_from_loader(mod_name, loader)
    sl = importlib.util.module_from_spec(spec)
    loader.exec_module(sl)
    root = tmp_path

    # backslash vs forward slash + different line numbers -> same fp
    a = sl.finding_fp("k8s", None, str(root / "engine\\x.js") + ":42", "child_process used", root)
    b = sl.finding_fp("k8s", None, "engine/x.js:99", "child_process used", root)
    assert a == b, f"expected {a} == {b}"

    # explicit key wins, ignores location
    c = sl.finding_fp("design", "hex:engine/y.js:#FFF", None, "t", root)
    assert c == "design:hex:engine/y.js:#FFF"


# ── helpers for audit tests ─────────────────────────────────────────────────

def write_auditor(tmp_path, name, findings, extra_lines="", complete=True):
    """Write a fake auditor script that emits JSONL findings + optional sentinel."""
    import json as _json
    lines = [
        "import json, sys",
    ]
    for f in findings:
        lines.append(f"print(json.dumps({_json.dumps(f)}))")
    if extra_lines:
        lines.append(extra_lines)
    if complete:
        lines.append('print(json.dumps({"audit_complete": True}))')
    p = tmp_path / f"{name}.py"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def load_sl(tmp_path, monkeypatch):
    """Init stoploss in tmp_path and return the loaded module."""
    monkeypatch.chdir(tmp_path)
    run("init")
    from importlib.machinery import SourceFileLoader
    sl = SourceFileLoader("sl_audit", str(BIN)).load_module()
    return sl


def run_audit(tmp_path, auditors_config):
    """Run `stoploss audit` with the given auditors list in config."""
    import json
    cfg_path = tmp_path / ".stoploss" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["auditors"] = auditors_config
    cfg["diff_base"] = "HEAD"  # avoid needing actual git remote
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    result = subprocess.run(
        ["python", str(BIN), "audit"],
        cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8"
    )
    return result


# ── audit tests ─────────────────────────────────────────────────────────────

def test_audit_ingests_findings_as_open(tmp_path, monkeypatch):
    """Basic: one deterministic finding lands as open with source audit:<name>."""
    monkeypatch.chdir(tmp_path)
    run("init")
    findings = [{"title": "child_process", "claim": "spawn used", "location": "engine/x.js:5",
                 "severity": "major", "verify": "MANUAL: check engine/x.js"}]
    auditor = write_auditor(tmp_path, "k8s", findings)
    result = run_audit(tmp_path, [{"name": "k8s", "cmd": f"python {auditor}", "type": "deterministic"}])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 new" in result.stdout
    # verify it's in the ledger as open
    import json
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    open_f = [f for f in db["findings"] if f["status"] == "open"]
    assert len(open_f) == 1
    assert open_f[0]["source"] == "audit:k8s"


def test_audit_dedup_on_second_run(tmp_path, monkeypatch):
    """Re-running audit on same code → 0 new (dedup by fingerprint)."""
    monkeypatch.chdir(tmp_path)
    run("init")
    findings = [{"title": "hex color", "claim": "#FFF used", "location": "engine/x.js:10",
                 "severity": "minor", "verify": "MANUAL: fix hex"}]
    auditor = write_auditor(tmp_path, "design", findings)
    cfg = [{"name": "design", "cmd": f"python {auditor}", "type": "deterministic"}]
    run_audit(tmp_path, cfg)  # first run
    result2 = run_audit(tmp_path, cfg)  # second run, same findings
    assert result2.returncode == 0
    assert "0 new" in result2.stdout


def test_audit_reopens_closed_on_regression(tmp_path, monkeypatch):
    """Close a finding, then audit emits same fp → reopens (regression detected)."""
    monkeypatch.chdir(tmp_path)
    run("init")
    findings = [{"key": "static:engine/x.js", "title": "static key",
                 "claim": "c", "location": "engine/x.js:1",
                 "severity": "major", "verify": "MANUAL: x"}]
    auditor = write_auditor(tmp_path, "k8s", findings)
    cfg = [{"name": "k8s", "cmd": f"python {auditor}", "type": "deterministic"}]
    run_audit(tmp_path, cfg)  # ingest
    # close it manually via subprocess
    import json
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    f = db["findings"][0]; f["status"] = "closed"
    (tmp_path / ".stoploss" / "ledger.json").write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    # re-audit → should reopen
    result2 = run_audit(tmp_path, cfg)
    assert result2.returncode == 0, result2.stdout + result2.stderr
    assert "1 reopened" in result2.stdout
    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db2["findings"][0]["status"] == "open"
    assert db2["findings"][0]["reopens"] == 1


def test_reopen_adopts_the_current_defect(tmp_path, monkeypatch):
    """A reopen carries TODAY's claim/verify, not the text the id was first filed with.

    The fingerprint is coarse on purpose (one bucket per check per client, no date), so a different
    defect of the same kind lands on the existing id. Keeping the original text made the board
    describe an already-fixed defect, and the stale `verify` would pass and close it unread.
    """
    monkeypatch.chdir(tmp_path)
    run("init")
    key = "judge:contradiction:some-client"
    old = [{"key": key, "title": "judge on some-client", "claim": "old defect",
            "location": "http://x", "severity": "major", "verify": "MANUAL: old quote",
            "he": {"what": "הפגם הישן", "where": "w", "fix": "f"}}]
    auditor = write_auditor(tmp_path, "nightly", old)
    cfg = [{"name": "nightly", "cmd": f"python {auditor}", "type": "deterministic"}]
    run_audit(tmp_path, cfg)
    import json
    led = tmp_path / ".stoploss" / "ledger.json"
    db = json.loads(led.read_text(encoding="utf-8"))
    db["findings"][0]["status"] = "closed"
    led.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    # same fp, different defect — this is the real-world case that misled the board
    fresh = [{**old[0], "claim": "new defect", "verify": "MANUAL: new quote",
              "he": {"what": "הפגם החדש", "where": "w2", "fix": "f2"},
              "evidence": {"quote": "today's sentence"}}]
    auditor2 = write_auditor(tmp_path, "nightly", fresh)
    result = run_audit(tmp_path, [{"name": "nightly", "cmd": f"python {auditor2}", "type": "deterministic"}])
    assert "1 reopened" in result.stdout, result.stdout + result.stderr
    f = json.loads(led.read_text(encoding="utf-8"))["findings"][0]
    assert f["status"] == "open" and f["reopens"] == 1
    assert f["claim"] == "new defect" and f["verify"] == "MANUAL: new quote"
    assert f["he"]["what"] == "הפגם החדש"
    assert f["evidence"]["quote"] == "today's sentence"


def test_refind_moves_the_finding_to_today(tmp_path, monkeypatch):
    """A finding the sweep finds again is re-dated to today, with its history kept.

    Oren, 2026-08-05: an old finding stayed filed under the day it was first seen, so every session
    re-checked it, found the original sentence already gone, and burned the same tokens again. One
    copy, dated by the sweep that found it; `first_seen` + `moved_from` let the old day say
    "moved to <today>" instead of showing a stale open row.
    """
    monkeypatch.chdir(tmp_path)
    run("init")
    fs = [{"key": "judge:contradiction:c1", "title": "t", "claim": "c", "location": "http://x",
           "severity": "major", "verify": "MANUAL: q"}]
    auditor = write_auditor(tmp_path, "nightly", fs)
    cfg = [{"name": "nightly", "cmd": f"python {auditor}", "type": "deterministic"}]
    run_audit(tmp_path, cfg)
    import json
    led = tmp_path / ".stoploss" / "ledger.json"
    db = json.loads(led.read_text(encoding="utf-8"))
    db["findings"][0]["created"] = "2026-01-02T03:04:05+00:00"   # filed on an old day
    led.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    run_audit(tmp_path, cfg)   # same fp, still open, found again "today"
    f = json.loads(led.read_text(encoding="utf-8"))["findings"][0]
    assert f["first_seen"].startswith("2026-01-02")
    assert f["moved_from"] == ["2026-01-02"]
    assert not f["created"].startswith("2026-01-02")   # moved onto the day it was found again


def test_audit_missing_sentinel_aborts(tmp_path, monkeypatch):
    """Auditor that exits without sentinel → AUDIT FAILED, exit 2."""
    monkeypatch.chdir(tmp_path)
    run("init")
    auditor = write_auditor(tmp_path, "bad", [], complete=False)  # no sentinel
    result = run_audit(tmp_path, [{"name": "bad", "cmd": f"python {auditor}", "type": "deterministic"}])
    assert result.returncode == 2
    assert "AUDIT FAILED" in result.stdout or "AUDIT FAILED" in result.stderr


def test_audit_tolerates_nonjson_noise(tmp_path, monkeypatch):
    """npm-style banner lines before JSONL are ignored; finding still ingested."""
    monkeypatch.chdir(tmp_path)
    run("init")
    auditor_code = (
        "import json\n"
        "print('> script@1.0.0 audit')\n"  # noise line
        "print('npm WARN ...')\n"           # more noise
        'print(json.dumps({"title":"t","claim":"c","location":"f.js:1","severity":"major","verify":"MANUAL: x"}))\n'
        'print(json.dumps({"audit_complete": True}))\n'
    )
    auditor = tmp_path / "noisy.py"
    auditor.write_text(auditor_code, encoding="utf-8")
    result = run_audit(tmp_path, [{"name": "noisy", "cmd": f"python {auditor}", "type": "deterministic"}])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 new" in result.stdout


def test_audit_bypasses_noise_rule_at_round2(tmp_path, monkeypatch):
    """Audit-sourced findings at round 2 land as open, not backlog."""
    import json
    monkeypatch.chdir(tmp_path)
    run("init")
    db_p = tmp_path / ".stoploss" / "ledger.json"
    db = json.loads(db_p.read_text(encoding="utf-8"))
    db["round"] = 2
    db_p.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    findings = [{"title": "round2 find", "claim": "c", "location": "x.js:1",
                 "severity": "major", "verify": "MANUAL: x"}]
    auditor = write_auditor(tmp_path, "k8s", findings)
    result = run_audit(tmp_path, [{"name": "k8s", "cmd": f"python {auditor}", "type": "deterministic"}])
    assert result.returncode == 0
    db2 = json.loads(db_p.read_text(encoding="utf-8"))
    f = db2["findings"][0]
    assert f["status"] == "open", f"expected open, got {f['status']}"


# ── P1-T5: bench-without-halt ────────────────────────────────────────────────

def test_audit_finding_benches_no_halt_on_two_strikes(tmp_path, monkeypatch):
    """Independent audit finding (no caused_by) fails twice → benched (backlog), NO db.halted, exit 2."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    # add finding at round 0 (no caused_by) → status=open
    rc, out = sl(tmp_path, "add",
                 "--title", "bad find", "--claim", "c",
                 "--location", "f.js:1", "--severity", "major",
                 "--verify", "python -c \"import sys; sys.exit(1)\"")
    assert rc == 0 and "open" in out, out
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    fid = db["findings"][0]["id"]

    sl(tmp_path, "start", fid)

    # first close → fails (attempt 1)
    r1_rc, r1_out = sl(tmp_path, "close", fid)
    assert r1_rc == 2
    assert "attempt 1/2" in r1_out

    # second close → benched, NO halt
    r2_rc, r2_out = sl(tmp_path, "close", fid)
    assert r2_rc == 2
    assert "benched" in r2_out.lower()

    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db2["halted"] is None, f"expected no halt, got: {db2['halted']}"
    assert db2["findings"][0]["status"] == "backlog"
    assert db2["findings"][0].get("benched") is True


def test_caused_by_finding_halts_on_two_strikes(tmp_path, monkeypatch):
    """Regression (has caused_by) fails twice → HALT (original behavior)."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    # parent finding at round 0
    sl(tmp_path, "add", "--title", "parent", "--claim", "c",
       "--location", "f.js:1", "--severity", "major", "--verify", "true")
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    parent_id = db["findings"][0]["id"]
    sl(tmp_path, "round")  # advance to round 1
    # regression finding with caused_by → open despite being after round 0
    sl(tmp_path, "add", "--title", "regression", "--claim", "c",
       "--location", "f.js:2", "--severity", "major",
       "--verify", "false",
       "--caused-by", parent_id)
    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    reg_id = db2["findings"][1]["id"]
    assert db2["findings"][1]["status"] == "open", f"regression should be open, got {db2['findings'][1]['status']}"
    sl(tmp_path, "start", reg_id)
    sl(tmp_path, "close", reg_id)  # attempt 1
    r2_rc, r2_out = sl(tmp_path, "close", reg_id)  # attempt 2
    assert r2_rc == 2
    db3 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db3["halted"] is not None, "expected HALT for caused_by finding"


# ── P1-T6: Stop hook blocks on open/triage ───────────────────────────────────

def test_stop_blocks_on_open_findings_after_round0(tmp_path, monkeypatch):
    """Round 1, one open finding (no pending) → hook stop exits 2."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    # add at round 0 so it lands as open (not backlogged by noise rule)
    sl(tmp_path, "add", "--title", "t", "--claim", "c",
       "--location", "f.js:1", "--severity", "major", "--verify", "MANUAL: x")
    sl(tmp_path, "round")  # advance to round 1; open count = 1
    hook_input = json.dumps({"stop_hook_active": False, "cwd": str(tmp_path)})
    rc, out = sl(tmp_path, "hook", "stop", stdin=hook_input)
    assert rc == 2, f"expected exit 2, got {rc}; output: {out}"


def test_stop_allows_when_clean(tmp_path, monkeypatch):
    """Round 1, zero open/triage/pending → hook stop exits 0."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    sl(tmp_path, "round")
    hook_input = json.dumps({"stop_hook_active": False, "cwd": str(tmp_path)})
    rc, out = sl(tmp_path, "hook", "stop", stdin=hook_input)
    assert rc == 0, f"expected exit 0, got {rc}; output: {out}"


def _repo_with_upstream(tmp_path, name, dirty):
    """A git repo whose `@{u}` resolves, with `dirty` uncommitted (i.e. in flight).
    Without a resolvable upstream `_pending_files` returns None and EVERYTHING blocks,
    so the scoping branch is only reachable from a repo shaped like this."""
    bare, work = tmp_path / f"{name}.git", tmp_path / name
    work.mkdir()
    g = lambda *a, cwd=work: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    g("init", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("remote", "add", "origin", str(bare))
    (work / "seed.txt").write_text("x", encoding="utf-8")
    g("add", "-A"); g("commit", "-m", "seed"); g("push", "-u", "origin", "main")
    (work / dirty).write_text("y", encoding="utf-8")
    return work


def test_stop_scopes_blockers_to_files_in_flight(tmp_path, monkeypatch):
    """A finding blocks session-end only when its location names a file in flight.
    The tree is shared between parallel sessions — an unrelated peer finding used to hold
    every session open (Oren 2026-07-29, same rule as the push gate)."""
    hook = lambda w: sl(w, "hook", "stop",
                        stdin=json.dumps({"stop_hook_active": False, "cwd": str(w)}))

    # unrelated: touched.js is dirty, the finding points at other.js → not enforced
    away = _repo_with_upstream(tmp_path, "away", "touched.js")
    monkeypatch.chdir(away)
    sl(away, "init")
    sl(away, "add", "--title", "peer", "--claim", "c", "--location", "other.js:1",
       "--severity", "major", "--verify", "MANUAL: x")
    sl(away, "round")
    rc, out = hook(away)
    assert rc == 0, f"unrelated finding must not block; got {rc}: {out}"
    assert "not related" in out, out

    # related: same file is dirty AND named by the finding → still blocks
    near = _repo_with_upstream(tmp_path, "near", "touched.js")
    monkeypatch.chdir(near)
    sl(near, "init")
    sl(near, "add", "--title", "mine", "--claim", "c", "--location", "touched.js:9",
       "--severity", "major", "--verify", "MANUAL: x")
    sl(near, "round")
    rc, out = hook(near)
    assert rc == 2, f"related finding must block; got {rc}: {out}"


# ── P1-T7: check_gate green push signal ─────────────────────────────────────

def _make_clean_audit(tmp_path, monkeypatch):
    """Helper: init, run a clean audit (zero findings), return run_audit result."""
    monkeypatch.chdir(tmp_path)
    run("init")
    auditor = write_auditor(tmp_path, "clean", [])  # zero findings
    return run_audit(tmp_path, [{"name": "clean", "cmd": f"python {auditor}", "type": "deterministic"}])


def test_check_exit0_when_clean(tmp_path, monkeypatch):
    """Zero findings after audit → audit --check exits 0."""
    _make_clean_audit(tmp_path, monkeypatch)
    cfg_p = tmp_path / ".stoploss" / "config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    auditor = write_auditor(tmp_path, "clean2", [])
    cfg["auditors"] = [{"name": "clean2", "cmd": f"python {auditor}", "type": "deterministic"}]
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    rc, out = sl(tmp_path, "audit", "--check")
    assert rc == 0, out
    assert "READY TO PUSH" in out


def test_check_exit2_with_open(tmp_path, monkeypatch):
    """One open finding → audit --check exits 2."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    findings = [{"title": "bug", "claim": "c", "location": "f.js:1",
                 "severity": "major", "verify": "MANUAL: x"}]
    auditor = write_auditor(tmp_path, "k8s", findings)
    cfg_p = tmp_path / ".stoploss" / "config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    cfg["auditors"] = [{"name": "k8s", "cmd": f"python {auditor}", "type": "deterministic"}]
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    rc, out = sl(tmp_path, "audit", "--check")
    assert rc == 2, out
    assert "NOT READY" in out


def test_confirm_streak_counts_and_reject_breaks_it(tmp_path, monkeypatch):
    """Oren's confirmation on a closed fix is the trust gate: 3 in a row, a reject resets.

    A green verify proves the symptom is gone; only he can say the right thing got fixed. A rejected
    fix must BREAK the streak, not silently leave the closed set and take its evidence with it.
    """
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    for i in (1, 2):
        sl(tmp_path, "add", "--title", f"f{i}", "--claim", "c", "--location", f"f{i}.js:1",
           "--severity", "major", "--source", "boris:x", "--verify", "python -c \"pass\"")
        sl(tmp_path, "start", f"F-{i}")
        assert sl(tmp_path, "close", f"F-{i}")[0] == 0

    rc, out = sl(tmp_path, "confirm", "F-1")
    assert rc == 0 and "1/3" in out, out
    rc, out = sl(tmp_path, "confirm", "F-2")
    assert rc == 0 and "2/3" in out, out

    # reject the newest → it reopens and the chain breaks at it
    rc, out = sl(tmp_path, "confirm", "F-2", "--reject")
    assert rc == 0 and "broken" in out.lower(), out
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    f2 = [f for f in db["findings"] if f["id"] == "F-2"][0]
    assert f2["status"] == "open" and f2["confirmed"] is False and f2["reopens"] == 1

    # an unconfirmed close is skipped, not counted, and cannot be confirmed twice into a lie
    rc, out = sl(tmp_path, "confirm", "F-2")
    assert rc != 0 and "not closed" in out, out


def test_check_exit2_with_benched_boris_finding(tmp_path, monkeypatch):
    """A boris item frozen after two failed fixes blocks the push gate, like an audit one.

    record_failure promises "It still BLOCKS push"; check_gate used to filter benched findings
    to source `audit:` only, so that promise was false for every boris item — the whole ceiling
    of the boris loop leaked at the push gate.
    """
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    rc, out = sl(tmp_path, "add", "--title", "boris item", "--claim", "c",
                 "--location", "f.js:1", "--severity", "major",
                 "--source", "boris:item-7",
                 "--verify", "python -c \"import sys; sys.exit(1)\"")
    assert rc == 0 and "open" in out, out
    sl(tmp_path, "start", "F-1")
    assert sl(tmp_path, "close", "F-1")[0] == 2          # attempt 1/2
    assert sl(tmp_path, "close", "F-1")[0] == 2          # benched, no halt

    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db["findings"][0]["status"] == "backlog" and db["findings"][0]["benched"] is True
    assert db["halted"] is None, db["halted"]

    auditor = write_auditor(tmp_path, "clean", [])
    cfg_p = tmp_path / ".stoploss" / "config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    cfg["auditors"] = [{"name": "clean", "cmd": f"python {auditor}", "type": "deterministic"}]
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    rc, out = sl(tmp_path, "audit", "--check")
    assert rc == 2, out
    assert "benched" in out and "F-1" in out, out


# ── P1-T8: Hebrew audit triggers in prompt hook ──────────────────────────────

def test_prompt_hook_fires_on_hebrew_audit_noun(tmp_path, monkeypatch):
    """'תעשה אודיט לפני פוש' triggers ledger injection (the user's actual phrase)."""
    monkeypatch.chdir(tmp_path)
    sl(tmp_path, "init")
    # add a finding so there's something to report in the ledger
    sl(tmp_path, "add", "--title", "t", "--claim", "c",
       "--location", "f.js:1", "--severity", "major", "--verify", "MANUAL: x")
    hook_input = json.dumps({
        "cwd": str(tmp_path),
        "prompt": "תעשה אודיט לפני פוש"
    })
    rc, out = sl(tmp_path, "hook", "prompt", stdin=hook_input)
    assert rc == 0
    assert "[stoploss]" in out, (
        f"Hook should print [stoploss] ledger line for 'תעשה אודיט לפני פוש'. "
        f"Got: '{out}'"
    )


# ── P1-T9: triage command ────────────────────────────────────────────────────

def test_triage_real_to_open(tmp_path, monkeypatch):
    """stoploss triage F-x --verdict REAL → status open."""
    monkeypatch.chdir(tmp_path)
    run("init")
    # Use audit to create a triage finding (type: triage)
    findings = [{"title": "heavy handler", "claim": "await chain in route",
                 "location": "server.js:100", "severity": "major", "verify": "MANUAL: check route"}]
    auditor = write_auditor(tmp_path, "candidates", findings)
    run_audit(tmp_path, [{"name": "candidates", "cmd": f"python {auditor}", "type": "triage"}])
    import json
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    fid = db["findings"][0]["id"]
    assert db["findings"][0]["status"] == "triage", f"expected triage, got {db['findings'][0]['status']}"

    result = subprocess.run(["python", str(BIN), "triage", fid, "--verdict", "REAL"],
                            cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db2["findings"][0]["status"] == "open"


def test_triage_not_to_dismissed(tmp_path, monkeypatch):
    """stoploss triage F-x --verdict NOT → dismissed; re-audit skips it."""
    monkeypatch.chdir(tmp_path)
    run("init")
    findings = [{"key": "cand:server.js", "title": "candidate", "claim": "c",
                 "location": "server.js:50", "severity": "minor", "verify": "MANUAL: check"}]
    auditor = write_auditor(tmp_path, "candidates", findings)
    cfg = [{"name": "candidates", "cmd": f"python {auditor}", "type": "triage"}]
    run_audit(tmp_path, cfg)
    import json
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    fid = db["findings"][0]["id"]

    subprocess.run(["python", str(BIN), "triage", fid, "--verdict", "NOT"],
                   cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8")
    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db2["findings"][0]["status"] == "dismissed"

    # Re-audit: same fp → dismissed → skip; 0 new
    result2 = run_audit(tmp_path, cfg)
    assert result2.returncode == 0
    assert "0 new" in result2.stdout


def test_backlog_raise_needs_a_red_verify(tmp_path):
    """A shelved finding re-enters the loop only while its verify still fails.

    F-60 sat in backlog with `grep prevViews` as its verify. The code was fixed weeks earlier and
    the grep matched the comment documenting the fix, so raising it would have produced a green
    close on zero work — the first live run of the trust gate, on a no-op.
    """
    init(tmp_path)
    add(tmp_path)                            # F-1 at round 0 -> open, so `round` has work
    sl(tmp_path, "round")
    add(tmp_path, verify="true")             # F-2: green verify -> backlog (review noise)
    add(tmp_path, verify="false")            # F-3: red verify   -> backlog (review noise)
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert [f["status"] for f in db["findings"][1:]] == ["backlog", "backlog"]

    rc, out = sl(tmp_path, "triage", "F-2", "--verdict", "REAL")
    assert rc != 0 and "GREEN" in out, out
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db["findings"][1]["status"] == "backlog", "a refused raise must not move the finding"

    # The other door: the defect is gone, so drop the row instead of raising it.
    rc, out = sl(tmp_path, "triage", "F-2", "--verdict", "NOT")
    assert rc == 0, out
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db["findings"][1]["status"] == "dismissed"

    # A still-red backlog item raises, and the boris source makes its bench block push.
    rc, out = sl(tmp_path, "triage", "F-3", "--verdict", "REAL")
    assert rc == 0 and "open" in out, out
    db = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db["findings"][2]["status"] == "open"
    assert db["findings"][2]["source"] == "boris:F-3"


def test_status_shows_triage_and_dismissed(tmp_path, monkeypatch):
    """stoploss status output includes triage and dismissed counts."""
    monkeypatch.chdir(tmp_path)
    run("init")
    findings = [{"title": "cand", "claim": "c", "location": "x.js:1",
                 "severity": "minor", "verify": "MANUAL: x"}]
    auditor = write_auditor(tmp_path, "cands", findings)
    run_audit(tmp_path, [{"name": "cands", "cmd": f"python {auditor}", "type": "triage"}])
    result = subprocess.run(["python", str(BIN), "status"],
                            cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert "triage" in result.stdout.lower()
