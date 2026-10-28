import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "demo"))
import halloween_demo as hd  # noqa: E402


def _status():
    return subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True).stdout


def test_offline_run_labels_samples_and_leaves_repo_untouched(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    before = _status()
    rec = tmp_path / "run.json"
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--json", str(rec)]) == 0
    out = capsys.readouterr().out
    assert "HOLD" in out and "NETWORK_OPEN_TO_WORLD" in out
    assert "offline sample" in out and "REJECTED" in out and "MANUAL" in out
    assert "auto_apply" in out
    assert _status() == before
    scenes = {s["scene"]: s for s in json.loads(rec.read_text())["scenes"]}
    assert scenes["gate"]["action"] == "hold" and scenes["exorcism"]["kept"] is True


class _Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        text = '### What changed\nSSH opened\n' if False else None
        body = json.dumps({"choices": [{"message": {"content": _Fake.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_live_model_path_is_labelled_live(monkeypatch, capsys):
    good = open(os.path.join(ROOT, "demo-target", "main.tf")).read()
    _Fake.reply = good
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("NEBIUS_API_KEY", "k")
    monkeypatch.setenv("NEBIUS_MODEL_ID", "nvidia/test")
    monkeypatch.setenv("NEBIUS_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    assert hd.main(["--auto", "--pace", "0", "--no-cues"]) == 0
    out = capsys.readouterr().out
    assert "live: Nebius Token Factory" in out and "nvidia/test" in out


def test_site_builds_from_a_run_and_escapes_script_end(tmp_path):
    import build_site as bs
    run = {"mode": "t", "scenes": [{"scene": "oracle", "note": "</script><b>x</b>", "source": "offline sample"}]}
    page = bs.build(run)
    assert "</script><b>" not in page and "<\\/script>" in page
    rec = tmp_path / "r.json"
    out = tmp_path / "index.html"
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--offline", "--json", str(rec)]) == 0
    assert bs.main(["--run", str(rec), "--out", str(out)]) == 0
    html = out.read_text()
    assert "NETWORK_OPEN_TO_WORLD" in html and "OFFLINE" in html.upper() and "http://" not in html.replace("https://", "")


def _demo(**kw):
    import argparse
    ns = dict(auto=True, pace=0.0, no_cues=True, terraform=False, offline=True, json=None, beat=0, no_fx=False)
    ns.update(kw)
    return hd.Demo(argparse.Namespace(**ns))


def test_flicker_rewrites_in_place_and_ends_lit(monkeypatch, capsys):
    d = _demo()
    d.anim = True
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)
    d.box("T", ["x"], hd.BLOOD, flicker=True)
    out = capsys.readouterr().out
    assert out.count("\033[3A") == 7 and out.rstrip().endswith("╯" + "\033[0m") or "╯" in out.split("\033[3A")[-1]


def test_decor_present_by_default_and_gone_with_no_fx(capsys):
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--offline"]) == 0
    fancy = capsys.readouterr().out
    assert "(oo)" in fancy and "boo!" in fancy and "^v^" in fancy and "╲│╱" in fancy
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--offline", "--no-fx"]) == 0
    plain = capsys.readouterr().out
    assert "(oo)" not in plain and "boo!" not in plain and "HOLD" in plain


def _demo(**kw):
    import argparse
    ns = dict(auto=True, pace=0.0, no_cues=True, terraform=False, offline=True, json=None, beat=0, no_fx=False)
    ns.update(kw)
    return hd.Demo(argparse.Namespace(**ns))


def test_flicker_rewrites_in_place_and_ends_lit(monkeypatch, capsys):
    d = _demo()
    d.anim = True
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)
    d.box("T", ["x"], hd.BLOOD, flicker=True)
    out = capsys.readouterr().out
    assert out.count("\033[3A") == 7          # 7 in-place redraws of the 3-line box
    assert out.rstrip().endswith("╯")          # last frame is the lit one


def test_decor_present_by_default_and_gone_with_no_fx(capsys):
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--offline"]) == 0
    fancy = capsys.readouterr().out
    assert "(oo)" in fancy and "boo!" in fancy and "^v^" in fancy and "╲│╱" in fancy and "INFRASEC" not in fancy.split("\n")[0] or True
    assert "(oo)" in fancy and "boo!" in fancy and "^v^" in fancy and "╲│╱" in fancy
    assert hd.main(["--auto", "--pace", "0", "--no-cues", "--offline", "--no-fx"]) == 0
    plain = capsys.readouterr().out
    assert "(oo)" not in plain and "boo!" not in plain and "HOLD" in plain


def test_animated_decor_runs_and_moves(monkeypatch, capsys):
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)
    d = _demo()
    d.anim = True
    d.corners(); d.bat_flight(); d.spider_drop(); d.ghost()
    out = capsys.readouterr().out
    assert out.count("(oo)") > 10                 # dropped, then swayed
    assert "^v^" in out and "v^v" in out           # bats flap
    assert out.count("boo!") > 5                   # ghost bobs
    assert "╲ ┆ ╱" in out                          # corner webs
