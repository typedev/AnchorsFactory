"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const REDUCED = matchMedia("(prefers-reduced-motion:reduce)").matches;
const LH = 20, PAD = 14;                     // editor line-height / padding (match app.css)
let META = null, VIEW = {glyphs:{}}, SELECTED = null, EDITOR = null, GLYPH_FILTER = "", HL_ANCHOR = null;
const lastPos = {};                          // glyph -> {anchor -> {x,y}} for tweening

const $ = s => document.querySelector(s);
const el = (n, a={}) => { const e=document.createElementNS(SVGNS,n); for(const k in a) e.setAttribute(k,a[k]); return e; };
const round = v => Math.round(v*10)/10;
const escapeHtml = s => String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const debounce = (fn, ms) => { let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), ms);}; };

async function boot(){
  META = await (await fetch("/api/state")).json();
  setFontMeta();
  const sel = $("#preset");
  for(const p of META.presets){ const o=document.createElement("option"); o.value=o.textContent=p; sel.appendChild(o); }
  EDITOR = initEditor(debounce(compute, 300));
  EDITOR.setValue(META.rules);
  sel.addEventListener("change", () => {
    const t = META.presetTexts[sel.value];
    if(t !== undefined){ EDITOR.setValue(t); compute(); }
  });
  $("#download").addEventListener("click", download);
  $("#openrules").addEventListener("click", () => $("#rulesfile").click());
  $("#rulesfile").addEventListener("change", async e => {
    const f = e.target.files[0];
    if(f) loadRulesText(await f.text());
    e.target.value = "";
  });
  $("#glyphq").addEventListener("input", e => { GLYPH_FILTER = e.target.value.trim(); renderGrid(); });
  setupTheme();
  setupFind();
  setupFontDrop();
  setupSplitters();
  compute();
}

/* ===================================================================== *
 *  Light / dark theme
 * ===================================================================== */
function setupTheme(){
  const KEY = "af.theme", btn = $("#theme");
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch(_){}
  const apply = t => {
    document.documentElement.dataset.theme = t;
    btn.textContent = t === "light" ? "☀" : "◐";
    btn.title = `theme: ${t} · click to toggle`;
  };
  apply(saved || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    apply(next);
    try { localStorage.setItem(KEY, next); } catch(_){}
  });
}

/* ===================================================================== *
 *  Find in rules
 * ===================================================================== */
function setupFind(){
  const bar = $("#find"), q = $("#findq"), cnt = $("#findcount"), ta = $("#rules");
  let matches = [], idx = -1;
  const updateCount = () => { cnt.textContent = matches.length ? `${idx+1}/${matches.length}` : (q.value ? "0/0" : ""); };
  function run(jump){
    const term = q.value; matches = []; idx = -1;
    if(term){
      const hay = ta.value.toLowerCase(), needle = term.toLowerCase();
      for(let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + Math.max(1, needle.length))) matches.push(i);
    }
    if(matches.length){
      const caret = ta.selectionStart;
      idx = matches.findIndex(m => m >= caret); if(idx < 0) idx = 0;
      if(jump) select();
    }
    updateCount();
  }
  function select(){
    if(idx < 0 || !matches.length) return;
    const start = matches[idx];
    ta.setSelectionRange(start, start + q.value.length);
    const line = ta.value.slice(0, start).split("\n").length;
    ta.scrollTop = Math.max(0, (line-1)*LH - ta.clientHeight/2 + LH);   // scroll fires editor sync
    updateCount();
  }
  const step = d => { if(!matches.length) return; idx = (idx + d + matches.length) % matches.length; select(); };
  const open = () => {
    bar.hidden = false;
    const sel = ta.value.substring(ta.selectionStart, ta.selectionEnd);
    if(sel && sel.length < 40 && !sel.includes("\n")) q.value = sel;
    q.focus(); q.select(); run(false);
  };
  const close = () => { bar.hidden = true; ta.focus(); };

  $("#findbtn").addEventListener("click", () => bar.hidden ? open() : close());
  $("#findclose").addEventListener("click", close);
  $("#findnext").addEventListener("click", () => step(1));
  $("#findprev").addEventListener("click", () => step(-1));
  q.addEventListener("input", () => run(true));
  q.addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); step(e.shiftKey ? -1 : 1); }
    else if(e.key === "Escape"){ e.preventDefault(); close(); }
  });
  addEventListener("keydown", e => {
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f"){ e.preventDefault(); open(); }
  });
}

