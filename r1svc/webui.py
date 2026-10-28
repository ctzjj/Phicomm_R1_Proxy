""":9000 API + WebUI:状态页 / 日志 / 设置页;NLU/ASR 端点(复用 app.py 契约)。"""
from __future__ import annotations

from fastapi import FastAPI, Request, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

import r1svc.config as config
import r1svc.state as statemod


def nlu_recognize(data: bytes):
    import r1svc.nlu as nlu_mod
    return nlu_mod.recognize_ogg(data)


def build(rt: config.Runtime) -> FastAPI:
    app = FastAPI(title="r1svc")
    st = statemod.STATE

    @app.get("/health")
    async def health():
        import r1svc.asr_engine.sherpa_asr as _sa
        return {"asr": _sa.asr_label() or "sensevoice cpu",
                "asr_ready": _sa.asr_ready(),
                "lexicon": 0}

    @app.post("/asr/text-mode")
    async def asr_text_mode(req: Request):
        body = await req.body()
        if not body:
            raise HTTPException(400, "no audio")
        import r1svc.nlu as _n
        import r1svc.asr_engine.sherpa_asr as _sa
        with _sa.asr_lock():
            t = _n.asr_text(_n.decode_to_wav16k(body))
        return {"text": t}

    @app.post("/asr")
    async def asr(file: UploadFile | None = None):
        if file is None:
            raise HTTPException(400, "no file")
        data = await file.read()
        import r1svc.nlu as _n
        import r1svc.asr_engine.sherpa_asr as _sa
        with _sa.asr_lock():
            t = _n.asr_text(_n.decode_to_wav16k(data))
        return {"text": t}

    @app.post("/slu")
    async def slu(req: Request):
        from r1svc.asr_engine import slu_ernie
        if req.headers.get("content-type", "").startswith("application/json"):
            b = await req.json()
            text = (b or {}).get("text") or ""
        else:
            text = (await req.body()).decode("utf-8", "replace")
        out = slu_ernie.get_slu()(text)
        return JSONResponse(out)

    @app.post("/nlu")
    async def nlu_endpoint(file: UploadFile | None = None):
        if file is None:
            raise HTTPException(400, "no file")
        data = await file.read()
        out = nlu_recognize(data)
        if not isinstance(out, dict):
            return PlainTextResponse(str(out or ""))
        return JSONResponse(out)

    @app.get("/api/status")
    async def api_status():
        import r1svc.asr_engine.sherpa_asr as _sa
        info = st.inspect()
        api = rt.get("llm_api") or ""
        chat_on = bool(rt.get("llm_chat"))
        if not chat_on:
            llm = "off"
        elif api:
            llm = "llama.cpp " + api
        else:
            llm = "builtin"
        return {"nlu_mode": rt["nlu_mode"],
                "llm": llm,
                "llm_chat": chat_on,
                "llm_api": api,
                "web_search": bool(rt.get("web_search")),
                "asr_ready": _sa.asr_ready(),
                "asr_label": _sa.asr_label(),
                "uptime_s": info.get("uptime_s", 0),
                "intercepts": info.get("intercepts", 0),
                "sessions": info.get("sessions", 0),
                "configs": {k: rt[k] for k in
                            ("listen_asr", "listen_api", "listen_bind",
                             "media_base", "upstream", "dns",
                             "nlu_mode", "audio_dir", "dump_dir")}}

    @app.get("/api/config")
    async def api_get_config():
        return JSONResponse(rt.snapshot())

    @app.post("/api/config")
    async def api_post_config(request: Request):
        try:
            patch = await request.json()
        except Exception:
            raise HTTPException(400, "bad json")
        if not isinstance(patch, dict):
            raise HTTPException(400, "must be json object")
        known = {k: v for k, v in patch.items() if k in config.EDITABLE}
        if not known:
            raise HTTPException(400, "no known keys")
        rt.update(known)
        if "llm_chat" in known or "llm_api" in known or "web_search" in known:
            from r1svc.asr_engine import qa_llm
            if "llm_chat" in known:
                qa_llm.set_enabled(bool(known["llm_chat"]))
                st.log("[llm] chat -> " + ("on" if known["llm_chat"] else "off"))
            if "llm_api" in known:
                qa_llm.set_api(known["llm_api"])
                st.log("[llm] api -> " + (str(known["llm_api"]) or "(empty)"))
            if "web_search" in known:
                qa_llm.set_web_search(bool(known["web_search"]))
                st.log("[llm] web search -> " +
                       ("on" if known["web_search"] else "off"))
        return {"ok": True, "applied": known}

    @app.get("/logs")
    async def api_logs(after: int = 0):
        items = st.logs(200)
        return {"items": [i for i in items if i["seq"] > after]}

    @app.get("/settings")
    async def settings():
        return HTMLResponse(_SETTINGS_PAGE)

    @app.get("/")
    async def index():
        return HTMLResponse(_STATUS_PAGE)

    return app


