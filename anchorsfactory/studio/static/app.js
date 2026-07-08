"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const REDUCED = matchMedia("(prefers-reduced-motion:reduce)").matches;
const LH = 20, PAD = 14;                     // editor line-height / padding (match app.css)
let META = null, VIEW = {glyphs:{}, layers:[]}, SELECTED = null, GLYPH_FILTER = "", HL_ANCHOR = null;
let GLYPHS = {};                       // last valid glyph view (frozen while rules are invalid)
let GRID_TAB = "affected";             // "affected" | "all"
let HIDE_AFFECTED = false;             // on the "all" tab: show only unaffected glyphs
let ALLGLYPHS = null;                  // [{name,order,advance,bounds,path}] for the "all" tab (lazy)
let ALLMAP = {};                       // name -> all-glyph geometry entry
let baseEd = null, customEd = null, activeEd = null, customOpen = false;
const lastPos = {};                          // glyph -> {anchor -> {x,y}} for tweening

const $ = s => document.querySelector(s);
const el = (n, a={}) => { const e=document.createElementNS(SVGNS,n); for(const k in a) e.setAttribute(k,a[k]); return e; };
const round = v => Math.round(v*10)/10;
const escapeHtml = s => String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const debounce = (fn, ms) => { let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), ms);}; };
const allRulesText = () => (baseEd ? baseEd.getValue() : "") + "\n" + (customEd ? customEd.getValue() : "");
const editorForLayer = i => (i === 0 ? baseEd : customEd);

async function boot(){
  META = await (await fetch("/api/state")).json();
  setFontMeta();
  const sel = $("#preset");
  for(const p of META.presets){ const o=document.createElement("option"); o.value=o.textContent=p; sel.appendChild(o); }
  setupEditors();
  setupGrid();
  setupTheme();
  setupFind();
  setupFontDrop();
  setupSplitters();
  compute();
}

function setFontMeta(){
  $("#fontmeta").textContent = `${META.font}  ${META.unitsPerEm}upm  ital ${META.italicAngle}°`;
}

/* ===================================================================== *
 *  Rule layers: a base preset (editable) + a custom layer on top.
 *  Effective rules = base then custom (custom overrides).
 * ===================================================================== */
const persist = debounce(() => {
  try {
    localStorage.setItem("af.rules", JSON.stringify(
      {preset: $("#preset").value, base: baseEd.getValue(), custom: customEd.getValue(), customOpen}));
  } catch(_){}
}, 400);

// Custom layer is collapsible: closed → work with the base only.
function setCustomOpen(open){ customOpen = open; $(".editor").classList.toggle("solo-base", !open); persist(); }

function setupEditors(){
  const onChange = () => { persist(); scheduleCompute(); };
  baseEd = makeEditor($("#edBase"), onChange, () => activeEd = baseEd);
  customEd = makeEditor($("#edCustom"), onChange, () => activeEd = customEd);
  activeEd = customEd;

  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("af.rules") || "null"); } catch(_){}
  if(saved){
    $("#preset").value = saved.preset || META.presets[0] || "";
    baseEd.setValue(saved.base ?? META.rules);
    customEd.setValue(saved.custom ?? "");
    customOpen = !!saved.customOpen;
  } else {
    $("#preset").value = presetOf(META.rules) || META.presets[0] || "";
    baseEd.setValue(META.rules);
    customEd.setValue("# custom rules — layered over the base below, and win\n");
    customOpen = false;                            // start with just the base
  }
  $(".editor").classList.toggle("solo-base", !customOpen);

  $("#preset").addEventListener("change", e => {
    const t = META.presetTexts[e.target.value];
    if(t !== undefined){ baseEd.setValue(t); persist(); compute(); }
  });
  document.querySelectorAll(".layer-head [data-a]").forEach(btn => {
    btn.addEventListener("click", () => {
      const a = btn.dataset.a;
      if(a === "find"){ activeEd = customEd; openFind(); }
      else if(a === "open"){ $("#rulesfile").click(); }
      else if(a === "dl-custom") downloadText(customEd.getValue(), "custom.af");
      else if(a === "dl-base") downloadText(baseEd.getValue(), "base.af");
      else if(a === "add-custom"){ setCustomOpen(true); customEd.focus(); compute(); }
      else if(a === "close"){ setCustomOpen(false); if(activeEd === customEd) activeEd = baseEd; compute(); }
    });
  });
  $("#rulesfile").addEventListener("change", async e => {
    const f = e.target.files[0];
    if(f){ setCustomOpen(true); customEd.setValue(await f.text()); persist(); SELECTED = null; HL_ANCHOR = null; compute(); }
    e.target.value = "";
  });
}