function sortedGlyphs(){
  return Object.values(VIEW.glyphs).sort((a,b) =>
    (a.order - b.order) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

/* ===================================================================== *
 *  Resizable panes (splitters) — sizes persist in localStorage
 * ===================================================================== */
function setupSplitters(){
  const defs = {
    edw:   {sel:"main",        axis:"x", sign: 1, min:240, def:380, max:()=>innerWidth*0.65},
    gridh: {sel:".stage",      axis:"y", sign: 1, min: 90, def:200, max:()=>$(".stage").clientHeight*0.72},
    row:   {sel:".inspector",  axis:"x", sign:-1, min:180, def:260, max:()=>460},
  };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("af.splits") || "{}"); } catch(_){}
  const targetOf = t => document.querySelector(defs[t].sel);
  for(const t in defs) targetOf(t).style.setProperty("--"+t, (saved[t] ?? defs[t].def) + "px");
  const persist = () => {
    const out = {};
    for(const t in defs) out[t] = parseFloat(getComputedStyle(targetOf(t)).getPropertyValue("--"+t)) || defs[t].def;
    try { localStorage.setItem("af.splits", JSON.stringify(out)); } catch(_){}
  };
  for(const sp of document.querySelectorAll(".split")){
    const t = sp.dataset.t, d = defs[t], target = targetOf(t);
    sp.addEventListener("pointerdown", e => {
      e.preventDefault(); sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
      const start = d.axis === "x" ? e.clientX : e.clientY;
      const cur = parseFloat(getComputedStyle(target).getPropertyValue("--"+t)) || d.def;
      const mx = typeof d.max === "function" ? d.max() : d.max;
      const move = ev => {
        const now = d.axis === "x" ? ev.clientX : ev.clientY;
        const val = Math.max(d.min, Math.min(mx, cur + d.sign*(now - start)));
        target.style.setProperty("--"+t, val + "px");
      };
      const up = () => {
        sp.releasePointerCapture(e.pointerId); sp.classList.remove("drag");
        removeEventListener("pointermove", move); removeEventListener("pointerup", up);
        persist();
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    });
    sp.addEventListener("dblclick", () => { target.style.setProperty("--"+t, d.def + "px"); persist(); });
  }
}

function setFontMeta(){
  $("#fontmeta").textContent = `${META.font}  ${META.unitsPerEm}upm  ital ${META.italicAngle}°`;
}

/* ===================================================================== *
 *  Code editor: textarea + highlight overlay + gutter + autocomplete
 * ===================================================================== */
const KW = new Set(["width","box","outline","advance","left","center","right",
  "bottom","middle","top","first","last","centroid"]);
const METRICS = ["capHeight","xHeight","ascender","descender","baseline"];
const METRIC_SET = new Set(METRICS);
const DIRECTIVES = new Set(["!extends","!suffixes","!shiftx"]);
const BARE = [...KW, ...METRICS];             // completion pool for a bare word

function highlightLine(line){
  let out = "";
  const hash = line.indexOf("#");
  let code = line, tail = "";
  if(hash >= 0){ code = line.slice(0, hash); tail = line.slice(hash); }
  const re = /(U\+[0-9A-Fa-f]+)|(@[\w.]+)|(&\w+)|(\$[\w.]+)|(\*\d+\/\d+)|(!?[A-Za-z][\w]*)|(-?\d+(?:\.\d+)?)|(\+=|-=|=)|([(),.])/g;
  let m, last = 0;
  const put = (cls, txt) => { out += cls ? `<span class="t-${cls}">${escapeHtml(txt)}</span>` : escapeHtml(txt); };
  while((m = re.exec(code))){
    if(m.index > last) put(null, code.slice(last, m.index));
    const t = m[0];
    if(m[1]) put("uni", t);
    else if(m[2]) put("label", t);
    else if(m[3]) put("var", t);
    else if(m[4]) put("glyphref", t);
    else if(m[5]) put("num", t);
    else if(m[6]) put(DIRECTIVES.has(t) ? "dir" : KW.has(t) ? "kw" : METRIC_SET.has(t) ? "metric" : null, t);
    else if(m[7]) put("num", t);
    else if(m[8]) put("op", t);
    else put(null, t);
    last = re.lastIndex;
  }
  if(last < code.length) put(null, code.slice(last));
  if(tail) put("comment", tail);
  return out || "&nbsp;";
}

function initEditor(onChange){
  const ta = $("#rules"), hl = $("#hl"), gutter = $("#gutter"), gnums = $("#gnums"), ac = $("#ac");
  let errLines = new Set();
  let acItems = [], acSel = 0, acStart = 0;

  // measure monospace char width once
  const probe = document.createElement("span");
  probe.style.cssText = "position:absolute;visibility:hidden;font-family:var(--mono);font-size:var(--fs);white-space:pre";
  probe.textContent = "0".repeat(40);
  document.body.appendChild(probe);
  const CW = probe.getBoundingClientRect().width / 40;
  probe.remove();

  function refresh(){
    const lines = ta.value.split("\n");
    hl.innerHTML = lines.map((l,i) =>
      `<div class="ln${errLines.has(i+1) ? " err" : ""}">${highlightLine(l)}</div>`).join("");
    gnums.innerHTML = lines.map((_,i) =>
      `<div class="gl${errLines.has(i+1) ? " err" : ""}">${i+1}</div>`).join("");
    sync();
  }
  function sync(){
    hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft;
    gutter.scrollTop = ta.scrollTop;
  }
  function markErrors(set){ errLines = set || new Set(); refresh(); }

  // ---- autocomplete ----
  function currentWord(){
    const pos = ta.selectionStart;
    const upto = ta.value.slice(0, pos);
    const m = /[@&$]?[\w.]*$/.exec(upto);
    return { word: m ? m[0] : "", start: m ? pos - m[0].length : pos, pos };
  }
  function candidates(word){
    if(word.startsWith("@")){
      const set = new Set(); for(const x of ta.value.matchAll(/@[\w.]+/g)) set.add(x[0]);
      return [...set].map(v => ({v, k:"label"}));
    }
    if(word.startsWith("&")){
      const set = new Set(); for(const x of ta.value.matchAll(/&\w+/g)) set.add(x[0]);
      return [...set].map(v => ({v, k:"var"}));
    }
    if(word.startsWith("$")) return [];
    return BARE.map(v => ({v, k: METRIC_SET.has(v) ? "metric" : "kw"}));
  }
  function acUpdate(){
    const {word, start, pos} = currentWord();
    if(word.length < 1 || pos !== ta.selectionStart){ return acHide(); }
    const pool = candidates(word);
    const lower = word.toLowerCase();
    acItems = pool.filter(c => c.v.toLowerCase().startsWith(lower) && c.v !== word).slice(0, 12);
    if(!acItems.length) return acHide();
    acStart = start; acSel = 0;
    ac.innerHTML = acItems.map((c,i) =>
      `<div class="item${i===0?" sel":""}" data-i="${i}"><span>${escapeHtml(c.v)}</span><span class="k">${c.k}</span></div>`).join("");
    // position at caret (monospace math)
    const before = ta.value.slice(0, ta.selectionStart);
    const row = before.split("\n").length - 1;
    const col = before.length - before.lastIndexOf("\n") - 1;
    ac.style.left = Math.max(0, PAD + col*CW - ta.scrollLeft) + "px";
    ac.style.top  = (PAD + (row+1)*LH - ta.scrollTop) + "px";
    ac.hidden = false;
  }
  function acHide(){ ac.hidden = true; acItems = []; }
  function acMove(d){
    acSel = (acSel + d + acItems.length) % acItems.length;
    [...ac.children].forEach((n,i) => n.classList.toggle("sel", i===acSel));
    ac.children[acSel].scrollIntoView({block:"nearest"});
  }
  function acAccept(){
    if(!acItems.length) return false;
    const val = acItems[acSel].v, pos = ta.selectionStart;
    ta.value = ta.value.slice(0, acStart) + val + ta.value.slice(pos);
    const caret = acStart + val.length;
    ta.setSelectionRange(caret, caret);
    acHide(); refresh(); onChange();
    return true;
  }

  ta.addEventListener("input", () => { refresh(); acUpdate(); onChange(); });
  ta.addEventListener("scroll", sync);
  ta.addEventListener("keydown", e => {
    if(!ac.hidden){
      if(e.key === "ArrowDown"){ e.preventDefault(); return acMove(1); }
      if(e.key === "ArrowUp"){ e.preventDefault(); return acMove(-1); }
      if(e.key === "Enter" || e.key === "Tab"){ if(acAccept()){ e.preventDefault(); return; } }
      if(e.key === "Escape"){ e.preventDefault(); return acHide(); }
    }
    if(e.key === "Escape") acHide();
  });
  ta.addEventListener("click", () => acHide());
  ta.addEventListener("blur", () => setTimeout(acHide, 120));
  ac.addEventListener("mousedown", e => {
    const it = e.target.closest(".item"); if(!it) return;
    e.preventDefault(); acSel = +it.dataset.i; acAccept();
  });

  function gotoLine(n){
    const lines = ta.value.split("\n");
    let pos = 0; for(let i=0;i<n-1 && i<lines.length;i++) pos += lines[i].length + 1;
    ta.focus();
    ta.setSelectionRange(pos, pos + (lines[n-1]?.length || 0));
    ta.scrollTop = Math.max(0, (n-1)*LH - ta.clientHeight/2 + LH);
    sync();
    const ln = hl.children[n-1];
    if(ln){ ln.style.transition="background .1s"; ln.classList.add("err");
            setTimeout(()=>{ if(!errLines.has(n)) ln.classList.remove("err"); }, 700); }
  }

  return {
    getValue: () => ta.value,
    setValue: v => { ta.value = v; markErrors(new Set()); },
    refresh, markErrors, gotoLine,
  };
}

/* ===================================================================== *
 *  Font loading: drag a .ufoz/.zip/.ufo, or pick a file
 * ===================================================================== */
function setupFontDrop(){
  const overlay = $("#drop");
  let depth = 0;
  addEventListener("dragenter", e => { e.preventDefault(); if(depth++ === 0) overlay.classList.add("on"); });
  addEventListener("dragover", e => e.preventDefault());
  addEventListener("dragleave", e => { e.preventDefault(); if(--depth <= 0){ depth=0; overlay.classList.remove("on"); } });
  addEventListener("drop", async e => {
    e.preventDefault(); depth=0; overlay.classList.remove("on");
    const roots=[];
    for(const it of e.dataTransfer.items){
      const en = it.webkitGetAsEntry && it.webkitGetAsEntry();
      if(en) roots.push(en);
    }
    if(!roots.length) return;
    const collected=[];
    for(const r of roots) await walkEntry(r, "", collected);
    if(collected.length === 1 && /\.(af|dsl|txt)$/i.test(collected[0].path)){
      loadRulesText(await collected[0].file.text());   // a dropped rules file → editor
      return;
    }
    await sendFont(roots[0].name, collected);
  });
  $("#loadfont").addEventListener("click", () => $("#fontfile").click());
  $("#fontfile").addEventListener("change", async e => {
    const list=[...e.target.files];
    if(!list.length) return;
    const collected=list.map(f => ({path: f.webkitRelativePath || f.name, file: f}));
    const first=list[0];
    const name=(first.webkitRelativePath ? first.webkitRelativePath.split("/")[0] : first.name) || "font";
    await sendFont(name, collected);
    e.target.value="";
  });
}

async function walkEntry(entry, prefix, out){
  const path = prefix ? prefix+"/"+entry.name : entry.name;
  if(entry.isFile){
    out.push({path, file: await new Promise((res,rej)=>entry.file(res,rej))});
  } else if(entry.isDirectory){
    const reader = entry.createReader();
    let batch;
    do { batch = await new Promise((res,rej)=>reader.readEntries(res,rej));
         for(const e of batch) await walkEntry(e, path, out); } while(batch.length);
  }
}

async function fileToB64(file){
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin=""; const step=0x8000;
  for(let i=0;i<bytes.length;i+=step) bin += String.fromCharCode.apply(null, bytes.subarray(i, i+step));
  return btoa(bin);
}

async function sendFont(name, collected){
  const status=$("#status"); status.className="pill"; status.textContent="loading font…";
  const files=[];
  for(const c of collected) files.push({path:c.path, data: await fileToB64(c.file)});
  let j;
  try {
    const res = await fetch("/api/font",{method:"POST",headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name, files})});
    j = await res.json();
  } catch(err){ j = {ok:false, error:String(err)}; }
  if(!j.ok){
    status.className="pill bad"; status.textContent="font error";
    $("#problems").innerHTML = `<div class="row err"><span class="tag">font</span><span>${escapeHtml(j.error||"load failed")}</span></div>`;
    return;
  }
  Object.assign(META, j.state);
  setFontMeta();
  SELECTED = null;
  for(const k in lastPos) delete lastPos[k];      // tween state is per-font
  compute();
}

