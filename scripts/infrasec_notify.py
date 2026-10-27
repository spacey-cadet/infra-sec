#!/usr/bin/env python3
"""Post the InfraSec report on the merge request and mention the Duo flow.

Runs from the pipeline's `.post` stage when a job failed. Mentioning the flow in a
comment is the documented way to trigger a custom flow, so this makes the hands-off
loop independent of the project's "pipeline failed" trigger setting.

Environment:
  INFRASEC_TOKEN        project access token (api scope, Developer role)  [required]
  INFRASEC_FLOW_HANDLE  the @handle GitLab autocompletes for the flow     [required]
  CI_API_V4_URL, CI_PROJECT_ID, CI_COMMIT_REF_NAME, CI_PIPELINE_ID        [set by GitLab]

Never fails the pipeline: a missing token or MR just prints what to do.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _api(method: str, url: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def main(env=None, report_path: str = "infrasec-report.md") -> int:
    env = os.environ if env is None else env
    token, handle = env.get("INFRASEC_TOKEN", ""), env.get("INFRASEC_FLOW_HANDLE", "")
    if not token or not handle:
        print("INFRASEC_TOKEN / INFRASEC_FLOW_HANDLE not set: skipping the MR comment.\n"
              "Set both CI/CD variables to make the auto-fix loop hands-off.")
        return 0
    base = f"{env['CI_API_V4_URL']}/projects/{env['CI_PROJECT_ID']}"
    branch = env["CI_COMMIT_REF_NAME"]
    try:
        mrs = _api("GET", f"{base}/merge_requests?state=opened&source_branch={urllib.parse.quote(branch, safe='')}", token)
        if not mrs:
            print(f"No open merge request for branch '{branch}'. Open one and the next push will notify the flow.")
            return 0
        iid = mrs[0]["iid"]
        target = mrs[0].get("target_branch") or env.get("CI_DEFAULT_BRANCH", "main")
        report = Path(report_path).read_text() if Path(report_path).exists() else "(no InfraSec report found)"
        body = (f"{handle} InfraSec held this change (pipeline #{env.get('CI_PIPELINE_ID', '?')}). "
                "Follow your instructions: explain why it did not pass, and fix it if every finding is auto-fixable.\n\n"
                f"Context: project_id={env['CI_PROJECT_ID']}, merge_request_iid={iid}, branch={branch}, target_branch={target}\n\n" + report)
        _api("POST", f"{base}/merge_requests/{iid}/notes", token, {"body": body})
        print(f"Posted the report and mentioned {handle} on MR !{iid}.")
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"Could not notify the flow: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