/* ===================================================================== *
 *  Glyph grid: affected / all-glyphs tabs
 * ===================================================================== */
function persistGrid(){
  try { localStorage.setItem("af.grid", JSON.stringify({tab: GRID_TAB, hideAffected: HIDE_AFFECTED})); } catch(_){}
}

function setupGrid(){
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("af.grid") || "null"); } catch(_){}
  if(saved){ GRID_TAB = saved.tab === "all" ? "all" : "affected"; HIDE_AFFECTED = !!saved.hideAffected; }
  $("#hideaffcb").checked = HIDE_AFFECTED;
  syncGridChrome();

  document.querySelectorAll("#gridtabs .tab").forEach(btn => {
    btn.addEventListener("click", () => selectTab(btn.dataset.tab));
  });
  $("#hideaffcb").addEventListener("change", e => {
    HIDE_AFFECTED = e.target.checked; persistGrid(); renderGrid();
  });
  const applyFilter = debounce(() => renderGrid(), 120);
  $("#glyphq").addEventListener("input", e => { GLYPH_FILTER = e.target.value.trim(); applyFilter(); });
}

// reflect GRID_TAB in the tab buttons + show the hide-affected control only on "all"
function syncGridChrome(){
  document.querySelectorAll("#gridtabs .tab").forEach(b => b.classList.toggle("sel", b.dataset.tab === GRID_TAB));
  $("#hideaff").hidden = GRID_TAB !== "all";
}

async function selectTab(tab){
  if(tab === GRID_TAB) return;
  GRID_TAB = tab; persistGrid(); syncGridChrome();
  if(tab === "all" && ALLGLYPHS === null) await fetchAllGlyphs();
  renderGrid();
}

async function fetchAllGlyphs(){
  const cnt = $("#count"); cnt.textContent = "loading…";
  try {
    const j = await (await fetch("/api/allglyphs")).json();
    ALLGLYPHS = j.glyphs || [];
  } catch(err){ ALLGLYPHS = []; }
  ALLMAP = {}; for(const g of ALLGLYPHS) ALLMAP[g.name] = g;
}

const scheduleCompute = debounce(() => compute(), 300);
function presetOf(text){ return META.presets.find(p => META.presetTexts[p] === text) || ""; }

/* ---- a code editor bound to a host element (one per layer) ---- */
const KW = new Set(["width","box","outline","advance","left","center","right",
  "bottom","middle","top","first","last","centroid"]);
const METRICS = ["capHeight","xHeight","ascender","descender","baseline"];
const METRIC_SET = new Set(METRICS);
const DIRECTIVES = new Set(["!extends","!suffixes","!shiftx","!propagate"]);
const BARE = [...KW, ...METRICS];
let CHAR_W = 0;

function highlightLine(line){
  let out = "";
  const hash = line.indexOf("#");
  let code = line, tail = "";
  if(hash >= 0){ code = line.slice(0, hash); tail = line.slice(hash); }
  const re = /(U\+[0-9A-Fa-f]+)|(@[\w.]+)|(&\w+)|(%[\w.]+)|(\$[\w.]+)|(\*\d+\/\d+)|(!?[A-Za-z][\w]*)|(-?\d+(?:\.\d+)?)|(\+=|-=|=)|([(),.])/g;
  let m, last = 0;
  const put = (cls, txt) => { out += cls ? `<span class="t-${cls}">${escapeHtml(txt)}</span>` : escapeHtml(txt); };
  while((m = re.exec(code))){
    if(m.index > last) put(null, code.slice(last, m.index));
    const t = m[0];
    if(m[1]) put("uni", t);
    else if(m[2]) put("label", t);
    else if(m[3]) put("var", t);
    else if(m[4]) put("glyphref", t);            // %anchor — reference to another anchor
    else if(m[5]) put("glyphref", t);
    else if(m[6]) put("num", t);
    else if(m[7]) put(DIRECTIVES.has(t) ? "dir" : KW.has(t) ? "kw" : METRIC_SET.has(t) ? "metric" : null, t);
    else if(m[8]) put("num", t);
    else if(m[9]) put("op", t);
    else put(null, t);
    last = re.lastIndex;
  }
  if(last < code.length) put(null, code.slice(last));
  if(tail) put("comment", tail);
  return out || "&nbsp;";
}