/* ===================================================================== *
 *  Compute + render
 * ===================================================================== */
async function compute(){
  const status = $("#status");
  status.className = "pill"; status.textContent = "computing…";
  const res = await fetch("/api/compute", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({rules: EDITOR.getValue()})
  });
  VIEW = await res.json();
  markErrorLines();
  renderProblems();
  renderGrid();
  if(!VIEW.glyphs[SELECTED]) SELECTED = (sortedGlyphs()[0] || {}).name || null;
  renderInspector();
  const bad = !VIEW.ok || (VIEW.diagnostics||[]).some(d=>d.severity==="error");
  status.className = "pill " + (bad ? "bad" : "ok");
  status.textContent = VIEW.ok ? (VIEW.diagnostics.length ? `ok · ${VIEW.diagnostics.length} notes` : "ok")
                               : `${VIEW.problems.length} problem${VIEW.problems.length>1?"s":""}`;
}

function markErrorLines(){
  const set = new Set();
  for(const p of VIEW.problems||[]){
    const m = /^line (\d+):/.exec(p);
    if(m) set.add(+m[1]);
  }
  EDITOR.markErrors(set);
}

function renderProblems(){
  const box = $("#problems"); box.innerHTML = "";
  for(const p of VIEW.problems||[]){
    const m = /^line (\d+):/.exec(p);
    row("err", "error", p, m ? +m[1] : null);
  }
  for(const d of VIEW.diagnostics||[])
    row(d.severity==="error"?"err":"warn", `${d.glyph}·${d.anchor}`, d.reason, null);
  function row(cls, tag, msg, line){
    const r=document.createElement("div"); r.className="row "+cls+(line?" clickable":"");
    r.innerHTML=`<span class="tag">${tag}</span><span>${escapeHtml(msg)}</span>`;
    if(line) r.addEventListener("click", ()=>EDITOR.gotoLine(line));
    box.appendChild(r);
  }
}

