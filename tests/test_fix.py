import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import infrasec_fix as fx  # noqa: E402

BAD = 'resource "aws_security_group" "app" {\n  ingress {\n    cidr_blocks = ["0.0.0.0/0"]\n  }\n}\n'
GOOD = 'resource "aws_security_group" "app" {\n  ingress {\n    cidr_blocks = ["10.0.0.0/8"]\n  }\n}\n'
HOLD = {"action": "hold", "attempt": 0,
        "risk_flags": [{"code": "NETWORK_OPEN_TO_WORLD", "message": "ssh open", "severity": "critical"}]}


class _Fake(BaseHTTPRequestHandler):
    reply = GOOD
    calls = 0

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        _Fake.calls += 1
        body = json.dumps({"choices": [{"message": {"content": _Fake.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("NEBIUS_API_KEY", "k")
    monkeypatch.setenv("NEBIUS_MODEL_ID", "nvidia/test")
    monkeypatch.setenv("NEBIUS_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    for k in ("INFRASEC_TOKEN", "CI_API_V4_URL", "CI_PROJECT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    _Fake.reply, _Fake.calls = GOOD, 0
    (tmp_path / "main.tf").write_text(BAD)
    (tmp_path / "d.json").write_text(json.dumps(HOLD))
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "add", "main.tf"], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    return tmp_path


def run(*extra):
    return fx.main(["--decision", "d.json", "--tf", "main.tf", *extra])


def test_good_fix_is_kept_and_committed(env, monkeypatch):
    monkeypatch.setenv("INFRASEC_RECHECK_CMD", "true")
    assert run("--commit") == 0
    assert "10.0.0.0/8" in (env / "main.tf").read_text()
    msg = subprocess.run(["git", "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
    assert "[infrasec-autofix]" in msg


def test_gate_still_holds_reverts(env, monkeypatch):
    monkeypatch.setenv("INFRASEC_RECHECK_CMD", "false")
    run("--commit")
    assert (env / "main.tf").read_text() == BAD
    assert subprocess.run(["git", "status", "--short", "main.tf"], capture_output=True, text=True).stdout == ""


def test_code_fences_and_think_are_stripped(env, monkeypatch):
    monkeypatch.setenv("INFRASEC_RECHECK_CMD", "true")
    _Fake.reply = "<think>hmm</think>\n```hcl\n" + GOOD + "```"
    run()
    assert (env / "main.tf").read_text() == GOOD


def test_non_tf_file_refused(env):
    (env / "main.py").write_text("x")
    assert fx.main(["--decision", "d.json", "--tf", "main.py"]) == 0
    assert _Fake.calls == 0


def test_oversized_diff_rejected(env, monkeypatch):
    monkeypatch.setenv("INFRASEC_RECHECK_CMD", "true")
    _Fake.reply = GOOD + "".join(f"# line {i}\n" for i in range(30))
    run()
    assert (env / "main.tf").read_text() == BAD


def test_resource_set_change_rejected(env, monkeypatch):
    monkeypatch.setenv("INFRASEC_RECHECK_CMD", "true")
    _Fake.reply = GOOD.replace('"app"', '"other"')
    run()
    assert (env / "main.tf").read_text() == BAD


def test_non_fixable_finding_never_calls_model(env):
    (env / "d.json").write_text(json.dumps({**HOLD, "risk_flags": [
        {"code": "IAM_RESOURCE_TOUCHED", "message": "iam", "severity": "high"}]}))
    run()
    assert _Fake.calls == 0 and (env / "main.tf").read_text() == BAD


def test_attempt_budget_blocks(env):
    (env / "d.json").write_text(json.dumps({**HOLD, "attempt": 2}))
    run()
    assert _Fake.calls == 0


def test_auto_apply_decision_skipped(env):
    (env / "d.json").write_text(json.dumps({"action": "auto_apply", "risk_flags": []}))
    run()
    assert _Fake.calls == 0


def test_skips_without_key(env, monkeypatch, capsys):
    monkeypatch.delenv("NEBIUS_API_KEY")
    assert run() == 0
    assert "skipping" in capsys.readouterr().out and _Fake.calls == 0


def test_default_recheck_runs_terraform_then_the_real_gate(env, monkeypatch):
    """No INFRASEC_RECHECK_CMD: stand-in `terraform` emits a saved plan, the real gate judges it."""
    import shutil
    repo = os.path.join(os.path.dirname(__file__), "..")
    shutil.copytree(os.path.join(repo, ".infrasec"), env / ".infrasec")
    bindir = env / "bin"
    bindir.mkdir()
    for name, plan in (("safe", "safe.json"), ("held", "ssh_open.json")):
        shim = bindir / f"terraform_{name}"
        shim.write_text('#!/bin/sh\nif [ "$1" = show ]; then cat "%s"; fi\nexit 0\n'
                        % os.path.abspath(os.path.join(repo, "demo", "plans", plan)))
        shim.chmod(0o755)
    monkeypatch.delenv("INFRASEC_RECHECK_CMD", raising=False)

    for name, expect_kept in (("safe", True), ("held", False)):
        (env / "main.tf").write_text(BAD)
        tfbin = env / "bin2"
        tfbin.mkdir(exist_ok=True)
        link = tfbin / "terraform"
        if link.exists():
            link.unlink()
        link.symlink_to(bindir / f"terraform_{name}")
        monkeypatch.setenv("PATH", f"{tfbin}:{os.environ['PATH']}")
        run()
        assert ("10.0.0.0/8" in (env / "main.tf").read_text()) is expect_kept