_STATUS_PAGE = """<!doctype html><html><meta charset=utf-8>
<title>r1svc</title><style>
body{font-family:Consolas,monospace;background:#111;color:#ccc;margin:24px}
.card{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:16px}
pre{white-space:pre-wrap;color:#9c9;font-size:12px}
a{color:#6cf}</style><body>
<div class=card><b>r1svc</b> status <a href=/settings>settings</a></div>
<div class=card id=status>loading…</div>
<div class=card>logs<pre id=logs>loading…</pre></div>
<script>
function upd(){fetch('/api/status').then(r=>r.json()).then(j=>{
 document.getElementById('status').textContent=JSON.stringify(j,null,2)});
 fetch('/logs?after=0').then(r=>r.json()).then(j=>{
  document.getElementById('logs').textContent=
   j.items.map(i=>i.t+' '+i.msg).join('\\n')||'(empty)');});
upd();setInterval(upd,3000);</script></body></html>"""

_SETTINGS_PAGE = """<!doctype html><html><meta charset=utf-8>
<title>r1svc settings</title><style>
body{font-family:Consolas,monospace;background:#111;color:#ccc;margin:24px}
div.f{margin-bottom:8px} input{background:#000;color:#ccc;border:1px solid #444;padding:4px;width:60%}
select{background:#000;color:#ccc;border:1px solid #444}
button{background:#333;color:#eee;border:1px solid #555;padding:6px 14px;margin-top:12px}
</style><body>
<div><b>settings</b> — <a href=/>back</a></div><div id=body></div>
<button onclick=save()>save</button><div id=msg></div>
<script>
const ED=['listen_asr','listen_api','listen_bind','upstream','dns','media_base','nlu_mode','nlu_key','llm_chat','llm_api','web_search','dump_dir','audio_dir','music_enabled','music_limit'];
const SEL={nlu_mode:['cloud','custom']};
fetch('/api/config').then(r=>r.json()).then(j=>{
 const b=document.getElementById('body');
 ED.forEach(k=>{
  const d=document.createElement('div');d.className='f';d.dataset.row=k;
  const lab=document.createElement('span');lab.textContent=k+'  ';
  d.appendChild(lab);
  if(SEL[k]){
   const s=document.createElement('select');s.dataset.k=k;
   SEL[k].forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;
    if(String(j[k])===v)o.selected=true;s.appendChild(o);});
   d.appendChild(s);}else if(k==='web_search'||k==='llm_chat'){
   const cb=document.createElement('input');cb.type='checkbox';cb.dataset.k=k;
   cb.checked=!!j[k];cb.style.width='auto';d.appendChild(cb);
   if(k==='web_search'){
    const note=document.createElement('span');
    note.textContent=' 仅外部接口可用;勾选后可能导致回复超时';
    note.style.color='#c96';d.appendChild(note);}
   if(k==='llm_chat'){
    const note=document.createElement('span');
    note.textContent=' 关=播报"聊天服务异常,请稍后再试"';
    note.style.color='#c96';d.appendChild(note);}}else{
   const i=document.createElement('input');i.dataset.k=k;i.value=j[k]??'';
   if(k==='llm_api')i.placeholder='空=内置模型;填外部 llama.cpp 地址如 http://127.0.0.1:12345';
   if(k==='llm_api')i.addEventListener('input',syncWS);
   d.appendChild(i);}
  b.appendChild(d);});
 syncWS();});
function syncWS(){
 const api=document.querySelector('[data-k=llm_api]');
 const row=document.querySelector('[data-row=web_search]');
 if(!api||!row)return;
 const on=api.value.trim()!=='';
 row.style.display=on?'':'none';
 if(!on){const cb=row.querySelector('input');if(cb)cb.checked=false;}}
function save(){const patch={};
 document.querySelectorAll('[data-k]').forEach(e=>{
  patch[e.dataset.k]=(e.type==='checkbox')?e.checked:e.value});
 fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(patch)}).then(r=>r.json()).then(j=>{
  document.getElementById('msg').textContent=JSON.stringify(j)});}
</script></body></html>"""


def serve(rt: config.Runtime) -> FastAPI:
    return build(rt)


def create_app() -> FastAPI:
    """--factory 入口:直接跑 :9000 用(uvicorn r1svc.webui:create_app --factory)。"""
    import json
    from pathlib import Path
    from r1svc.config import Config, DEFAULTS, Runtime
    cfg_path = Path("data/config.json")
    d = dict(DEFAULTS)
    if cfg_path.exists():
        d.update(json.loads(cfg_path.read_text(encoding="utf-8")))
    return build(Runtime(Config.model_validate(d), cfg_path))