function renderGrid(){
  const grid = $("#grid"); grid.innerHTML="";
  const all = sortedGlyphs();                        // font glyphOrder
  const f = GLYPH_FILTER.toLowerCase();
  const shown = f ? all.filter(g => g.name.toLowerCase().includes(f)) : all;
  $("#count").textContent = f ? `${shown.length}/${all.length}` : all.length;
  for(const g of shown){
    const card = document.createElement("div");
    card.className = "thumb" + (g.name===SELECTED?" sel":"");
    const holder = document.createElement("div");
    card.appendChild(holder);
    card.insertAdjacentHTML("beforeend",
      `<div class="cap"><b>${escapeHtml(g.name)}</b><span>${g.anchors.length}</span></div>`);
    holder.appendChild(drawGlyph(g, {small:true}));
    card.addEventListener("click", ()=>{ SELECTED=g.name; HL_ANCHOR=null; renderGrid(); renderInspector(); });
    grid.appendChild(card);
  }
}

function extent(g){
  const m = META.metrics;
  let x0=Math.min(0, g.bounds?g.bounds[0]:0), x1=Math.max(g.advance, g.bounds?g.bounds[2]:g.advance);
  let y0=Math.min(m.descender??-200, g.bounds?g.bounds[1]:0), y1=Math.max(m.ascender??META.unitsPerEm, g.bounds?g.bounds[3]:0);
  for(const a of g.anchors){ x0=Math.min(x0,a.x); x1=Math.max(x1,a.x); y0=Math.min(y0,a.y); y1=Math.max(y1,a.y); }
  return {x0,x1,y0,y1};
}

