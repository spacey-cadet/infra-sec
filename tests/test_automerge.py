import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.infrasec_automerge import main  # noqa: E402

HEAD = "a" * 40


class FakeGitLab:
    def __init__(self, mrs=None, mr=None, message="fix(infrasec): x [infrasec-autofix]", merge_codes=(200,)):
        outer = self
        self.mrs = [{"iid": 1}] if mrs is None else mrs
        self.mr = {"iid": 1, "sha": HEAD, "draft": False, "has_conflicts": False, **(mr or {})}
        self.message, self.codes, self.requests = message, list(merge_codes), []

        class H(BaseHTTPRequestHandler):
            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                if "/repository/commits/" in self.path:
                    self._send(200, {"message": outer.message})
                elif "/merge_requests?" in self.path:
                    self._send(200, outer.mrs)
                else:
                    self._send(200, outer.mr)

            def do_PUT(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.requests.append(("PUT", self.path, json.loads(self.rfile.read(n))))
                self._send(outer.codes.pop(0) if outer.codes else 200, {"state": "merged"})

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v4"

    def puts(self):
        return [r for r in self.requests if r[0] == "PUT"]

    def close(self):
        self.server.shutdown()


def run(gl, **extra):
    env = {"CI_API_V4_URL": gl.url, "CI_PROJECT_ID": "7", "CI_COMMIT_REF_NAME": "demo/open-ssh",
           "CI_COMMIT_SHA": HEAD, "INFRASEC_TOKEN": "tok", **extra}
    try:
        return main(env)
    finally:
        gl.close()


def test_merges_tagged_head_commit_pinned_to_sha():
    gl = FakeGitLab()
    assert run(gl) == 0
    (put,) = gl.puts()
    assert put[1].endswith("/merge_requests/1/merge") and put[2] == {"sha": HEAD}


def test_does_not_merge_human_commit():
    gl = FakeGitLab(message="tweak something")
    assert run(gl) == 0 and gl.puts() == []


def test_does_not_merge_when_head_moved_after_the_pipeline_started():
    gl = FakeGitLab(mr={"sha": "b" * 40})
    assert run(gl) == 0 and gl.puts() == []


def test_does_not_merge_draft_or_conflicted_mr():
    for mr in ({"draft": True}, {"has_conflicts": True}):
        gl = FakeGitLab(mr=mr)
        assert run(gl) == 0 and gl.puts() == []


def test_no_open_mr_or_no_token_is_a_quiet_noop():
    gl = FakeGitLab(mrs=[])
    assert run(gl) == 0 and gl.puts() == []
    gl = FakeGitLab()
    assert run(gl, INFRASEC_TOKEN="") == 0 and gl.requests == []


def test_falls_back_to_merge_when_pipeline_succeeds_on_405():
    gl = FakeGitLab(merge_codes=(405, 200))
    assert run(gl) == 0
    first, second = gl.puts()
    assert first[2] == {"sha": HEAD}
    assert second[2] == {"sha": HEAD, "merge_when_pipeline_succeeds": True}


def test_unreachable_api_never_fails_the_pipeline():
    env = {"CI_API_V4_URL": "http://127.0.0.1:9/api/v4", "CI_PROJECT_ID": "7",
           "CI_COMMIT_REF_NAME": "b", "CI_COMMIT_SHA": HEAD, "INFRASEC_TOKEN": "tok"}
    assert main(env) == 0