function makeEditor(host, onChange, onFocus){
  host.innerHTML =
    '<div class="ed"><div class="ed-gutter"><div class="gnums"></div></div>'+
    '<div class="ed-body"><pre class="ed-hl" aria-hidden="true"></pre>'+
    '<textarea class="ed-ta" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off"></textarea>'+
    '<div class="ac" hidden></div></div></div>';
  const ta = host.querySelector(".ed-ta"), hl = host.querySelector(".ed-hl"),
        gutter = host.querySelector(".ed-gutter"), gnums = host.querySelector(".gnums"),
        ac = host.querySelector(".ac");
  let errLines = new Set(), acItems = [], acSel = 0, acStart = 0;

  if(!CHAR_W){
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;font-family:var(--mono);font-size:var(--fs);white-space:pre";
    probe.textContent = "0".repeat(40); document.body.appendChild(probe);
    CHAR_W = probe.getBoundingClientRect().width / 40; probe.remove();
  }

  function refresh(){
    const lines = ta.value.split("\n");
    hl.innerHTML = lines.map((l,i) => `<div class="ln${errLines.has(i+1)?" err":""}">${highlightLine(l)}</div>`).join("");
    gnums.innerHTML = lines.map((_,i) => `<div class="gl${errLines.has(i+1)?" err":""}">${i+1}</div>`).join("");
    sync();
  }
  function sync(){ hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft; gutter.scrollTop = ta.scrollTop; }
  function markErrors(set){ errLines = set || new Set(); refresh(); }

  function currentWord(){
    const pos = ta.selectionStart, upto = ta.value.slice(0, pos);
    const m = /[@&$]?[\w.]*$/.exec(upto);
    return { word: m ? m[0] : "", start: m ? pos - m[0].length : pos, pos };
  }
  function candidates(word){
    if(word.startsWith("@")){ const s=new Set(); for(const x of allRulesText().matchAll(/@[\w.]+/g)) s.add(x[0]); return [...s].map(v=>({v,k:"label"})); }
    if(word.startsWith("&")){ const s=new Set(); for(const x of allRulesText().matchAll(/&\w+/g)) s.add(x[0]); return [...s].map(v=>({v,k:"var"})); }
    if(word.startsWith("$")) return [];
    return BARE.map(v => ({v, k: METRIC_SET.has(v) ? "metric" : "kw"}));
  }
  function acUpdate(){
    const {word, start, pos} = currentWord();
    if(word.length < 1 || pos !== ta.selectionStart) return acHide();
    const lower = word.toLowerCase();
    acItems = candidates(word).filter(c => c.v.toLowerCase().startsWith(lower) && c.v !== word).slice(0, 12);
    if(!acItems.length) return acHide();
    acStart = start; acSel = 0;
    ac.innerHTML = acItems.map((c,i) => `<div class="item${i===0?" sel":""}" data-i="${i}"><span>${escapeHtml(c.v)}</span><span class="k">${c.k}</span></div>`).join("");
    const before = ta.value.slice(0, ta.selectionStart);
    const row = before.split("\n").length - 1, col = before.length - before.lastIndexOf("\n") - 1;
    ac.style.left = Math.max(0, PAD + col*CHAR_W - ta.scrollLeft) + "px";
    ac.style.top = (PAD + (row+1)*LH - ta.scrollTop) + "px";
    ac.hidden = false;
  }
  function acHide(){ ac.hidden = true; acItems = []; }
  function acMove(d){ acSel = (acSel + d + acItems.length) % acItems.length; [...ac.children].forEach((n,i)=>n.classList.toggle("sel", i===acSel)); ac.children[acSel].scrollIntoView({block:"nearest"}); }
  function acAccept(){
    if(!acItems.length) return false;
    const val = acItems[acSel].v, pos = ta.selectionStart;
    ta.value = ta.value.slice(0, acStart) + val + ta.value.slice(pos);
    const caret = acStart + val.length; ta.setSelectionRange(caret, caret);
    acHide(); refresh(); onChange(); return true;
  }

  ta.addEventListener("input", () => { refresh(); acUpdate(); onChange(); });
  ta.addEventListener("scroll", sync);
  ta.addEventListener("focus", () => onFocus && onFocus());
  ta.addEventListener("click", acHide);
  ta.addEventListener("blur", () => setTimeout(acHide, 120));
  ta.addEventListener("keydown", e => {
    if(!ac.hidden){
      if(e.key === "ArrowDown"){ e.preventDefault(); return acMove(1); }
      if(e.key === "ArrowUp"){ e.preventDefault(); return acMove(-1); }
      if(e.key === "Enter" || e.key === "Tab"){ if(acAccept()){ e.preventDefault(); return; } }
      if(e.key === "Escape"){ e.preventDefault(); return acHide(); }
    }
  });
  ac.addEventListener("mousedown", e => { const it = e.target.closest(".item"); if(!it) return; e.preventDefault(); acSel = +it.dataset.i; acAccept(); });

  function gotoLine(n){
    const lines = ta.value.split("\n");
    let pos = 0; for(let i=0;i<n-1 && i<lines.length;i++) pos += lines[i].length + 1;
    ta.focus();
    ta.setSelectionRange(pos, pos + (lines[n-1]?.length || 0));
    ta.scrollTop = Math.max(0, (n-1)*LH - ta.clientHeight/2 + LH); sync();
    const ln = hl.children[n-1];
    if(ln){ ln.classList.add("err"); setTimeout(()=>{ if(!errLines.has(n)) ln.classList.remove("err"); }, 700); }
  }

  return { getValue: () => ta.value, setValue: v => { ta.value = v; markErrors(new Set()); },
           refresh, markErrors, gotoLine, focus: () => ta.focus(), ta };
}

