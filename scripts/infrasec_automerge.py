#!/usr/bin/env python3
"""Merge an InfraSec auto-fix merge request once the gate has passed.

GitLab refuses the /merge quick action inside AI workflows, so the merge is done here,
by a deterministic CI job that runs only after every earlier job (including the
InfraSec gate) succeeded.

It merges only when ALL of these hold:
  * the branch has an open merge request,
  * the pipeline's commit is the MR's current head (a later push invalidates it),
  * that head commit's message carries the [infrasec-autofix] tag,
  * the MR is not a draft and has no merge conflicts.

The merge call passes `sha`, so GitLab itself rejects it if the head moved.
Never fails the pipeline: any problem just prints what happened.

Environment:
  INFRASEC_TOKEN   project access token (api scope, Developer role)  [required]
  CI_API_V4_URL, CI_PROJECT_ID, CI_COMMIT_REF_NAME, CI_COMMIT_SHA    [set by GitLab]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TAG = "[infrasec-autofix]"


def _api(method: str, url: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def main(env=None) -> int:
    env = os.environ if env is None else env
    token = env.get("INFRASEC_TOKEN", "")
    if not token:
        print("INFRASEC_TOKEN not set: skipping auto-merge.")
        return 0
    base = f"{env['CI_API_V4_URL']}/projects/{env['CI_PROJECT_ID']}"
    branch, sha = env["CI_COMMIT_REF_NAME"], env["CI_COMMIT_SHA"]
    try:
        mrs = _api("GET", f"{base}/merge_requests?state=opened&source_branch={urllib.parse.quote(branch, safe='')}", token)
        if not mrs:
            print(f"No open merge request for '{branch}': nothing to merge.")
            return 0
        iid = mrs[0]["iid"]
        mr = _api("GET", f"{base}/merge_requests/{iid}", token)
        if mr.get("sha") != sha:
            print(f"Pipeline commit {sha[:8]} is not the MR head {str(mr.get('sha'))[:8]}: not merging.")
            return 0
        if mr.get("draft") or mr.get("work_in_progress"):
            print("MR is a draft: not merging.")
            return 0
        if mr.get("has_conflicts"):
            print("MR has conflicts: a human must resolve them.")
            return 0
        commit = _api("GET", f"{base}/repository/commits/{sha}", token)
        if TAG not in (commit.get("message") or ""):
            print(f"Head commit is not tagged {TAG}: a human must merge this one.")
            return 0
        try:
            _api("PUT", f"{base}/merge_requests/{iid}/merge", token, {"sha": sha})
            print(f"Gate passed. Merged MR !{iid}.")
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 406):
                raise
            # "Pipelines must succeed" is on and this pipeline is still running (it includes
            # this job), so ask GitLab to merge when the pipeline succeeds instead.
            _api("PUT", f"{base}/merge_requests/{iid}/merge", token,
                 {"sha": sha, "merge_when_pipeline_succeeds": True})
            print(f"Queued MR !{iid} to merge when this pipeline succeeds.")
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"Could not auto-merge: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
