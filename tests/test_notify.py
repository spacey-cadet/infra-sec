import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.infrasec_notify import main  # noqa: E402


class FakeGitLab:
    """Tiny stand-in for the GitLab API that records requests."""

    def __init__(self, mrs):
        outer = self
        self.mrs, self.requests = mrs, []

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(("GET", self.path, self.headers.get("PRIVATE-TOKEN"), None))
                self._reply(outer.mrs)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(("POST", self.path, self.headers.get("PRIVATE-TOKEN"),
                                       json.loads(self.rfile.read(length))))
                self._reply({"id": 1})

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v4"

    def close(self):
        self.server.shutdown()


def env_for(gl, **extra):
    env = {"CI_API_V4_URL": gl.url, "CI_PROJECT_ID": "7", "CI_COMMIT_REF_NAME": "demo/open-ssh",
           "CI_PIPELINE_ID": "99", "INFRASEC_TOKEN": "tok", "INFRASEC_FLOW_HANDLE": "@ai-infrasec-autofix"}
    env.update(extra)
    return env


def test_posts_report_and_mentions_flow_on_the_branchs_mr(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("## InfraSec: **HELD**\nNETWORK_OPEN_TO_WORLD")
    gl = FakeGitLab([{"iid": 12}])
    try:
        assert main(env_for(gl), str(report)) == 0
    finally:
        gl.close()
    get, post = gl.requests
    assert "source_branch=demo%2Fopen-ssh" in get[1] and get[2] == "tok"
    assert post[1].endswith("/projects/7/merge_requests/12/notes")
    assert post[3]["body"].startswith("@ai-infrasec-autofix")
    assert "NETWORK_OPEN_TO_WORLD" in post[3]["body"] and "#99" in post[3]["body"]
    assert "Context: project_id=7, merge_request_iid=12, branch=demo/open-ssh" in post[3]["body"]


def test_no_open_mr_posts_nothing_and_does_not_fail(tmp_path):
    gl = FakeGitLab([])
    try:
        assert main(env_for(gl), str(tmp_path / "missing.md")) == 0
    finally:
        gl.close()
    assert [r[0] for r in gl.requests] == ["GET"]


def test_missing_token_or_handle_skips_without_calling_the_api(tmp_path, capsys):
    gl = FakeGitLab([{"iid": 1}])
    try:
        assert main(env_for(gl, INFRASEC_TOKEN=""), str(tmp_path / "r.md")) == 0
    finally:
        gl.close()
    assert gl.requests == [] and "not set" in capsys.readouterr().out


def test_unreachable_api_never_fails_the_pipeline(tmp_path):
    env = {"CI_API_V4_URL": "http://127.0.0.1:9/api/v4", "CI_PROJECT_ID": "7", "CI_COMMIT_REF_NAME": "b",
           "INFRASEC_TOKEN": "tok", "INFRASEC_FLOW_HANDLE": "@f"}
    assert main(env, str(tmp_path / "r.md")) == 0