/* ===================================================================== *
 *  Find in rules (operates on the active layer's editor)
 * ===================================================================== */
let findMatches = [], findIdx = -1;
function findRun(jump){
  const q = $("#findq"), ta = activeEd.ta, term = q.value;
  findMatches = []; findIdx = -1;
  if(term){
    const hay = ta.value.toLowerCase(), needle = term.toLowerCase();
    for(let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + Math.max(1, needle.length))) findMatches.push(i);
  }
  if(findMatches.length){
    findIdx = findMatches.findIndex(m => m >= ta.selectionStart); if(findIdx < 0) findIdx = 0;
    if(jump) findSelect();
  }
  findCount();
}
function findSelect(){
  const q = $("#findq"), ta = activeEd.ta;
  if(findIdx < 0 || !findMatches.length) return;
  const start = findMatches[findIdx];
  ta.setSelectionRange(start, start + q.value.length);
  ta.scrollTop = Math.max(0, (ta.value.slice(0,start).split("\n").length-1)*LH - ta.clientHeight/2 + LH);
  ta.dispatchEvent(new Event("scroll"));
  findCount();
}
function findStep(d){ if(findMatches.length){ findIdx = (findIdx + d + findMatches.length) % findMatches.length; findSelect(); } }
function findCount(){ const q=$("#findq"); $("#findcount").textContent = findMatches.length ? `${findIdx+1}/${findMatches.length}` : (q.value ? "0/0" : ""); }
function openFind(){
  const bar = $("#find"), q = $("#findq"), ta = activeEd.ta;
  bar.hidden = false;
  const sel = ta.value.substring(ta.selectionStart, ta.selectionEnd);
  if(sel && sel.length < 40 && !sel.includes("\n")) q.value = sel;
  q.focus(); q.select(); findRun(false);
}
function closeFind(){ $("#find").hidden = true; activeEd.focus(); }
function setupFind(){
  $("#findclose").addEventListener("click", closeFind);
  $("#findnext").addEventListener("click", () => findStep(1));
  $("#findprev").addEventListener("click", () => findStep(-1));
  $("#findq").addEventListener("input", () => findRun(true));
  $("#findq").addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); findStep(e.shiftKey ? -1 : 1); }
    else if(e.key === "Escape"){ e.preventDefault(); closeFind(); }
  });
  addEventListener("keydown", e => { if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f"){ e.preventDefault(); openFind(); } });
}

/* ===================================================================== *
 *  Light / dark theme
 * ===================================================================== */
function setupTheme(){
  const KEY = "af.theme", btn = $("#theme");
  let saved = null; try { saved = localStorage.getItem(KEY); } catch(_){}
  const apply = t => { document.documentElement.dataset.theme = t; btn.textContent = t==="light" ? "☀" : "◐"; btn.title = `theme: ${t} · click to toggle`; };
  apply(saved || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  btn.addEventListener("click", () => { const next = document.documentElement.dataset.theme==="light" ? "dark" : "light"; apply(next); try { localStorage.setItem(KEY, next); } catch(_){} });
}

/* ===================================================================== *
 *  Resizable panes (splitters) — sizes persist in localStorage
 * ===================================================================== */
function setupSplitters(){
  const defs = {
    edw:   {sel:"main",       axis:"x", sign: 1, min:280, def:400, max:()=>innerWidth*0.7},
    baseh: {sel:".editor",    axis:"y", sign:-1, min: 80, def:220, max:()=>$(".editor").clientHeight*0.7},
    probh: {sel:".editor",    axis:"y", sign:-1, min: 44, def:150, max:()=>$(".editor").clientHeight*0.6},
    gridh: {sel:".stage",     axis:"y", sign: 1, min: 90, def:200, max:()=>$(".stage").clientHeight*0.72},
    row:   {sel:".inspector", axis:"x", sign:-1, min:180, def:260, max:()=>460},
  };
  let saved = {}; try { saved = JSON.parse(localStorage.getItem("af.splits") || "{}"); } catch(_){}
  const targetOf = t => document.querySelector(defs[t].sel);
  for(const t in defs) targetOf(t).style.setProperty("--"+t, (saved[t] ?? defs[t].def) + "px");
  const store = () => { const o={}; for(const t in defs) o[t]=parseFloat(getComputedStyle(targetOf(t)).getPropertyValue("--"+t))||defs[t].def; try{localStorage.setItem("af.splits",JSON.stringify(o));}catch(_){} };
  for(const sp of document.querySelectorAll(".split")){
    const t = sp.dataset.t, d = defs[t]; if(!d) continue;
    const target = targetOf(t);
    sp.addEventListener("pointerdown", e => {
      e.preventDefault(); sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
      const start = d.axis==="x" ? e.clientX : e.clientY;
      const cur = parseFloat(getComputedStyle(target).getPropertyValue("--"+t)) || d.def;
      const mx = typeof d.max === "function" ? d.max() : d.max;
      const move = ev => { const now = d.axis==="x" ? ev.clientX : ev.clientY; target.style.setProperty("--"+t, Math.max(d.min, Math.min(mx, cur + d.sign*(now-start))) + "px"); };
      const up = () => { sp.releasePointerCapture(e.pointerId); sp.classList.remove("drag"); removeEventListener("pointermove", move); removeEventListener("pointerup", up); store(); };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    });
    sp.addEventListener("dblclick", () => { target.style.setProperty("--"+t, d.def + "px"); store(); });
  }
}

/* ===================================================================== *
 *  Font loading: drag a font/.af, or pick a file
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
    for(const it of e.dataTransfer.items){ const en = it.webkitGetAsEntry && it.webkitGetAsEntry(); if(en) roots.push(en); }
    if(!roots.length) return;
    const collected=[];
    for(const r of roots) await walkEntry(r, "", collected);
    if(collected.length === 1 && /\.(af|dsl|txt)$/i.test(collected[0].path)){   // a rules file → custom layer
      setCustomOpen(true); customEd.setValue(await collected[0].file.text()); persist(); SELECTED = null; HL_ANCHOR = null; compute(); return;
    }
    await sendFont(roots[0].name, collected);
  });
  $("#loadfont").addEventListener("click", () => $("#fontfile").click());
  $("#fontfile").addEventListener("change", async e => {
    const list=[...e.target.files]; if(!list.length) return;
    const collected=list.map(f => ({path: f.webkitRelativePath || f.name, file: f}));
    const first=list[0];
    const name=(first.webkitRelativePath ? first.webkitRelativePath.split("/")[0] : first.name) || "font";
    await sendFont(name, collected); e.target.value="";
  });
}

async function walkEntry(entry, prefix, out){
  const path = prefix ? prefix+"/"+entry.name : entry.name;
  if(entry.isFile){ out.push({path, file: await new Promise((res,rej)=>entry.file(res,rej))}); }
  else if(entry.isDirectory){ const reader = entry.createReader(); let batch;
    do { batch = await new Promise((res,rej)=>reader.readEntries(res,rej)); for(const e of batch) await walkEntry(e, path, out); } while(batch.length); }
}

async function fileToB64(file){
  const bytes = new Uint8Array(await file.arrayBuffer()); let bin=""; const step=0x8000;
  for(let i=0;i<bytes.length;i+=step) bin += String.fromCharCode.apply(null, bytes.subarray(i, i+step));
  return btoa(bin);
}

async function sendFont(name, collected){
  const status=$("#status"); status.className="pill"; status.textContent="loading font…";
  const files=[]; for(const c of collected) files.push({path:c.path, data: await fileToB64(c.file)});
  let j;
  try { j = await (await fetch("/api/font",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name, files})})).json(); }
  catch(err){ j = {ok:false, error:String(err)}; }
  if(!j.ok){ status.className="pill bad"; status.textContent="font error";
    $("#problems").innerHTML = `<div class="row err"><span class="tag">font</span><span>${escapeHtml(j.error||"load failed")}</span></div>`; return; }
  Object.assign(META, j.state); setFontMeta();
  SELECTED = null; HL_ANCHOR = null; GLYPHS = {};    // a new font invalidates the frozen view
  ALLGLYPHS = null; ALLMAP = {};                     // …and the all-glyphs geometry cache
  for(const k in lastPos) delete lastPos[k];
  compute();
}

function downloadText(text, filename){
  const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([text],{type:"text/plain"}));
  a.download=filename; a.click(); URL.revokeObjectURL(a.href);
}

/* ===================================================================== *
 *  Compute + render
 * ===================================================================== */
async function compute(){
  const status = $("#status"); status.className = "pill"; status.textContent = "computing…";
  const layers = customOpen
    ? [{name:"base", text: baseEd.getValue()}, {name:"custom", text: customEd.getValue()}]
    : [{name:"base", text: baseEd.getValue()}];
  try {
    const res = await fetch("/api/compute", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({layers})});
    VIEW = await res.json();
  } catch(err) {                                    // server 500 / dropped connection / bad JSON
    VIEW = {ok:false, problems:["studio server error — see terminal: "+String(err)], diagnostics:[], glyphs:{}, layers:[]};
  }
  markErrorLines();
  renderProblems();
  // Freeze the last valid preview while rules are mid-edit / invalid: the server
  // returns no glyphs for a broken document, so re-rendering would blank the grid
  // and drop the selection (then snap to the first glyph when it validates again).
  // Only refresh the glyph view — and the selection — on a clean compute.
  const stage = document.querySelector(".stage");
  if(VIEW.ok){
    GLYPHS = VIEW.glyphs;
    stage.classList.remove("stale");
    renderGrid();
    if(!glyphData(SELECTED)) SELECTED = (sortedGlyphs()[0] || {}).name || null;
    renderInspector();
  } else {
    stage.classList.add("stale");                   // show it's frozen, not live
  }
  const bad = !VIEW.ok || (VIEW.diagnostics||[]).some(d=>d.severity==="error");
  status.className = "pill " + (bad ? "bad" : "ok");
  status.textContent = VIEW.ok ? (VIEW.diagnostics.length ? `ok · ${VIEW.diagnostics.length} notes` : "ok")
                               : `${VIEW.problems.length} problem${VIEW.problems.length>1?"s":""}`;
}

// "base: line 3: ..." / "custom: line 3: ..." / "line 3: ..." → {layer index, line}
function problemLoc(p){
  let m = /^(base|custom): line (\d+):/.exec(p);
  if(m) return { layer: m[1]==="base" ? 0 : 1, line: +m[2] };
  m = /^line (\d+):/.exec(p);
  return m ? { layer: 1, line: +m[1] } : null;
}

function markErrorLines(){
  const sets = [new Set(), new Set()];
  for(const p of VIEW.problems||[]){ const loc = problemLoc(p); if(loc) sets[loc.layer].add(loc.line); }
  baseEd.markErrors(sets[0]); customEd.markErrors(sets[1]);
}

function renderProblems(){
  const box = $("#problems"); box.innerHTML = "";
  const probs = VIEW.problems||[], diags = VIEW.diagnostics||[];
  const errs = probs.length + diags.filter(d=>d.severity==="error").length;
  const cnt = $("#outcount");
  if(cnt){ cnt.textContent = (probs.length+diags.length) || ""; cnt.classList.toggle("bad", errs>0); }
  if(!probs.length && !diags.length){
    box.innerHTML = `<div class="row ok-row"><span class="tag">ok</span><span>no problems</span></div>`; return;
  }
  for(const p of probs){ const loc = problemLoc(p); row("err", "error", p, loc); }
  for(const d of diags) row(d.severity==="error"?"err":"warn", `${d.glyph}·${d.anchor}`, d.reason, null);
  function row(cls, tag, msg, loc){
    const r=document.createElement("div"); r.className="row "+cls+(loc?" clickable":"");
    r.innerHTML=`<span class="tag">${tag}</span><span>${escapeHtml(msg)}</span>`;
    if(loc) r.addEventListener("click", ()=>{ activeEd = editorForLayer(loc.layer); editorForLayer(loc.layer).gotoLine(loc.line); });
    box.appendChild(r);
  }
}

const _bySort = (a,b) => (a.order - b.order) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);