// Build the SVG for a glyph. small=true → thumbnail (ink + dots only).
function drawGlyph(g, {small=false}={}){
  const pad = small?60:110;
  const ex = extent(g);
  const x0=ex.x0-pad, W=(ex.x1-ex.x0)+2*pad;
  const minY=-(ex.y1+pad), H=(ex.y1-ex.y0)+2*pad;
  const svg = el("svg", {viewBox:`${x0} ${minY} ${W} ${H}`, preserveAspectRatio:"xMidYMid meet"});

  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){
      const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      const t=el("text",{class:"metric-lbl", x:x0+6, y:-h-4}); t.textContent=lbl; svg.appendChild(t);
    }
    if(g.bounds){
      const [bx0,by0,bx1,by1]=g.bounds;
      svg.appendChild(el("rect",{class:"bbox", x:bx0, y:-by1, width:bx1-bx0, height:by1-by0}));
    }
  }

  const flip = el("g",{transform:"matrix(1 0 0 -1 0 0)"});
  flip.appendChild(el("path",{class:"ink", d:g.path}));
  svg.appendChild(flip);

  if(!small){
    for(const a of g.anchors){
      if(a.x_sample){
        const h=a.x_sample.height;
        svg.appendChild(el("line",{class:"scan", x1:x0, y1:-h, x2:x0+W, y2:-h}));
        for(const c of a.x_sample.crossings) svg.appendChild(el("circle",{class:"cross", cx:c, cy:-h, r:5}));
        for(const [lo,hi] of a.x_sample.stems) svg.appendChild(el("line",{class:"stem", x1:lo, y1:-h, x2:hi, y2:-h}));
      }
      if(a.y_sample){
        const c=a.y_sample.column;
        svg.appendChild(el("line",{class:"scan", x1:c, y1:minY, x2:c, y2:minY+H}));
        for(const cr of a.y_sample.crossings) svg.appendChild(el("circle",{class:"cross", cx:c, cy:-cr, r:5}));
        for(const [lo,hi] of a.y_sample.stems) svg.appendChild(el("line",{class:"stem", x1:c, y1:-lo, x2:c, y2:-hi}));
      }
      if(a.centroid){
        const [cx,cy]=a.centroid;
        svg.appendChild(el("line",{class:"centroid", x1:cx-22, y1:-cy, x2:cx+22, y2:-cy}));
        svg.appendChild(el("line",{class:"centroid", x1:cx, y1:-cy-22, x2:cx, y2:-cy+22}));
      }
    }
  }

  const store = (lastPos[g.name] = lastPos[g.name] || {});
  for(const a of g.anchors){
    const warn = a.warnings && a.warnings.length;
    const grp = el("g",{class:"anchor-g"+(warn?" warn":""), "data-name":a.name});
    grp.appendChild(el("circle",{class:"ring", cx:0, cy:0, r:small?9:16}));
    grp.appendChild(el("circle",{cx:0, cy:0, r:small?3:5}));
    if(!small){
      const t=el("text",{x:12, y:-10}); t.textContent=`${a.name} (${Math.round(a.x)}, ${Math.round(a.y)})`;
      grp.appendChild(t);
    }
    const target=`translate(${a.x}px, ${-a.y}px)`;
    if(!small && !REDUCED && store[a.name]){
      const p=store[a.name];
      grp.style.transform=`translate(${p.x}px, ${-p.y}px)`;
      requestAnimationFrame(()=>requestAnimationFrame(()=>{ grp.style.transform=target; }));
    } else {
      grp.style.transform=target;
    }
    store[a.name]={x:a.x, y:a.y};
    svg.appendChild(grp);
  }
  return svg;
}

