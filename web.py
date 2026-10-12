"""
Web UI for OpsPilot.   Run:  python web.py     then open http://localhost:5051
(The sandbox must also be running: python app.py --reset)
"""
import asyncio
import json
import threading

import yaml
from flask import Response, jsonify, request

from agent import approval, config, memory, reporter
from agent.llm_pool import pool

from app import app 

STATE = {"running": False, "lines": [], "pending": None, "answer": None, "result": None}
_evt = threading.Event()
_CTRL = {"loop": None, "task": None}


# ---- send agent output and questions to the web page instead of the terminal ----
def _say(self, text=""):
    print(text, flush=True)
    STATE["lines"].append(str(text))


def _ask(question):
    STATE["pending"] = {"type": "question", "text": question}
    _evt.clear()
    _evt.wait()
    ans = STATE["answer"] or ""
    STATE["pending"] = None
    return ans


def _approve(step, facts, auto_approve):
    shown = {k: v for k, v in facts.items() if k in ("vendor", "invoice_number", "amount", "due_date")}
    if auto_approve:
        return True
    STATE["pending"] = {"type": "approval", "text": step["goal"], "facts": shown or facts}
    _evt.clear()
    _evt.wait()
    ok = STATE["answer"] == "yes"
    STATE["pending"] = None
    return ok


reporter.RunLog.say = _say
approval.ask_human = _ask
approval.approve_write = _approve


def _worker(task, auto):
    from agent.runner import run_task

    async def main():
        _CTRL["loop"] = asyncio.get_running_loop()
        _CTRL["task"] = asyncio.ensure_future(run_task(task, auto_approve=auto))
        return await _CTRL["task"]

    try:
        STATE["result"] = asyncio.run(main())
    except asyncio.CancelledError:
        STATE["lines"].append("Stopped by user. Nothing further was changed.")
        STATE["result"] = {"status": "STOPPED", "verdict": "NOT COMPLETED", "facts": {}}
    except Exception as e:  # noqa: BLE001
        STATE["lines"].append(f"ERROR: {e}")
        STATE["result"] = {"status": "ERROR", "verdict": "NONE", "facts": {}}
    finally:
        _CTRL["loop"] = _CTRL["task"] = None
        STATE["running"] = False


@app.post("/api/run")
def api_run():
    if STATE["running"]:
        return jsonify(error="A run is already in progress"), 409
    body = request.get_json(force=True)
    task = (body.get("task") or "").strip()
    if not task:
        return jsonify(error="Task is empty"), 400
    STATE.update(running=True, lines=[], pending=None, answer=None, result=None)
    threading.Thread(target=_worker, args=(task, bool(body.get("auto"))), daemon=True).start()
    return jsonify(ok=True)

@app.post("/api/stop")
def api_stop():
    loop, task = _CTRL["loop"], _CTRL["task"]
    if not STATE["running"] or loop is None or task is None:
        return jsonify(ok=True)
    STATE["pending"] = None
    STATE["answer"] = "no"                       # if it was waiting on an approval, this rejects it
    loop.call_soon_threadsafe(task.cancel)       # cancel the run
    _evt.set()                                   # wake the agent if it is waiting on you
    return jsonify(ok=True)

@app.post("/api/answer")
def api_answer():
    STATE["answer"] = (request.get_json(force=True).get("answer") or "").strip()
    _evt.set()
    return jsonify(ok=True)


@app.get("/api/state")
def api_state():
    return jsonify(running=STATE["running"], lines=STATE["lines"], pending=STATE["pending"],
                   result=STATE["result"], models=pool.status())


@app.get("/api/tasks")
def api_tasks():
    return jsonify(yaml.safe_load((config.ROOT / "tasks.yaml").read_text())["tasks"])


@app.get("/api/runs")
def api_runs():
    if not config.RUNS_DIR.exists():
        return jsonify([])
    dirs = sorted([d.name for d in config.RUNS_DIR.iterdir() if (d / "report.md").exists()], reverse=True)
    return jsonify(dirs[:20])


@app.get("/api/runs/<run_id>")
def api_run_report(run_id):
    f = config.RUNS_DIR / run_id / "report.md"
    if "/" in run_id or ".." in run_id or not f.exists():
        return "Not found", 404
    return Response(f.read_text(), mimetype="text/plain")


@app.post("/api/reset-erp")
def api_reset_erp():
    config.ERP_FILE.write_text(json.dumps({"bills": []}, indent=2))
    return jsonify(ok=True)


@app.post("/api/clear-lessons")
def api_clear_lessons():
    memory.clear_lessons()
    return jsonify(ok=True)


