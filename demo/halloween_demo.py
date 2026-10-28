#!/usr/bin/env python3
"""InfraSec demo runner with a dark Halloween theme (standard library only).

Everything runs in a temp copy; your repo is never modified. It uses the real code:
the deterministic gate, the Nemotron explain/fix calls (when NEBIUS_API_KEY and
NEBIUS_MODEL_ID are set) and the real fix guardrails. Anything that is NOT live is
labelled on screen ("offline sample", "saved plan"), so the video never pretends.

  python demo/halloween_demo.py                 press Enter between scenes (with narration cues)
  python demo/halloween_demo.py --auto          hands-free, for screen recording (about 1:45 incl. model time at the default --beat 8)
  python demo/halloween_demo.py --auto --no-cues
  python demo/halloween_demo.py --terraform     real `terraform plan` instead of saved plans
  python demo/halloween_demo.py --offline       never call the model
  python demo/halloween_demo.py --json run.json write what happened (for a replay page)
"""
from __future__ import annotations

import argparse
import difflib
import itertools
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import infrasec_explain as ex  # noqa: E402
import infrasec_fix as fx  # noqa: E402

WIDTH = 78
PUMPKIN, PURPLE, GREEN = (255, 117, 24), (176, 102, 255), (57, 255, 20)
BLOOD, BONE, DIM = (255, 55, 80), (232, 226, 210), (130, 120, 150)
COLOR = (sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))) and not os.environ.get("NO_COLOR")

OFFLINE_NOTE = """### What changed
The SSH ingress rule on `aws_security_group.app` was widened from `10.0.0.0/8` to `0.0.0.0/0`, exposing port 22 to the whole internet.
### Why it was held
The evaluator raised `NETWORK_OPEN_TO_WORLD`. The Terraform is valid, so CI alone would have shipped it.
### Rollback plan
Restore `cidr_blocks = ["10.0.0.0/8"]`, apply, then confirm the security group in the console."""

LANTERN = [
    r"       ,/",
    r'     .-"-.',
    r"   .'     '.",
    r"  /   /\  /\  \ ",
    r" |      ^^     |",
    r" |  \/\/\/\/\/ |",
    r"  \  '------'  / ",
    r"   '-._____.-'",
]
FIGLET = [
    r" ___  _  _ ___ ___    _   ___ ___ ___",
    r"|_ _|| \| | __| _ \  /_\ / __| __/ __|",
    r" | | | .` | _||   / / _ \\__ \ _| (__",
    r"|___||_|\_|_| |_|_\/_/ \_\___/___\___|",
]
GHOST = ["    .-.", "   (o o)  boo!", "   | O \\", "    \\   \\", "     `~~~'"]