function sortedGlyphs(){
  return Object.values(GLYPHS).sort(_bySort);
}

// The glyphs to show for the active tab. "all" overlays computed anchors onto the
// full geometry (affected glyphs keep their anchors/overlays); hide-affected drops
// the ones already in the affected set.
function glyphList(){
  if(GRID_TAB === "affected") return sortedGlyphs();
  let all = (ALLGLYPHS || []).map(g => GLYPHS[g.name] || {...g, anchors: []});
  if(HIDE_AFFECTED) all = all.filter(g => !GLYPHS[g.name]);
  return all.sort(_bySort);
}

// A glyph's data for the inspector: computed (with anchors/overlays) if affected,
// else its plain geometry with no anchors (an unaffected glyph on the "all" tab).
function glyphData(name){
  if(GLYPHS[name]) return GLYPHS[name];
  const g = ALLMAP[name];
  return g ? {...g, anchors: []} : null;
}

// Thumbnails draw lazily: the SVG is built only when a card scrolls near view,
// so an ~800-glyph "all" tab stays responsive.
let gridObserver = null;
function ensureObserver(){
  if(gridObserver) return gridObserver;
  gridObserver = new IntersectionObserver(entries => {
    for(const e of entries){
      if(!e.isIntersecting) continue;
      gridObserver.unobserve(e.target);
      const holder = e.target.querySelector(".holder");
      if(e.target._glyph && holder && !holder.firstChild){
        holder.classList.remove("ph");
        holder.appendChild(drawGlyph(e.target._glyph, {small:true}));
      }
    }
  }, {root: $(".gridwrap"), rootMargin: "250px"});
  return gridObserver;
}

