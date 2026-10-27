#!/usr/bin/env python3
"""Suggest infrastructure code for a repository (IAM, OIDC trust, env, packages).

  python scripts/infrasec_suggest.py --root . --repo ORG/REPO

Writes suggested-infra/*.tf, infrasec-suggestions.md and infrasec-suggestions.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.suggest import suggest, to_markdown  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="InfraSec infra-code suggester")
    ap.add_argument("--root", default=".")
    ap.add_argument("--repo", default=None, help="ORG/REPO used to pin the OIDC trust (default: git remote)")
    ap.add_argument("--out", default="suggested-infra")
    ap.add_argument("--report-dir", default=".")
    args = ap.parse_args(argv)

    s = suggest(args.root, args.repo)
    out = Path(args.out)
    if s.files:
        out.mkdir(parents=True, exist_ok=True)
        for name, body in s.files.items():
            (out / name).write_text(body)
    rd = Path(args.report_dir)
    md = to_markdown(s)
    (rd / "infrasec-suggestions.md").write_text(md)
    (rd / "infrasec-suggestions.json").write_text(json.dumps(
        {"repo": s.repo, "findings": [asdict(f) for f in s.findings],
         "usages": [asdict(u) | {"iam": u.iam} for u in s.usages],
         "files": sorted(s.files)}, indent=2))
    print(md)
    return 1 if any(f.severity == "critical" for f in s.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