class Demo:
    def __init__(self, a):
        self.a = a
        self.rec = {"scenes": []}
        self.key, self.model = os.environ.get("NEBIUS_API_KEY"), os.environ.get("NEBIUS_MODEL_ID")
        self.base = os.environ.get("NEBIUS_BASE_URL", ex.DEFAULT_BASE_URL)
        self.live_model = bool(self.key and self.model) and not a.offline
        self.fx = not a.no_fx
        self.anim = COLOR and sys.stdout.isatty() and a.pace > 0 and self.fx

    # ---- theme -----------------------------------------------------------
    def paint(self, rgb, text, bold=False, dim=False):
        if not COLOR:
            return text
        r, g, b = rgb
        pre = ("\033[1m" if bold else "") + ("\033[2m" if dim else "") + f"\033[38;2;{r};{g};{b}m"
        return f"{pre}{text}\033[0m"

    def out(self, text=""):
        print(text, flush=True)

    def typed(self, text, rgb=BONE, bold=False):
        if self.a.pace <= 0 or not COLOR:
            return self.out(self.paint(rgb, text, bold))
        for ch in text:
            sys.stdout.write(self.paint(rgb, ch, bold))
            sys.stdout.flush()
            time.sleep(0.012 * self.a.pace)
        sys.stdout.write("\n")

    def nap(self, lo, hi):
        time.sleep(random.uniform(lo, hi) * min(self.a.pace, 1.5))

    def show_lines(self, make, flicker=False):
        """Print make('on'); with flicker, rewrite in place dim/on/off like a failing candle."""
        first = make("on")
        for ln in first:
            self.out(ln)
        if not (flicker and self.anim):
            return
        n = len(first)
        for style in ("dim", "on", "dim", "off", "on", "dim", "on"):
            self.nap(0.05, 0.13)
            sys.stdout.write(f"\033[{n}A")
            for ln in make(style):
                sys.stdout.write("\033[2K" + ln + "\n")
            sys.stdout.flush()

    def box_lines(self, title, rows, color, style="on"):
        w = WIDTH
        col = tuple(int(x * 0.35) for x in color) if style == "dim" else color
        lines = [self.paint(col, f"╭─ {title} " + "─" * (w - len(title) - 5) + "╮", bold=True)]
        for row in rows:
            text, rgb = (row, BONE) if isinstance(row, str) else row
            rgb = DIM if style == "dim" else rgb
            for part in (textwrap.wrap(text, w - 4) or [""]):
                lines.append(self.paint(col, "│ ") + self.paint(rgb, part.ljust(w - 4)) + self.paint(col, " │"))
        lines.append(self.paint(col, "╰" + "─" * (w - 2) + "╯", bold=True))
        return [""] * len(lines) if style == "off" else lines

    def box(self, title, rows, color, flicker=False):
        self.show_lines(lambda st: self.box_lines(title, rows, color, st), flicker=flicker and self.fx)

    def flicker_text(self, text, rgb=BLOOD):
        dim = tuple(int(x * 0.35) for x in rgb)
        self.show_lines(lambda st: [self.paint(rgb if st == "on" else dim, text, bold=True) if st != "off" else ""], flicker=True)

    # ---- Halloween decor -------------------------------------------------
    def rule(self, color):
        web = "╲│╱" if self.fx else "═══"
        self.out(self.paint(color, web + "═" * (WIDTH - 6) + web, bold=True))

    def lantern_rows(self):
        g = (random.randint(235, 255), random.randint(120, 215), random.randint(20, 70))
        tag = {6: "  AI does the work.", 7: "  Deterministic code decides. A human approves."}
        rows = []
        for i, art in enumerate(LANTERN):
            row = self.paint(g if 3 <= i <= 5 else PUMPKIN, art.ljust(18), bold=True)
            if 2 <= i <= 5:
                row += self.paint(PUMPKIN, FIGLET[i - 2].ljust(42), bold=True)
            elif i in tag:
                row += self.paint(PURPLE, tag[i], bold=True)
            else:
                row += " " * 42
            if i <= 2:  # the spider's thread (column 64)
                row += " " * 4 + self.paint(DIM, "│")
            elif i == 3:  # the spider
                row += self.paint(PURPLE, "/\\(oo)/\\", bold=True)
            rows.append(row)
        return rows

    def banner(self):
        if not self.fx:
            self.typed("INFRASEC", PUMPKIN, bold=True)
            self.typed("  AI does the work. Deterministic code decides. A human approves.", PURPLE, bold=True)
            return
        self.corners()
        self.bat_flight()
        rows = self.lantern_rows()
        for r in rows:
            self.out(r)
        if self.anim:
            for _ in range(16):
                self.nap(0.07, 0.12)
                sys.stdout.write(f"\033[{len(rows)}A")
                for r in self.lantern_rows():
                    sys.stdout.write("\033[2K" + r + "\n")
                sys.stdout.flush()
        self.out(self.paint(DIM, "  --*--  a web of lies, spun by AI. Only the gate may cut it."))

    def corners(self):
        """Cobwebs in the top-left and top-right corners."""
        web = [r"╲ ┆ ╱", r" ╲┆╱ ", r"──*──"]
        for w in web:
            self.out(self.paint(PURPLE, w + " " * (WIDTH - 2 * len(w)) + w, dim=True))

    def spider_drop(self, indent=62, drop=3):
        """A spider lowers itself on a thread, then sways."""
        if not self.fx:
            return

        def frame(h, ind):
            return [self.paint(DIM, " " * (ind + 4) + "│")] * h + [self.paint(PURPLE, " " * ind + "/\\(oo)/\\", bold=True)]

        def redraw(lines, new):
            sys.stdout.write(f"\033[{len(lines)}A")
            for ln in new:
                sys.stdout.write("\033[2K" + ln + "\n")
            sys.stdout.flush()

        shown = frame(1 if self.anim else drop, indent)
        for ln in shown:
            self.out(ln)
        if not self.anim:
            return
        for h in range(2, drop + 1):
            self.nap(0.18, 0.3)
            new = frame(h, indent)
            redraw(shown, new)
            shown = new
        for dx in (1, 2, 3, 2, 1, 0, -1, -2, -3, -2, -1, 0):
            self.nap(0.08, 0.12)
            new = frame(drop, indent + dx)
            redraw(shown, new)
            shown = new

    def bat_flight(self, frames=28):
        """Bats flap across the screen on one line."""
        if not self.fx:
            return

        def line(x, flap):
            buf = [" "] * WIDTH
            for off in (0, 19, 41):
                pos = x - off
                if 0 <= pos < WIDTH - 3:
                    buf[pos:pos + 3] = list("^v^" if flap else "v^v")
            return self.paint(PURPLE, "".join(buf), dim=True)

        if self.anim:
            for k in range(frames):
                sys.stdout.write("\r\033[2K" + line(int(k * (WIDTH + 41) / frames), k % 2 == 0))
                sys.stdout.flush()
                self.nap(0.05, 0.07)
            sys.stdout.write("\r\033[2K")
        self.out(line(60, True))

    def bats(self):
        self.bat_flight(frames=18)

    def ghost(self):
        """A ghost that bobs up and down."""
        if not self.fx:
            return
        high, low = GHOST + [""], [""] + GHOST
        for ln in high:
            self.out(self.paint(BONE, ln, bold=True))
        if self.anim:
            n = len(high)
            for k in range(10):
                self.nap(0.2, 0.28)
                sys.stdout.write(f"\033[{n}A")
                for ln in (low if k % 2 == 0 else high):
                    sys.stdout.write("\033[2K" + self.paint(BONE, ln, bold=True) + "\n")
                sys.stdout.flush()

    def say(self, text):
        if not self.a.no_cues:
            self.out(self.paint(DIM, "  " + text))

    def beat(self, scale=1.0):
        if self.a.auto:
            time.sleep(self.a.beat * scale * self.a.pace)
        else:
            input(self.paint(DIM, "  [Enter] "))

    def scene(self, title, color=PUMPKIN):
        self.out()
        self.rule(color)
        self.typed(f"  {title}", color, bold=True)
        self.rule(color)

    def spin(self, label, fn):
        if not (COLOR and self.a.pace > 0):
            self.out(self.paint(PURPLE, f"  {label}..."))
            return fn()
        box, stop = {}, threading.Event()

        def work():
            try:
                box["v"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["e"] = exc
            stop.set()

        threading.Thread(target=work, daemon=True).start()
        for f in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            if stop.is_set():
                break
            sys.stdout.write("\r" + self.paint(PURPLE, f"  {f} {label}"))
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(label) + 6) + "\r")
        if "e" in box:
            raise box["e"]
        return box["v"]

    def diff(self, old, new):
        for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), "main", "branch", lineterm="", n=1):
            rgb = GREEN if ln.startswith("+") and not ln.startswith("+++") else BLOOD if ln.startswith("-") and not ln.startswith("---") else DIM
            self.out("  " + self.paint(rgb, ln))

    def note(self, text):
        for ln in text.splitlines():
            if ln.startswith("#"):
                self.out(self.paint(PUMPKIN, "  " + ln.lstrip("# ").upper(), bold=True))
            else:
                for part in (textwrap.wrap(ln, WIDTH - 4) or [""]):
                    self.out(self.paint(BONE, "  " + part))

    def log(self, scene, **kw):
        self.rec["scenes"].append({"scene": scene, **kw})

    # ---- helpers ---------------------------------------------------------
    def gate(self, plan: Path, tmp: Path, attempt=0):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "infrasec_decide.py"), "--plan", str(plan),
                        "--ci-status", "pass", "--attempt", str(attempt), "--out-dir", str(tmp)],
                       cwd=ROOT, capture_output=True, text=True)
        return json.loads((tmp / "infrasec-decision.json").read_text())

    def fixture_gate(self, plans_dir, baseline: str):
        """Offline stand-in for terraform: pick a saved plan by whether the file is still more open than main."""
        def check(tf: Path, attempt: int) -> bool:
            still_open = tf.read_text().count('"0.0.0.0/0"') > baseline.count('"0.0.0.0/0"')
            plan = ROOT / "demo" / "plans" / ("ssh_open.json" if still_open else "safe.json")
            return self.gate(plan, plans_dir, attempt)["action"] == "auto_apply"
        return check

    # ---- the show --------------------------------------------------------
    def run(self):
        a = self.a
        tmp = Path(tempfile.mkdtemp(prefix="infrasec-demo-"))
        try:
            return self._run(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _run(self, tmp: Path):
        a = self.a
        work = tmp / "demo-target"
        shutil.copytree(ROOT / "demo-target", work, ignore=shutil.ignore_patterns(".terraform*", "*.tfstate*", "tfplan*"))
        tf = work / "main.tf"
        good = tf.read_text()
        bad = good.replace('"10.0.0.0/8"', '"0.0.0.0/0"')
        if bad == good:
            sys.exit("demo-target/main.tf has no 10.0.0.0/8 rule to open; update the demo.")

        self.banner()
        mode = ("live Nemotron" if self.live_model else "offline samples") + (" + real terraform" if a.terraform else " + saved plans")
        self.out(self.paint(DIM, f"  mode: {mode}"))
        self.beat()

        # 1 ---------------------------------------------------------------
        self.scene("1 · THE CURSED COMMIT  (a one-line change)")
        self.diff(good, bad)
        self.say("AI writes infrastructure fast. This one-line change opens SSH to the internet. It is valid Terraform, so CI alone would ship it.")
        self.log("cursed_commit", diff=list(difflib.unified_diff(good.splitlines(), bad.splitlines(), lineterm="", n=1)))
        self.beat()

        # 2 ---------------------------------------------------------------
        self.scene("2 · THE CRYPT KEEPER  (deterministic gate: no AI in this step)", BLOOD)
        plan, plan_src = ROOT / "demo" / "plans" / "ssh_open.json", "saved plan (demo/plans/ssh_open.json)"
        if a.terraform:
            plan, plan_src = self.real_plan(work, tmp, plan, plan_src)
        tf.write_text(bad)
        decision = self.gate(plan, tmp)
        codes = [f["code"] for f in decision.get("risk_flags", [])]
        action = decision["action"].upper().replace("_", " ")
        rows = [(f"VERDICT: {action}", BLOOD if decision["action"] == "hold" else GREEN),
                (f"plan source: {plan_src}", DIM)]
        rows += [(f"{f['severity']}  {f['code']}  {f['message']}", BONE) for f in decision.get("risk_flags", [])]
        rows.append((f"exit code {2 if decision['action'] == 'hold' else 0}  ·  reproducible, no model involved", DIM))
        self.box("InfraSec gate", rows, BLOOD if decision["action"] == "hold" else GREEN, flicker=decision["action"] == "hold")
        self.say("Deterministic code decides. The AI never does.")
        self.log("gate", action=decision["action"], codes=codes, plan_source=plan_src, flags=decision.get("risk_flags", []))
        self.beat()

        # 3 ---------------------------------------------------------------
        self.scene("3 · THE ORACLE  (NVIDIA Nemotron on Nebius Token Factory)", PURPLE)
        diff_text = "\n".join(difflib.unified_diff(good.splitlines(), bad.splitlines(), lineterm=""))
        note, src = None, "offline sample"
        if self.live_model:
            self.out(self.paint(DIM, f"  endpoint: {self.base}"))
            self.out(self.paint(DIM, f"  model:    {self.model}"))
            try:
                note = self.spin("Summoning Nemotron on Nebius Token Factory",
                                 lambda: ex.call_model(self.base, self.key, self.model,
                                                       ex.build_messages(json.dumps(decision, indent=2), diff_text)))
                src = "live: Nebius Token Factory"
            except Exception as exc:  # noqa: BLE001
                self.flicker_text(f"  Token Factory call failed ({type(exc).__name__}); showing an offline sample.")
        if not note:
            note = OFFLINE_NOTE
        self.out(self.paint(GREEN if src.startswith("live") else PUMPKIN, f"  source: {src}", bold=True))
        self.bats()
        self.note(note)
        self.say("This is Nebius Token Factory and NVIDIA Nemotron. It explains. It advises. It does not change the verdict.")
        self.log("oracle", source=src, model=self.model if src.startswith("live") else None, note=note)
        self.beat()

        # 4 ---------------------------------------------------------------
        self.scene("4 · THE EXORCISM  (Nemotron proposes, the gate decides)", GREEN)
        proposal, psrc = good, "offline sample"
        if self.live_model:
            try:
                proposal = self.spin("Asking Nemotron for a fix", lambda: fx.propose(
                    self.base, self.key, self.model, fx.build_messages(decision, "main.tf", bad, good)))
                psrc = "live: Nebius Token Factory"
                if proposal is None:
                    raise RuntimeError("no usable proposal")
            except Exception as exc:  # noqa: BLE001
                self.out(self.paint(BLOOD, f"  Proposal failed ({exc}); showing an offline sample."))
                proposal, psrc = good, "offline sample"
        self.out(self.paint(GREEN if psrc.startswith("live") else PUMPKIN, f"  proposal source: {psrc}", bold=True))
        self.diff(bad, proposal)
        checks, ok = [], True
        n = fx.changed_lines(bad, proposal)
        same = fx.resource_set(bad) == fx.resource_set(proposal)
        for label, passed in ((".tf file only", True), (f"{n} changed lines (limit {fx.MAX_CHANGED_LINES})", 0 < n <= fx.MAX_CHANGED_LINES),
                              ("same resources, none added or renamed", same)):
            ok = ok and passed
            checks.append((("✔ " if passed else "✘ ") + label, GREEN if passed else BLOOD))
        gate_ok = False
        if ok:
            tf.write_text(proposal)
            check = fx.gate_passes if a.terraform and shutil.which("terraform") else self.fixture_gate(tmp, good)
            gate_ok = check(tf, 0)
            checks.append((("✔ " if gate_ok else "✘ ") + "gate re-check on the patched file: "
                           + ("auto_apply" if gate_ok else "still hold, reverted")
                           + ("" if (a.terraform and shutil.which("terraform")) else "  (saved plan picked by comparing the file with main)"),
                           GREEN if gate_ok else BLOOD))
        self.box("Guardrails, then the gate", checks, GREEN if (ok and gate_ok) else BLOOD, flicker=not (ok and gate_ok))
        self.say("The model proposes. The same deterministic gate verifies. Only then is the fix kept.")
        self.log("exorcism", source=psrc, checks=[c[0] for c in checks], kept=bool(ok and gate_ok),
                 diff=list(difflib.unified_diff(bad.splitlines(), proposal.splitlines(), lineterm="", n=1)))
        self.beat()

        # 5 ---------------------------------------------------------------
        self.scene("5 · THE WARDS  (a bad proposal is discarded)", BLOOD)
        evil = bad.replace('"app"', '"backdoor"') + "".join(f"# extra {i}\n" for i in range(30))
        reasons = []
        if fx.resource_set(evil) != fx.resource_set(bad):
            reasons.append("a resource was renamed")
        if fx.changed_lines(bad, evil) > fx.MAX_CHANGED_LINES:
            reasons.append(f"{fx.changed_lines(bad, evil)} lines changed (limit {fx.MAX_CHANGED_LINES})")
        self.spider_drop()
        self.box("Simulated bad proposal (guardrails are the real code)",
                 [("✘ REJECTED: " + "; ".join(reasons), BLOOD), ("The file is left untouched. A human takes over.", BONE)], BLOOD, flicker=True)
        self.say("A bad fix is discarded, not trusted.")
        self.log("wards", reasons=reasons)
        self.beat()

        # 6 ---------------------------------------------------------------
        self.scene("6 · THE GATEKEEPER  (a human approves production)", PUMPKIN)
        for stage, state, rgb in (("infrasec:decide", "hold on the risky branch", BLOOD), ("infrasec:explain", "Nemotron note on the MR", PURPLE),
                                  ("infrasec:fix", "gate-verified fix committed", GREEN), ("infrasec:automerge", "merged after the gate passes", GREEN),
                                  ("deploy:staging", "automatic", BONE), ("deploy:production", "▶ MANUAL: a person clicks play", PUMPKIN)):
            self.out("  " + self.paint(rgb, f"{stage:<22}") + self.paint(BONE, state))
        self.say("Cut to the real merge request for 5 to 10 seconds: the Nemotron note, the fix commit, the manual production job.")
        self.log("gatekeeper")
        self.beat(1.6)  # room for the real-MR cutaway

        self.scene("INFRASEC  ·  MIT  ·  github.com/spacey-cadet/infra-sec", PURPLE)
        self.say("MIT licensed. Built on Nebius Token Factory and NVIDIA Nemotron. The evaluator is unchanged; the Nemotron explain, fix and guardrails are new.")
        self.ghost()
        self.typed("  Trick: a model proposes. Treat: the gate decides.", PUMPKIN, bold=True)
        self.rec["mode"] = mode
        if a.json:
            Path(a.json).write_text(json.dumps(self.rec, indent=2))
        return 0

    def real_plan(self, work: Path, tmp: Path, fallback, fallback_src):
        if not shutil.which("terraform"):
            self.out(self.paint(PUMPKIN, "  terraform not found; using the saved plan."))
            return fallback, fallback_src
        try:
            (work / "main.tf").write_text((work / "main.tf").read_text().replace('"10.0.0.0/8"', '"0.0.0.0/0"'))
            for cmd in (["terraform", "init", "-input=false", "-backend=false"], ["terraform", "plan", "-input=false", "-out=tfplan"]):
                subprocess.run(cmd, cwd=work, check=True, capture_output=True)
            shown = subprocess.run(["terraform", "show", "-json", "tfplan"], cwd=work, check=True, capture_output=True, text=True)
            (tmp / "plan.json").write_text(shown.stdout)
            return tmp / "plan.json", "real terraform plan"
        except (subprocess.CalledProcessError, OSError):
            self.out(self.paint(PUMPKIN, "  terraform plan failed; using the saved plan."))
            return fallback, fallback_src


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="InfraSec Halloween demo")
    ap.add_argument("--auto", action="store_true", help="no Enter prompts; timed beats for recording")
    ap.add_argument("--pace", type=float, default=1.0, help="speed multiplier for typing and beats (0 = instant)")
    ap.add_argument("--beat", type=float, default=8.0, help="seconds to hold each scene in --auto mode (room to talk)")
    ap.add_argument("--no-fx", action="store_true", help="plain colours: no webs, spiders, lantern or flicker")
    ap.add_argument("--no-cues", action="store_true", help="hide the narration lines")
    ap.add_argument("--terraform", action="store_true", help="run a real terraform plan")
    ap.add_argument("--offline", action="store_true", help="never call the model")
    ap.add_argument("--json", help="write a run record (for a replay page)")
    return Demo(ap.parse_args(argv)).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