function setGridCount(shown, total, filtered){
  const label = GRID_TAB === "affected" ? "affected" : (HIDE_AFFECTED ? "unaffected" : "all");
  $("#count").textContent = `${label} · ` + (filtered ? `${shown}/${total}` : total);
}

function renderGrid(){
  if(GRID_TAB === "all" && ALLGLYPHS === null){ fetchAllGlyphs().then(renderGrid); return; }
  const grid = $("#grid"); grid.innerHTML="";
  const obs = ensureObserver(); obs.disconnect();     // stop watching the old cards
  const all = glyphList();
  const f = GLYPH_FILTER.toLowerCase();
  const shown = f ? all.filter(g => g.name.toLowerCase().includes(f)) : all;
  setGridCount(shown.length, all.length, !!f);
  for(const g of shown){
    const card = document.createElement("div"); card.className = "thumb" + (g.name===SELECTED?" sel":"");
    card._glyph = g;
    const holder = document.createElement("div"); holder.className = "holder ph"; card.appendChild(holder);
    card.insertAdjacentHTML("beforeend", `<div class="cap"><b>${escapeHtml(g.name)}</b><span>${g.anchors.length}</span></div>`);
    card.addEventListener("click", ()=>{ SELECTED=g.name; HL_ANCHOR=null; renderGrid(); renderInspector(); });
    grid.appendChild(card);
    obs.observe(card);
  }
}

