import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import infrasec_explain as ex  # noqa: E402


def test_clip_truncates():
    assert ex.clip("a" * 50, 10).startswith("a" * 10)
    assert ex.clip("short", 10) == "short"


def test_strip_reasoning():
    assert ex.strip_reasoning("<think>x\ny</think>\nHello") == "Hello"


def test_messages_forbid_changing_verdict_and_include_data():
    msgs = ex.build_messages('{"decision":"hold"}', "-a\n+b")
    assert "never change it" in msgs[0]["content"]
    assert '"hold"' in msgs[1]["content"] and "+b" in msgs[1]["content"]


def test_skips_without_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    f = tmp_path / "d.json"
    f.write_text("{}")
    assert ex.main(["--decision", str(f)]) == 0
    assert "skipping" in capsys.readouterr().out


class _Fake(BaseHTTPRequestHandler):
    notes = []

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n))
        if self.path.endswith("/chat/completions"):
            assert self.headers["Authorization"] == "Bearer k"
            self._send({"choices": [{"message": {"content": "<think>t</think>### What changed\nSSH opened"}}]})
        else:
            _Fake.notes.append(payload["body"])
            self._send({"id": 1})

    def log_message(self, *a):
        pass


def test_end_to_end_posts_note(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    f = tmp_path / "d.json"
    f.write_text('{"decision":"hold"}')
    d = tmp_path / "c.diff"
    d.write_text("-10.0.0.0/8\n+0.0.0.0/0")
    for k, v in {
        "NEBIUS_API_KEY": "k", "NEBIUS_MODEL_ID": "nvidia/test", "NEBIUS_BASE_URL": base + "/v1",
        "INFRASEC_TOKEN": "t", "CI_API_V4_URL": base + "/api/v4", "CI_PROJECT_ID": "1",
        "CI_MERGE_REQUEST_IID": "2",
    }.items():
        monkeypatch.setenv(k, v)
    assert ex.main(["--decision", str(f), "--diff", str(d)]) == 0
    srv.shutdown()
    assert len(_Fake.notes) == 1
    assert "advisory only" in _Fake.notes[0] and "SSH opened" in _Fake.notes[0]
    assert "<think>" not in _Fake.notes[0]


def test_model_failure_never_raises(monkeypatch, tmp_path):
    f = tmp_path / "d.json"
    f.write_text("{}")
    monkeypatch.setenv("NEBIUS_API_KEY", "k")
    monkeypatch.setenv("NEBIUS_MODEL_ID", "m")
    monkeypatch.setenv("NEBIUS_BASE_URL", "http://127.0.0.1:1/v1")
    assert ex.main(["--decision", str(f)]) == 0