function renderInspector(){
  const canvas=$("#canvas"), read=$("#readout");
  if(!SELECTED || !VIEW.glyphs[SELECTED]){
    canvas.innerHTML='<div class="empty">no glyph selected</div>'; read.innerHTML=""; return;
  }
  const g=VIEW.glyphs[SELECTED];
  canvas.innerHTML=""; canvas.appendChild(drawGlyph(g,{small:false}));
  read.innerHTML=`<h3>${escapeHtml(g.name)}</h3><div class="sub">adv ${Math.round(g.advance)} · `+
    (g.bounds?`bbox ${g.bounds.map(Math.round).join(" ")}`:"no outline")+`</div>`;
  for(const a of g.anchors){
    const warn = (a.warnings||[]).map(w=>escapeHtml(w)).join("<br>");
    const card=document.createElement("div"); card.className="anchor-card";
    card.dataset.anchor = a.name;
    card.innerHTML =
      `<div class="nm">${escapeHtml(a.name)}${warn?' <span title="fallback">⚠</span>':''}</div>`+
      `<div class="co">x ${round(a.x)}   y ${round(a.y)}</div>`+
      `<div class="kd">x: ${a.x_kind} · y: ${a.y_kind}</div>`+
      (a.line?`<div class="rule">→ rule L${a.line}</div>`:"")+
      (warn?`<div class="wn">${warn}</div>`:"");
    card.addEventListener("click", ()=>{               // highlight the dot in the preview + jump to its rule
      highlightAnchor(a.name);
      if(a.line) EDITOR.gotoLine(a.line);
    });
    read.appendChild(card);
  }
  applyHighlight();
}

function highlightAnchor(name){ HL_ANCHOR = name; applyHighlight(); }

function applyHighlight(){
  for(const gEl of $("#canvas").querySelectorAll(".anchor-g"))
    gEl.classList.toggle("hl", gEl.dataset.name === HL_ANCHOR);
  for(const card of $("#readout").querySelectorAll(".anchor-card"))
    card.classList.toggle("sel", card.dataset.anchor === HL_ANCHOR);
}

function download(){
  const blob=new Blob([EDITOR.getValue()], {type:"text/plain"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download="anchors.af"; a.click();
  URL.revokeObjectURL(a.href);
}

// Load custom rule text into the editor (from the "open" picker or a dropped
// .af). Such a file may `!extends default` to inherit a bundled preset.
function loadRulesText(text){
  EDITOR.setValue(text);
  $("#preset").selectedIndex = -1;                 // content is now custom, not a raw preset
  SELECTED = null; HL_ANCHOR = null;
  compute();
}

boot();