function extent(g){
  const m = META.metrics;
  let x0=Math.min(0, g.bounds?g.bounds[0]:0), x1=Math.max(g.advance, g.bounds?g.bounds[2]:g.advance);
  let y0=Math.min(m.descender??-200, g.bounds?g.bounds[1]:0), y1=Math.max(m.ascender??META.unitsPerEm, g.bounds?g.bounds[3]:0);
  for(const a of g.anchors){ x0=Math.min(x0,a.x); x1=Math.max(x1,a.x); y0=Math.min(y0,a.y); y1=Math.max(y1,a.y); }
  return {x0,x1,y0,y1};
}

function drawGlyph(g, {small=false}={}){
  const pad = small?60:110;
  const ex = extent(g);
  const x0=ex.x0-pad, W=(ex.x1-ex.x0)+2*pad, minY=-(ex.y1+pad), H=(ex.y1-ex.y0)+2*pad;
  const svg = el("svg", {viewBox:`${x0} ${minY} ${W} ${H}`, preserveAspectRatio:"xMidYMid meet"});
  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){ const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      const t=el("text",{class:"metric-lbl", x:x0+6, y:-h-4}); t.textContent=lbl; svg.appendChild(t); }
    if(g.bounds){ const [bx0,by0,bx1,by1]=g.bounds; svg.appendChild(el("rect",{class:"bbox", x:bx0, y:-by1, width:bx1-bx0, height:by1-by0})); }
  }
  const flip = el("g",{transform:"matrix(1 0 0 -1 0 0)"});
  flip.appendChild(el("path",{class:"ink", d:g.path})); svg.appendChild(flip);
  if(!small){
    for(const a of g.anchors){
      if(a.x_sample){ const h=a.x_sample.height;
        svg.appendChild(el("line",{class:"scan", x1:x0, y1:-h, x2:x0+W, y2:-h}));
        for(const c of a.x_sample.crossings) svg.appendChild(el("circle",{class:"cross", cx:c, cy:-h, r:5}));
        for(const [lo,hi] of a.x_sample.stems) svg.appendChild(el("line",{class:"stem", x1:lo, y1:-h, x2:hi, y2:-h})); }
      if(a.y_sample){ const c=a.y_sample.column;
        svg.appendChild(el("line",{class:"scan", x1:c, y1:minY, x2:c, y2:minY+H}));
        for(const cr of a.y_sample.crossings) svg.appendChild(el("circle",{class:"cross", cx:c, cy:-cr, r:5}));
        for(const [lo,hi] of a.y_sample.stems) svg.appendChild(el("line",{class:"stem", x1:c, y1:-lo, x2:c, y2:-hi})); }
      if(a.centroid){ const [cx,cy]=a.centroid;
        svg.appendChild(el("line",{class:"centroid", x1:cx-22, y1:-cy, x2:cx+22, y2:-cy}));
        svg.appendChild(el("line",{class:"centroid", x1:cx, y1:-cy-22, x2:cx, y2:-cy+22})); }
    }
  }
  const store = (lastPos[g.name] = lastPos[g.name] || {});
  for(const a of g.anchors){
    const warn = a.warnings && a.warnings.length;
    const grp = el("g",{class:"anchor-g"+(warn?" warn":""), "data-name":a.name});
    grp.appendChild(el("circle",{class:"ring", cx:0, cy:0, r:small?9:16}));
    grp.appendChild(el("circle",{cx:0, cy:0, r:small?3:5}));
    if(!small){ const t=el("text",{x:12, y:-10}); t.textContent=`${a.name} (${Math.round(a.x)}, ${Math.round(a.y)})`; grp.appendChild(t); }
    const target=`translate(${a.x}px, ${-a.y}px)`;
    if(!small && !REDUCED && store[a.name]){ const p=store[a.name]; grp.style.transform=`translate(${p.x}px, ${-p.y}px)`;
      requestAnimationFrame(()=>requestAnimationFrame(()=>{ grp.style.transform=target; })); }
    else grp.style.transform=target;
    store[a.name]={x:a.x, y:a.y};
    svg.appendChild(grp);
  }
  return svg;
}

