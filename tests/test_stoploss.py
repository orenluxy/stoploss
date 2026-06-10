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


def test_triage_noise_to_dismissed(tmp_path, monkeypatch):
    """stoploss triage F-x --verdict NOISE → dismissed; re-audit skips it."""
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

    subprocess.run(["python", str(BIN), "triage", fid, "--verdict", "NOISE"],
                   cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8")
    db2 = json.loads((tmp_path / ".stoploss" / "ledger.json").read_text(encoding="utf-8"))
    assert db2["findings"][0]["status"] == "dismissed"

    # Re-audit: same fp → dismissed → skip; 0 new
    result2 = run_audit(tmp_path, cfg)
    assert result2.returncode == 0
    assert "0 new" in result2.stdout


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