@app.get("/agent")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>OpsPilot</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0d17;--panel:#12152a;--card:#181c34;--line:#262b4d;--txt:#e8eaf8;--mut:#8a90b8;--acc:#7c8cff;--acc2:#b07cff;--ok:#3ecf8e;--bad:#ff6b6b;--warn:#ffc857}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 60% -10%,#1b1f45 0%,var(--bg) 60%);color:var(--txt);font-family:Inter,system-ui,sans-serif;height:100vh;overflow:hidden}
.app{display:grid;grid-template-columns:270px 1fr;height:100vh}
@media(max-width:800px){.app{grid-template-columns:1fr}.side{display:none}}
.side{background:var(--panel);border-right:1px solid var(--line);padding:18px;overflow:auto}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;margin-bottom:16px}
.logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--acc2));display:grid;place-items:center;font-size:16px}
.side h3{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 8px}
.newbtn{width:100%;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;border:0;border-radius:10px;padding:10px;font-weight:600;cursor:pointer}
.model{display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;color:var(--txt)}
.model small{color:var(--mut)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:7px}
.run{padding:6px 8px;border-radius:8px;cursor:pointer;color:var(--mut);font-size:12.5px}
.run:hover{background:var(--card);color:var(--txt)}
.tool{display:block;width:100%;text-align:left;background:transparent;border:1px solid var(--line);color:var(--mut);border-radius:8px;padding:7px 10px;margin-bottom:6px;cursor:pointer;font-size:12.5px;text-decoration:none}
.tool:hover{color:var(--txt);border-color:var(--acc)}
.chat{display:flex;flex-direction:column;height:100vh}
.top{display:flex;justify-content:space-between;align-items:center;padding:14px 24px;border-bottom:1px solid var(--line)}
.pill{display:inline-block;padding:3px 11px;border-radius:99px;font-size:12px;font-weight:700}
.p-idle{background:#2a2a3d;color:var(--mut)}.p-run{background:#1b2a4d;color:var(--acc)}
.p-ok{background:#12382a;color:var(--ok)}.p-bad{background:#3b1a1a;color:var(--bad)}.p-warn{background:#3b3315;color:var(--warn)}
#feed{flex:1;overflow:auto;padding:24px 0}
.wrap{max-width:820px;margin:0 auto;padding:0 20px}
.hero{text-align:center;margin-top:5vh}
.hero .logo{width:60px;height:60px;font-size:30px;margin:0 auto 16px;border-radius:18px}
.hero h1{font-size:30px;margin:0 0 8px}
.hero p{color:var(--mut);margin:0 0 26px}
.chips{display:grid;grid-template-columns:1fr 1fr;gap:10px;text-align:left}
@media(max-width:700px){.chips{grid-template-columns:1fr}}
.chip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 14px;cursor:pointer;font-size:13.5px;color:var(--txt);line-height:1.4}
.chip:hover{border-color:var(--acc);transform:translateY(-1px)}
.chip b{display:block;color:var(--acc);font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.msg{display:flex;gap:12px;margin-bottom:22px}
.msg.user{justify-content:flex-end}
.bubble{background:linear-gradient(135deg,#3a4bd6,#7a4bd6);padding:11px 15px;border-radius:16px 16px 4px 16px;max-width:80%;line-height:1.5}
.av{width:32px;height:32px;border-radius:10px;flex:none;background:linear-gradient(135deg,var(--acc),var(--acc2));display:grid;place-items:center}
.agent{flex:1;min-width:0}
.status{display:flex;align-items:center;gap:8px;font-weight:600;margin:4px 0 10px}
.spin{width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--acc);border-radius:50%;animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.log{background:#0a0c18;border:1px solid var(--line);border-radius:12px;padding:12px 14px;max-height:300px;overflow:auto;font:12.5px/1.6 ui-monospace,Menlo,monospace}
.log div{white-space:pre-wrap}
.l-step{color:var(--acc);font-weight:700;margin-top:6px}
.l-good{color:var(--ok)}.l-bad{color:var(--bad)}.l-dim{color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:12px}
.card.ask{border-color:var(--warn)}
.card h4{margin:0 0 8px;font-size:13px;color:var(--warn);text-transform:uppercase;letter-spacing:.06em}
.kv{display:grid;grid-template-columns:130px 1fr;gap:4px 10px;font-size:13.5px;margin:8px 0}
.kv span:nth-child(odd){color:var(--mut)}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button.b{border:0;border-radius:9px;padding:8px 16px;font-weight:600;cursor:pointer;color:#fff;background:var(--acc)}
button.ok{background:var(--ok);color:#06210f}button.no{background:var(--bad)}button.gh{background:transparent;border:1px solid var(--line);color:var(--mut)}
input.t{width:100%;padding:9px 11px;border-radius:9px;border:1px solid var(--line);background:#0a0c18;color:var(--txt);margin-top:8px}
.composer{padding:14px 0 22px;border-top:1px solid var(--line);background:rgba(11,13,23,.7)}
.box{display:flex;gap:10px;align-items:flex-end;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:10px 12px}
.box:focus-within{border-color:var(--acc)}
textarea{flex:1;background:transparent;border:0;outline:0;color:var(--txt);font:inherit;resize:none;max-height:140px;min-height:24px}
.send{width:38px;height:38px;border-radius:11px;border:0;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;font-size:18px;cursor:pointer}
.send:disabled{opacity:.35;cursor:not-allowed}
.stopbtn{width:38px;height:38px;border-radius:11px;border:0;background:var(--bad);color:#fff;font-size:15px;cursor:pointer;display:none}
.opts{display:flex;justify-content:space-between;color:var(--mut);font-size:12px;margin-top:8px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;place-items:center;z-index:9}
#modal .in{background:var(--card);border:1px solid var(--line);border-radius:14px;width:min(820px,92vw);max-height:84vh;display:flex;flex-direction:column}
#modal .hd{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
#modal pre{margin:0;padding:16px;overflow:auto;font-size:12px;white-space:pre-wrap}
</style></head><body>
<div class="app">
<aside class="side">
  <div class="brand"><div class="logo">&#10022;</div>OpsPilot</div>
  <button class="newbtn" onclick="location.reload()">+ New task</button>
  <h3>Models (fallback order)</h3><div id="models"></div>
  <h3>Past runs</h3><div id="runs"></div>
  <h3>Tools</h3>
  <button class="tool" onclick="tool('/api/reset-erp','ERP reset')">Reset ERP</button>
  <button class="tool" onclick="tool('/api/clear-lessons','Lessons cleared')">Clear lessons</button>
  <a class="tool" href="/erp" target="_blank">Open ERP &#8599;</a>
  <a class="tool" href="/vendor" target="_blank">Open Vendor Portal &#8599;</a>
</aside>
<main class="chat">
  <div class="top"><div style="color:var(--mut);font-size:13px">Autonomous AI task worker</div><span id="status" class="pill p-idle">idle</span></div>
  <div id="feed"><div class="wrap" id="msgs">
    <div class="hero" id="hero">
      <div class="logo">&#10022;</div>
      <h1>What should I get done?</h1>
      <p>Describe a company task. I will plan it, do it in the browser, and verify the result.</p>
      <div class="chips" id="chips"></div>
    </div>
  </div></div>
  <div class="composer"><div class="wrap">
    <div class="box"><textarea id="task" rows="1" placeholder="Message OpsPilot..."></textarea>
    <button class="send" id="send" onclick="send()">&#10148;</button>
    <button class="stopbtn" id="stopbtn" title="Stop the task" onclick="stopRun()">&#9632;</button></div>
    <div class="opts"><label><input type="checkbox" id="auto"> auto-approve writes (testing only)</label><span>Enter to send &middot; Shift+Enter for new line</span></div>
  </div></div>
</main></div>
<div id="modal" onclick="if(event.target===this)closeModal()"><div class="in"><div class="hd"><b>Run report</b><button class="b gh" onclick="closeModal()">Close</button></div><pre id="rep"></pre></div></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let active=false,lastAsk='',resultShown=false;
async function post(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})})}
async function tool(u,msg){await post(u);alert(msg)}
function closeModal(){$('modal').style.display='none'}
async function showRun(id){$('rep').textContent=await (await fetch('/api/runs/'+id)).text();$('modal').style.display='grid'}
function scrollDown(){const f=$('feed');f.scrollTop=f.scrollHeight}
function addUser(t){$('msgs').insertAdjacentHTML('beforeend',`<div class="msg user"><div class="bubble">${esc(t)}</div></div>`)}
function addAgent(){
  const old=$('agent');if(old)old.removeAttribute('id');
  $('msgs').insertAdjacentHTML('beforeend',`<div class="msg" id="agent"><div class="av">&#10022;</div><div class="agent">
    <div class="status" id="aStatus"><div class="spin"></div>Working on it...</div>
    <div class="log" id="aLog"></div><div id="aAsk"></div><div id="aRes"></div></div></div>`);
  lastAsk='';resultShown=false;scrollDown();
}
async function send(){
  const t=$('task').value.trim();if(!t||active)return;
  const r=await post('/api/run',{task:t,auto:$('auto').checked});
  if(!r.ok){alert((await r.json()).error);return}
  $('task').value='';$('hero').style.display='none';
  addUser(t);addAgent();active=true;
}
async function stopRun(){await post('/api/stop');$('aAsk').innerHTML='';lastAsk=''}
function answer(a){post('/api/answer',{answer:a});$('aAsk').innerHTML='';lastAsk=''}
function logLine(l){
  let c='';
  if(/^\[Step/.test(l))c='l-step';
  else if(/PASS|VERIFIED|learned|A new bill/.test(l))c='l-good';
  else if(/FAIL|ERROR|not accepted|unavailable|Stopped/.test(l))c='l-bad';
  else if(/observed|attempt|Using model/.test(l))c='';
  else c='l-dim';
  return `<div class="${c}">${esc(l)}</div>`;
}
function renderAsk(p){
  const key=JSON.stringify(p);if(key===lastAsk)return;lastAsk=key;
  let h='<div class="card ask"><h4>'+(p.type==='approval'?'Approval needed':'The agent needs your input')+'</h4><div>'+esc(p.text)+'</div>';
  if(p.facts)h+='<div class="kv">'+Object.entries(p.facts).map(([k,v])=>`<span>${esc(k)}</span><span>${esc(v)}</span>`).join('')+'</div>';
  if(p.type==='approval')h+='<div class="row"><button class="b ok" onclick="answer(\'yes\')">Approve</button><button class="b no" onclick="answer(\'no\')">Reject</button></div>';
  else h+='<input class="t" id="mans" placeholder="Type your answer"><div class="row"><button class="b" onclick="answer($(\'mans\').value)">Send</button></div>';
  $('aAsk').innerHTML=h+'</div>';scrollDown();
}
function renderResult(r){
  if(resultShown)return;resultShown=true;
  const v=r.verdict||'NONE',cls=v==='VERIFIED'?'p-ok':(v==='FAILED'||v==='ERROR')?'p-bad':'p-warn';
  const f=r.facts||{};
  let h=`<div class="card"><span class="pill ${cls}">${esc(v)}</span> <span style="color:var(--mut);font-size:13px;margin-left:6px">status: ${esc(r.status)}</span>`;
  if(Object.keys(f).length)h+='<div class="kv">'+Object.entries(f).map(([k,x])=>`<span>${esc(k)}</span><span>${esc(x)}</span>`).join('')+'</div>';
  h+='<div class="row">';
  if(r.run_id)h+=`<button class="b" onclick="showRun('${r.run_id}')">View report</button>`;
  h+='<a class="tool" style="width:auto;display:inline-block;margin:0" href="/erp" target="_blank">Open ERP &#8599;</a></div></div>';
  $('aRes').innerHTML=h;scrollDown();
}
async function loadRuns(){
  const l=await (await fetch('/api/runs')).json();
  $('runs').innerHTML=l.map(i=>`<div class="run" onclick="showRun('${i}')">${i}</div>`).join('')||'<span style="color:var(--mut);font-size:12.5px">none yet</span>';
}
async function poll(){
  let s;try{s=await (await fetch('/api/state')).json()}catch(e){return}
  $('models').innerHTML=s.models.map(m=>`<div class="model"><span><span class="dot" style="background:${m.cooldown_s?'var(--bad)':'var(--ok)'}"></span>${esc(m.model)}</span><small>${m.cooldown_s?'cooling '+m.cooldown_s+'s':'ready'}</small></div>`).join('');
  if(s.running&&!active){$('hero').style.display='none';addAgent();active=true}
  $('send').style.display=s.running?'none':'block';
  $('stopbtn').style.display=s.running?'block':'none';
  $('status').textContent=s.running?'running':'idle';$('status').className='pill '+(s.running?'p-run':'p-idle');
  if(!active||!$('aLog'))return;
  const log=$('aLog'),bottom=log.scrollTop+log.clientHeight>=log.scrollHeight-20;
  log.innerHTML=s.lines.filter(l=>String(l).trim()).map(logLine).join('');
  if(bottom)log.scrollTop=log.scrollHeight;
  if(s.pending)renderAsk(s.pending);else if(lastAsk){$('aAsk').innerHTML='';lastAsk=''}
  if(!s.running&&s.result){
    $('aStatus').innerHTML=s.result.status==='STOPPED'?'Stopped':'Finished';
    renderResult(s.result);active=false;loadRuns();
  }
}
(async()=>{
  const t=await (await fetch('/api/tasks')).json();
  $('chips').innerHTML=t.map(x=>`<div class="chip" data-t="${esc(x)}"><b>Demo task</b>${esc(x.length>110?x.slice(0,110)+'...':x)}</div>`).join('');
  document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{$('task').value=c.dataset.t;$('task').focus()});
  $('task').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
  loadRuns();setInterval(poll,1000);poll();
})();
</script></body></html>"""

if __name__ == "__main__":
    app.run(port=5050, debug=False, threaded=True)