function renderInspector(){
  const canvas=$("#canvas"), read=$("#readout");
  const g = SELECTED && glyphData(SELECTED);
  if(!g){ canvas.innerHTML='<div class="empty">no glyph selected</div>'; read.innerHTML=""; return; }
  canvas.innerHTML=""; canvas.appendChild(drawGlyph(g,{small:false}));
  read.innerHTML=`<h3>${escapeHtml(g.name)}</h3><div class="sub">adv ${Math.round(g.advance)} · `+
    (g.bounds?`bbox ${g.bounds.map(Math.round).join(" ")}`:"no outline")+`</div>`;
  for(const a of g.anchors){
    const warn = (a.warnings||[]).map(w=>escapeHtml(w)).join("<br>");
    const layerName = (VIEW.layers||[])[a.layer] ?? a.layer;
    const card=document.createElement("div"); card.className="anchor-card"; card.dataset.anchor = a.name;
    const derived = a.derived_from ? "%" + a.derived_from.join(" %") : null;
    card.innerHTML =
      `<div class="nm">${escapeHtml(a.name)}`+
        `${a.propagated?' <span class="tag-prop">propagated</span>':''}`+
        `${derived?` <span class="tag-prop" title="derived from ${escapeHtml(derived)}">↦ ${escapeHtml(derived)}</span>`:''}`+
        `${warn?' <span title="fallback">⚠</span>':''}</div>`+
      `<div class="co">x ${round(a.x)}   y ${round(a.y)}</div>`+
      `<div class="kd">x: ${a.x_kind} · y: ${a.y_kind}</div>`+
      (a.propagated?`<div class="rule">↳ inherited from ${escapeHtml(String(a.from))}</div>`
        :(a.line!=null?`<div class="rule">→ ${escapeHtml(String(layerName))} L${a.line}</div>`:""))+
      (warn?`<div class="wn">${warn}</div>`:"");
    card.addEventListener("click", ()=>{
      highlightAnchor(a.name);
      if(a.line!=null){ activeEd = editorForLayer(a.layer); editorForLayer(a.layer).gotoLine(a.line); }
    });
    read.appendChild(card);
  }
  applyHighlight();
}

function highlightAnchor(name){ HL_ANCHOR = name; applyHighlight(); }
function applyHighlight(){
  for(const gEl of $("#canvas").querySelectorAll(".anchor-g")) gEl.classList.toggle("hl", gEl.dataset.name === HL_ANCHOR);
  for(const card of $("#readout").querySelectorAll(".anchor-card")) card.classList.toggle("sel", card.dataset.anchor === HL_ANCHOR);
}

boot();
