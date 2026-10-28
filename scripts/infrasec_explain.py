#!/usr/bin/env python3
"""Advisory explanation of an InfraSec decision, written by an NVIDIA Nemotron
model served on Nebius Token Factory.

The verdict (auto_apply / hold) always comes from the deterministic evaluator.
This script only EXPLAINS it: what changed, why it was held, and a rollback
plan. It never changes the verdict and it never fails the pipeline.

Environment:
  NEBIUS_API_KEY    Token Factory API key (skip silently if missing)
  NEBIUS_MODEL_ID   Nemotron model id from the Token Factory catalog
  NEBIUS_BASE_URL   optional, default https://api.tokenfactory.nebius.com/v1
  INFRASEC_TOKEN, CI_API_V4_URL, CI_PROJECT_ID, CI_MERGE_REQUEST_IID
                    used to post the explanation as a merge request note

Usage:
  infrasec_explain.py --decision decision.json [--diff changes.diff]
  infrasec_explain.py --list-models      # print Nemotron model ids to pick from
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
MAX_DIFF_CHARS = 12000
MAX_DECISION_CHARS = 6000

SYSTEM_PROMPT = (
    "You explain infrastructure-risk decisions to a developer reviewing a merge request. "
    "A deterministic evaluator has ALREADY made the decision; you must never change it, "
    "re-score it, or suggest it is wrong. Use only the decision data and the Terraform diff "
    "you are given. Do not invent findings, values or resources. Reply in Markdown with "
    "exactly three short sections: '### What changed', '### Why it was held', "
    "'### Rollback plan'. Keep it under 250 words."
)

NOTE_HEADER = (
    "**Explanation by NVIDIA Nemotron on Nebius Token Factory** "
    "(advisory only; the verdict comes from the deterministic evaluator)"
)


def clip(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def build_messages(decision_text, diff_text):
    user = (
        "Deterministic decision (JSON):\n```json\n"
        + clip(decision_text, MAX_DECISION_CHARS)
        + "\n```\n\nTerraform diff:\n```diff\n"
        + clip(diff_text or "(diff not available)", MAX_DIFF_CHARS)
        + "\n```"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def strip_reasoning(text):
    """Remove <think>...</think> blocks some reasoning models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _request(url, headers, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def call_model(base_url, api_key, model, messages):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 900}
    data = _request(url, headers, body)
    return strip_reasoning(data["choices"][0]["message"]["content"] or "")


def list_models(base_url, api_key):
    url = base_url.rstrip("/") + "/models"
    data = _request(url, {"Authorization": f"Bearer {api_key}"})
    return sorted(m["id"] for m in data.get("data", []))


def post_note(body):
    api = os.environ.get("CI_API_V4_URL")
    project = os.environ.get("CI_PROJECT_ID")
    iid = os.environ.get("CI_MERGE_REQUEST_IID")
    token = os.environ.get("INFRASEC_TOKEN")
    if api and project and token and not iid:
        # Branch pipelines have no CI_MERGE_REQUEST_IID: find the open MR by branch.
        branch = urllib.parse.quote(os.environ.get("CI_COMMIT_REF_NAME", ""), safe="")
        mrs = _request(f"{api}/projects/{project}/merge_requests?state=opened&source_branch={branch}",
                       {"PRIVATE-TOKEN": token})
        iid = str(mrs[0]["iid"]) if mrs else None
    if not (api and project and iid and token):
        print("No merge request context or token; printing only.")
        return False
    url = f"{api}/projects/{project}/merge_requests/{iid}/notes"
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}
    _request(url, headers, {"body": body})
    return True


def get_diff(path):
    if path and os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    target = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    try:
        out = subprocess.run(
            ["git", "diff", f"origin/{target}...HEAD", "--", "*.tf"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout
    except Exception:
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", help="JSON file with the decision API response")
    ap.add_argument("--diff", help="optional text file with the Terraform diff")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args(argv)

    api_key = os.environ.get("NEBIUS_API_KEY")
    base_url = os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("NEBIUS_MODEL_ID")

    try:
        if args.list_models:
            if not api_key:
                print("Set NEBIUS_API_KEY first.")
                return 0
            for mid in list_models(base_url, api_key):
                if "nemotron" in mid.lower() or "nvidia" in mid.lower():
                    print(mid)
            return 0

        if not (api_key and model):
            print("NEBIUS_API_KEY or NEBIUS_MODEL_ID not set; skipping explanation.")
            return 0
        if not args.decision or not os.path.exists(args.decision):
            print("Decision file not found; skipping explanation.")
            return 0

        decision_text = open(args.decision, encoding="utf-8", errors="replace").read()
        messages = build_messages(decision_text, get_diff(args.diff))
        answer = call_model(base_url, api_key, model, messages)
        if not answer:
            print("Model returned no text; skipping.")
            return 0
        note = f"{NOTE_HEADER}\n\n{answer}"
        print(note)
        post_note(note)
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        # Advisory step: never break the pipeline.
        print(f"Explanation skipped: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
