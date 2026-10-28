#!/usr/bin/env python3
"""Build site/index.html: a static, self-contained replay of a recorded demo run.

  python demo/halloween_demo.py --auto --pace 0 --json run.json     (set NEBIUS_* for a live run)
  python demo/build_site.py --run run.json --out site/index.html

The page makes no network requests. Model text is inserted with textContent only.
"""
import argparse
import json
from pathlib import Path

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>InfraSec: replay of a recorded run</title><style>
:root{--bg:#0d0a14;--panel:#17122200;--card:#171222;--bone:#e8e2d2;--dim:#8a7fa0;--pump:#ff7518;--purp:#b066ff;--green:#39ff14;--red:#ff3750}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 500px at 80% -10%,#2a1240,transparent),var(--bg);color:var(--bone);font:16px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}h1{margin:0;color:var(--pump);font-size:1.7rem;letter-spacing:.04em}
.tag{color:var(--purp);margin:.2rem 0 1rem}.note{border:1px solid #3a2c55;border-left:4px solid var(--pump);background:var(--card);padding:10px 14px;border-radius:8px;color:var(--dim);font-size:.9rem}
nav{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}button{font:inherit;background:var(--card);color:var(--bone);border:1px solid #3a2c55;border-radius:8px;padding:8px 14px;cursor:pointer}
button:hover,button:focus-visible{border-color:var(--pump);outline:none}.dots{display:flex;gap:6px;align-items:center;margin-left:auto}
.dot{width:10px;height:10px;border-radius:50%;background:#3a2c55;cursor:pointer}.dot.on{background:var(--pump)}
section{background:var(--card);border:1px solid #3a2c55;border-radius:12px;padding:18px}h2{margin:0 0 12px;font-size:1.15rem}
pre{margin:0;overflow-x:auto;background:#0d0a14;border-radius:8px;padding:10px}.add{color:var(--green)}.del{color:var(--red)}.ctx{color:var(--dim)}
.badge{display:inline-block;border-radius:999px;padding:2px 12px;font-weight:700;font-size:.85rem;margin-right:8px}.live{background:#1d4d12;color:var(--green)}.off{background:#4d2a0a;color:var(--pump)}
.verdict{font-size:1.8rem;font-weight:800;margin:4px 0 10px}.hold{color:var(--red)}.ok{color:var(--green)}li{margin:.35rem 0}ul{padding-left:1.1rem}
h4{color:var(--pump);margin:14px 0 4px;text-transform:uppercase;font-size:.9rem}.say{color:var(--dim);margin-top:14px;font-size:.9rem}
.web{position:fixed;top:0;width:150px;height:150px;opacity:.4;pointer-events:none;z-index:0}.web.l{left:0}.web.r{right:0;transform:scaleX(-1)}main{position:relative;z-index:1}.spider{position:fixed;top:0;right:90px;z-index:2;pointer-events:none;transform-origin:top center;animation:sway 4s ease-in-out infinite}.spider i{display:block;width:1px;background:#8a7fa0;margin:0 auto;height:0;animation:drop 2.5s ease-out forwards}.spider b{display:block;font-size:26px;font-weight:400;line-height:1}.lantern{display:inline-block;margin-right:8px;animation:glow 1.8s infinite}.hold{animation:flick 2.4s infinite}.bat{position:fixed;top:70px;left:-40px;font-size:22px;opacity:.7;pointer-events:none;animation:fly 14s linear infinite}.bat.b2{top:140px;animation-duration:19s;animation-delay:4s}.ghost{font-size:48px;text-align:center;margin-top:12px;animation:float 3s ease-in-out infinite}@keyframes drop{to{height:110px}}@keyframes sway{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}}@keyframes glow{0%,100%{filter:drop-shadow(0 0 6px #ff7518)}20%{filter:drop-shadow(0 0 14px #ffb347)}45%{filter:drop-shadow(0 0 3px #ff7518);opacity:.85}70%{filter:drop-shadow(0 0 16px #ffd24d)}}@keyframes flick{0%,18%,22%,62%,100%{opacity:1}20%,60%{opacity:.25}24%{opacity:.6}64%{opacity:.3}}@keyframes fly{to{transform:translate(calc(100vw + 80px),30px)}}@keyframes float{50%{transform:translateY(-12px)}}@media (prefers-reduced-motion:reduce){*{animation:none!important}.spider i{height:110px}}footer{margin-top:28px;color:var(--dim);font-size:.9rem}a{color:var(--purp)}</style></head><body><svg class="web l" viewBox="0 0 100 100" aria-hidden="true" fill="none" stroke="#b9a8d6" stroke-width=".6"><path d="M0 0H100M0 0L95 35M0 0L75 75M0 0L35 95M0 0V100"/><path d="M25 0Q18 18 0 25M50 0Q35 35 0 50M75 0Q53 53 0 75"/></svg><svg class="web r" viewBox="0 0 100 100" aria-hidden="true" fill="none" stroke="#b9a8d6" stroke-width=".6"><path d="M0 0H100M0 0L95 35M0 0L75 75M0 0L35 95M0 0V100"/><path d="M25 0Q18 18 0 25M50 0Q35 35 0 50M75 0Q53 53 0 75"/></svg><div class="spider" aria-hidden="true"><i></i><b>🕷️</b></div><span class="bat" aria-hidden="true">🦇</span><span class="bat b2" aria-hidden="true">🦇</span><main>
<h1><span class="lantern" aria-hidden="true">🎃</span>INFRASEC</h1><p class="tag">AI does the work. Deterministic code decides. A human approves.</p>
<div class="note" id="meta"></div><nav><button id="prev">&larr; Back</button><button id="next">Next &rarr;</button><button id="play">Play</button><span class="dots" id="dots"></span></nav>
<section id="stage" aria-live="polite"></section>
<footer>MIT licensed &middot; <a href="https://github.com/spacey-cadet/infra-sec">github.com/spacey-cadet/infra-sec</a> &middot; Built on Nebius Token Factory and NVIDIA Nemotron.</footer></main>
<script type="application/json" id="run">__RUN__</script><script>
const run=JSON.parse(document.getElementById('run').textContent),S=Object.fromEntries(run.scenes.map(s=>[s.scene,s]));
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
const diff=l=>{const p=el('pre');(l||[]).forEach(x=>p.append(el('div',x[0]=='+'&&x[1]!='+'?'add':x[0]=='-'&&x[1]!='-'?'del':'ctx',x)));return p};
const badge=s=>el('span','badge '+(String(s||'').startsWith('live')?'live':'off'),String(s||'').startsWith('live')?'LIVE: '+s.replace('live: ',''):'OFFLINE SAMPLE');
const say=(a,t)=>{a.append(el('p','say','Narration: '+t))};
const steps=[
['The Cursed Commit','one line, valid Terraform',a=>{a.append(diff(S.cursed_commit.diff));say(a,'CI alone would ship this: it opens SSH to the internet.')}],
['The Crypt Keeper','deterministic gate, no AI',a=>{const g=S.gate,h=g.action=='hold';a.append(el('div','verdict '+(h?'hold':'ok'),h?'HOLD':'AUTO APPLY'));
 const u=el('ul');(g.flags||[]).forEach(f=>u.append(el('li','',f.severity+' '+f.code+': '+f.message)));a.append(u);a.append(el('p','ctx','plan source: '+g.plan_source));say(a,'Deterministic code decides. The AI never does.')}],
['The Oracle','NVIDIA Nemotron on Nebius Token Factory',a=>{const o=S.oracle;a.append(badge(o.source));if(o.model)a.append(el('span','ctx','model: '+o.model));
 String(o.note||'').split('\n').forEach(l=>a.append(l[0]=='#'?el('h4','',l.replace(/^#+\s*/,'')):el('div','',l)));say(a,'It explains and advises. It does not change the verdict.')}],
['The Exorcism','Nemotron proposes, the gate decides',a=>{const x=S.exorcism;a.append(badge(x.source));a.append(diff(x.diff));const u=el('ul');
 x.checks.forEach(c=>u.append(el('li',c[0]=='✔'?'ok':'del',c)));a.append(u);say(a,'Kept only if the deterministic gate approves the patched file.')}],
['The Wards','a bad proposal is discarded',a=>{a.append(el('div','verdict hold','REJECTED'));const u=el('ul');S.wards.reasons.forEach(r=>u.append(el('li','',r)));a.append(u);
 a.append(el('p','ctx','Simulated bad proposal; the guardrails are the real code. The file is left untouched.'))}],
['The Gatekeeper','a human approves production',a=>{[['infrasec:decide','hold on the risky branch'],['infrasec:explain','Nemotron note on the MR'],['infrasec:fix','gate-verified fix committed'],['infrasec:automerge','merged after the gate passes'],['deploy:staging','automatic'],['deploy:production','MANUAL: a person clicks play']]
 .forEach(r=>{const d=el('div','');d.append(el('b','',r[0].padEnd(22,' ')),el('span','',r[1]));d.style.whiteSpace='pre';a.append(d)});a.append(el('div','ghost','👻'))}]];
let i=0,t=null;const st=document.getElementById('stage'),dots=document.getElementById('dots');
steps.forEach((_,k)=>{const d=el('span','dot');d.onclick=()=>go(k);dots.append(d)});
document.getElementById('meta').textContent='Static replay of a recorded run ('+run.mode+'). Not a live system: the labels show which steps called the model for real.';
function go(k){i=Math.max(0,Math.min(steps.length-1,k));st.replaceChildren(el('h2','',(i+1)+' · '+steps[i][0]+' ('+steps[i][1]+')'));steps[i][2](st);[...dots.children].forEach((d,j)=>d.classList.toggle('on',j==i))}
document.getElementById('prev').onclick=()=>go(i-1);document.getElementById('next').onclick=()=>go(i+1);
document.getElementById('play').onclick=e=>{if(t){clearInterval(t);t=null;e.target.textContent='Play';return}e.target.textContent='Pause';t=setInterval(()=>{if(i>=steps.length-1){clearInterval(t);t=null;e.target.textContent='Play'}else go(i+1)},4500)};
addEventListener('keydown',e=>{if(e.key=='ArrowRight')go(i+1);if(e.key=='ArrowLeft')go(i-1)});go(0);
</script></body></html>"""


def build(run: dict) -> str:
    data = json.dumps(run, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__RUN__", data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="site/index.html")
    a = ap.parse_args(argv)
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    run.setdefault("mode", "recorded run")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(run), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
