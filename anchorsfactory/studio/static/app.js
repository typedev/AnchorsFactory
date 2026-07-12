"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const REDUCED = matchMedia("(prefers-reduced-motion:reduce)").matches;
const LH = 20, PAD = 14;                     // editor line-height / padding (match app.css)
let META = null, VIEW = {glyphs:{}, layers:[]}, SELECTED = null, GLYPH_FILTER = "", HL_ANCHOR = null;
let GLYPHS = {};                       // last valid glyph view (frozen while rules are invalid)
let GRID_TAB = "anchored";             // "all" | "anchored" | "composites"
let SHOW_UNUSED = false;               // "anchored" tab: also reveal (dimmed) glyphs no rule touched
let ALLGLYPHS = null;                  // [{name,order,advance,bounds,path}] for the "all" tab (lazy)
let ALLMAP = {};                       // name -> all-glyph geometry entry
let COMPOSITES = {};                   // name -> GlyphConstruction-assembled composite (for the "composites" tab)
let UNCOVERED = [];                    // precomposed glyph names the constructions don't build (composites "show uncovered")
let anchorLayers = [];                 // [{name, host, ed}] bottom→top; [0] is the "default" layer
let activeLayer = 0;                   // which anchor layer the tab strip is editing
let gcEd = null, activeEd = null;
let RENDER_MODE = "fill";              // inspector outline style: "fill" | "outline" (grid is always filled)
let ZOOM = 1;                          // inspector preview zoom (grid thumbnails ignore it)
const lastPos = {};                          // glyph -> {anchor -> {x,y}} for tweening

const $ = s => document.querySelector(s);
const el = (n, a={}) => { const e=document.createElementNS(SVGNS,n); for(const k in a) e.setAttribute(k,a[k]); return e; };
const round = v => Math.round(v*10)/10;
const escapeHtml = s => String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const debounce = (fn, ms) => { let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), ms);}; };
const allRulesText = () => anchorLayers.map(l => l.ed.getValue()).join("\n");
const editorForLayer = i => (anchorLayers[i] ? anchorLayers[i].ed : null);

async function boot(){
  META = await (await fetch("/api/state")).json();
  setFontMeta();
  renderFontCards();
  const sel = $("#preset");
  for(const p of META.presets){ const o=document.createElement("option"); o.value=o.textContent=p; sel.appendChild(o); }
  setupEditors();
  setupGrid();
  setupTheme();
  setupFind();
  setupFontDrop();
  setupSplitters();
  setupView();
  $("#outbar").addEventListener("click", () => $("#output").classList.toggle("open"));
  compute();
}

function setFontMeta(){
  let s = `${META.font}  ${META.unitsPerEm}upm  ital ${META.italicAngle}°`;
  if(META.save) s += `  · autosave → ${META.save}`;
  $("#fontmeta").textContent = s;
}

/* ===================================================================== *
 *  Anchor rules: tabbed *layers* that merge bottom→top ([0] = "default").
 *  The active tab is only which layer you edit; compute always sends them all.
 * ===================================================================== */
const persist = debounce(() => {
  try {
    localStorage.setItem("af.rules", JSON.stringify({
      preset: $("#preset").value,
      layers: anchorLayers.map(l => ({name: l.name, text: l.ed.getValue()})),
      active: activeLayer,
    }));
  } catch(_){}
}, 400);

const persistGC = debounce(() => {
  try { localStorage.setItem("af.gc", gcEd.getValue()); } catch(_){}
}, 400);

function renderAnchorTabs(){
  const strip = $("#anchorTabs"); strip.innerHTML = "";
  anchorLayers.forEach((l, idx) => {
    const b = document.createElement("button");
    b.className = "ltab" + (idx === activeLayer ? " sel" : "");
    b.textContent = l.name;
    b.title = idx === 0 ? "default layer (bottom of the merge)" : `layer: ${l.name}`;
    b.addEventListener("click", () => setActiveLayer(idx));
    strip.appendChild(b);
  });
  const add = document.createElement("button");
  add.className = "ltab add"; add.textContent = "+ file";
  add.title = "load another .anchors file as a layer on top";
  add.addEventListener("click", () => $("#rulesfile").click());
  strip.appendChild(add);
}

function setActiveLayer(i){
  activeLayer = Math.max(0, Math.min(anchorLayers.length - 1, i));
  anchorLayers.forEach((l, idx) => l.host.classList.toggle("active", idx === activeLayer));
  activeEd = anchorLayers[activeLayer].ed;
  renderAnchorTabs();
}

function addAnchorLayer(name, text, {activate = false} = {}){
  const host = document.createElement("div");
  host.className = "lhost";
  $("#anchorEditors").appendChild(host);
  const ed = makeEditor(host, () => { persist(); scheduleCompute(); }, () => { activeEd = ed; });
  ed.setValue(text || "");
  const idx = anchorLayers.push({name, host, ed}) - 1;
  if(activate) setActiveLayer(idx); else renderAnchorTabs();
  return idx;
}

function setupEditors(){
  // Construction (GlyphConstruction) editor — single, no tabs.
  gcEd = makeEditor($("#edGC"), () => { persistGC(); scheduleCompute(); }, () => activeEd = gcEd, highlightGC);
  let savedGC = null; try { savedGC = localStorage.getItem("af.gc"); } catch(_){}
  gcEd.setValue(savedGC != null ? savedGC : (META.gc || ""));

  // Anchor layers — restore the saved stack, or seed one "default" layer from the preset.
  let saved = null; try { saved = JSON.parse(localStorage.getItem("af.rules") || "null"); } catch(_){}
  if(saved && Array.isArray(saved.layers) && saved.layers.length){
    $("#preset").value = saved.preset || presetOf(META.rules) || META.presets[0] || "";
    saved.layers.forEach((l, idx) => addAnchorLayer(
      l.name || (idx === 0 ? "default" : `layer ${idx}`),
      // with --save on, the default (bottom) layer is authoritative from disk
      (idx === 0 && META.save) ? META.rules : (l.text || "")));
    setActiveLayer(Number.isInteger(saved.active) ? saved.active : 0);
  } else {
    $("#preset").value = presetOf(META.rules) || META.presets[0] || "";
    addAnchorLayer("default", META.rules);
    setActiveLayer(0);
  }

  // Preset dropdown re-seeds the default (bottom) layer.
  $("#preset").addEventListener("change", e => {
    const t = META.presetTexts[e.target.value];
    if(t !== undefined && anchorLayers[0]){ anchorLayers[0].ed.setValue(t); persist(); compute(); }
  });

  // Pane-head buttons (anchors + construction).
  document.querySelectorAll(".pane-head [data-a]").forEach(btn => {
    btn.addEventListener("click", () => {
      const a = btn.dataset.a;
      if(a === "find"){ activeEd = anchorLayers[activeLayer].ed; openFind(); }
      else if(a === "find-gc"){ activeEd = gcEd; openFind(); }
      else if(a === "dl-anchor"){ const l = anchorLayers[activeLayer]; downloadText(l.ed.getValue(), (l.name || "anchors") + ".anchors"); }
      else if(a === "dl-gc") downloadText(gcEd.getValue(), "constructions.glyphConstruction");
    });
  });

  // + file / open → append a .anchors file as a new layer on top.
  $("#rulesfile").addEventListener("change", async e => {
    const f = e.target.files[0];
    if(f){
      addAnchorLayer(f.name.replace(/\.(anchors|af|dsl|txt)$/i, ""), await f.text(), {activate: true});
      persist(); SELECTED = null; HL_ANCHOR = null; compute();
    }
    e.target.value = "";
  });
}

/* ===================================================================== *
 *  Glyph grid: affected / all-glyphs tabs
 * ===================================================================== */
function persistGrid(){
  try { localStorage.setItem("af.grid", JSON.stringify({tab: GRID_TAB, showUnused: SHOW_UNUSED})); } catch(_){}
}

function setupGrid(){
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("af.grid") || "null"); } catch(_){}
  if(saved){
    GRID_TAB = ["all","composites"].includes(saved.tab) ? saved.tab : "anchored";  // old "affected" → "anchored"
    SHOW_UNUSED = !!saved.showUnused;
  }
  $("#unusedcb").checked = SHOW_UNUSED;
  syncGridChrome();

  document.querySelectorAll("#gridtabs .tab").forEach(btn => {
    btn.addEventListener("click", () => selectTab(btn.dataset.tab));
  });
  $("#unusedcb").addEventListener("change", async e => {
    SHOW_UNUSED = e.target.checked; persistGrid();
    if(SHOW_UNUSED && ALLGLYPHS === null) await fetchAllGlyphs();
    renderGrid();
  });
  const applyFilter = debounce(() => renderGrid(), 120);
  $("#glyphq").addEventListener("input", e => { GLYPH_FILTER = e.target.value.trim(); applyFilter(); });
}

// reflect GRID_TAB in the tab buttons + show the coverage reveal on anchored/composites
function syncGridChrome(){
  document.querySelectorAll("#gridtabs .tab").forEach(b => b.classList.toggle("sel", b.dataset.tab === GRID_TAB));
  $("#unusedwrap").hidden = !(GRID_TAB === "anchored" || GRID_TAB === "composites");
  $("#unusedcb").nextSibling.textContent = GRID_TAB === "composites" ? " show uncovered" : " show unused";
}

async function selectTab(tab){
  if(tab === GRID_TAB) return;
  GRID_TAB = tab; persistGrid(); syncGridChrome();
  if((tab === "all" || ((tab === "anchored" || tab === "composites") && SHOW_UNUSED)) && ALLGLYPHS === null) await fetchAllGlyphs();
  renderGrid();
  // The selection may not exist in the new tab (a glyph name has no composite,
  // or vice-versa) — refresh it and the inspector so the view isn't stale.
  const list = glyphList();
  if(!list.some(g => g.name === SELECTED)) SELECTED = (list[0] || {}).name || null;
  renderInspector();
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

// GlyphConstruction syntax (a different language from the anchor DSL):
//   name = base + mark@anchor [| 0xNN] [^metrics]   ·   $var / {var}   ·   ?skip-if-exists
function highlightGC(line){
  let out = "";
  const hash = line.indexOf("#");
  let code = line, tail = "";
  if(hash >= 0){ code = line.slice(0, hash); tail = line.slice(hash); }
  const re = /(\$\w+|\{\w+\})|(@[\w.]+)|(\?)|(\||\^)|(0x[0-9A-Fa-f]+|\d+)|([A-Za-z_][\w.]*)|(=|\+)/g;
  let m, last = 0;
  const put = (cls, txt) => { out += cls ? `<span class="t-${cls}">${escapeHtml(txt)}</span>` : escapeHtml(txt); };
  while((m = re.exec(code))){
    if(m.index > last) put(null, code.slice(last, m.index));
    const t = m[0];
    if(m[1]) put("var", t);                        // $var / {var}
    else if(m[2]) put("label", t);                 // @anchor
    else if(m[3]) put("dir", t);                    // ? — skip if the glyph exists
    else if(m[4]) put("op", t);                     // | unicode · ^ metrics
    else if(m[5]) put(t.startsWith("0x") ? "uni" : "num", t);
    else if(m[6]) put(null, t);                     // a glyph name → default ink
    else if(m[7]) put("op", t);                     // = · +
    else put(null, t);
    last = re.lastIndex;
  }
  if(last < code.length) put(null, code.slice(last));
  if(tail) put("comment", tail);
  return out || "&nbsp;";
}

function makeEditor(host, onChange, onFocus, highlight = highlightLine){
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
    hl.innerHTML = lines.map((l,i) => `<div class="ln${errLines.has(i+1)?" err":""}">${highlight(l)}</div>`).join("");
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
    consh: {sel:".editor",    axis:"y", sign:-1, min: 80, def:180, max:()=>$(".editor").clientHeight*0.6},
    outh:  {sel:".editor",    axis:"y", sign:-1, min: 44, def:150, max:()=>$(".editor").clientHeight*0.6},
    gridh: {sel:".stage",     axis:"y", sign: 1, min: 90, def:200, max:()=>$(".stage").clientHeight*0.72},
    sidew: {sel:"main",       axis:"x", sign:-1, min:220, def:300, max:()=>innerWidth*0.42},
    fonth: {sel:".sidebar",   axis:"y", sign: 1, min: 80, def:220, max:()=>$(".sidebar").clientHeight*0.7},
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
 *  Font loading: drag a font/.anchors, or pick a file
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
    if(collected.length === 1 && /\.(anchors|af|dsl|txt)$/i.test(collected[0].path)){   // a rules file → a new anchor layer
      const nm = collected[0].path.replace(/.*\//, "").replace(/\.(anchors|af|dsl|txt)$/i, "");
      addAnchorLayer(nm, await collected[0].file.text(), {activate: true});
      persist(); SELECTED = null; HL_ANCHOR = null; compute(); return;
    }
    await sendFont(roots[0].name, collected);
  });
  $("#loadfont").addEventListener("click", () => $("#fontfile").click());
  $("#addfont").addEventListener("click", () => $("#fontfile").click());
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
  Object.assign(META, j.state); setFontMeta(); renderFontCards();
  SELECTED = null; HL_ANCHOR = null; GLYPHS = {};    // the new font becomes active
  ALLGLYPHS = null; ALLMAP = {};                     // …its all-glyphs geometry is fresh
  for(const k in lastPos) delete lastPos[k];
  compute();
}

/* ===================================================================== *
 *  Loaded fonts: cards in the sidebar; the active one drives grid+preview.
 *  Switching keeps SELECTED, so the same glyph re-renders in the new master.
 * ===================================================================== */
function renderFontCards(){
  const box = $("#fontcards"); if(!box) return;
  const fonts = META.fonts || [{name: META.font, unitsPerEm: META.unitsPerEm, italicAngle: META.italicAngle}];
  const active = META.active ?? 0;
  box.innerHTML = "";
  fonts.forEach((f, i) => {
    const card = document.createElement("div");
    card.className = "fontcard" + (i === active ? " sel" : "");
    card.innerHTML =
      `<div class="fc-body"><div class="fc-name">${escapeHtml(f.name)}</div>`+
      `<div class="fc-meta">${Math.round(f.unitsPerEm)}upm · ital ${Math.round(f.italicAngle)}°</div></div>`+
      (fonts.length > 1 ? `<button class="fc-x" title="remove this font">✕</button>` : "");
    card.addEventListener("click", () => { if(i !== active) activateFont(i); });
    const x = card.querySelector(".fc-x");
    if(x) x.addEventListener("click", e => { e.stopPropagation(); removeFont(i); });
    box.appendChild(card);
  });
}

async function fontOp(url, index){
  let j; try {
    j = await (await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({index})})).json();
  } catch(_){ j = {ok:false}; }
  if(!j.ok || !j.state) return null;
  Object.assign(META, j.state); setFontMeta(); renderFontCards();
  ALLGLYPHS = null; ALLMAP = {};                     // the active font changed → fresh geometry
  for(const k in lastPos) delete lastPos[k];
  return j;
}

async function activateFont(i){
  const status = $("#status"); status.className="pill"; status.textContent="switching font…";
  if(await fontOp("/api/font/activate", i)) compute();   // keep SELECTED → same glyph, new master
}

async function removeFont(i){
  if(await fontOp("/api/font/remove", i)){ if(!GLYPHS[SELECTED]){ SELECTED=null; HL_ANCHOR=null; } GLYPHS={}; compute(); }
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
  const layers = anchorLayers.map(l => ({name: l.name, text: l.ed.getValue()}));
  const gc = gcEd ? gcEd.getValue() : "";
  try {
    const res = await fetch("/api/compute", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({layers, gc})});
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
    COMPOSITES = VIEW.composites || {};
    UNCOVERED = VIEW.uncovered || [];
    stage.classList.remove("stale");
    renderGrid();
    if(GRID_TAB === "composites"){
      if(!COMPOSITES[SELECTED] && !(SHOW_UNUSED && UNCOVERED.includes(SELECTED)))
        SELECTED = (compositeList()[0] || {}).name || null;
    } else if(!glyphData(SELECTED)){
      SELECTED = (sortedGlyphs()[0] || {}).name || null;
    }
    renderInspector();
  } else {
    stage.classList.add("stale");                   // show it's frozen, not live
  }
  const bad = !VIEW.ok || (VIEW.diagnostics||[]).some(d=>d.severity==="error");
  status.className = "pill " + (bad ? "bad" : "ok");
  status.textContent = VIEW.ok ? (VIEW.diagnostics.length ? `ok · ${VIEW.diagnostics.length} notes` : "ok")
                               : `${VIEW.problems.length} problem${VIEW.problems.length>1?"s":""}`;
}

// "<layer>: line 3: ..." / "line 3: ..." → {layer index, line} (layer by name)
function problemLoc(p){
  let m = /^([^:]+): line (\d+):/.exec(p);
  if(m){ const idx = anchorLayers.findIndex(l => l.name === m[1]); if(idx >= 0) return {layer: idx, line: +m[2]}; }
  m = /^line (\d+):/.exec(p);
  return m ? {layer: 0, line: +m[1]} : null;
}

function markErrorLines(){
  const sets = anchorLayers.map(() => new Set());
  for(const p of VIEW.problems||[]){ const loc = problemLoc(p); if(loc && sets[loc.layer]) sets[loc.layer].add(loc.line); }
  anchorLayers.forEach((l, idx) => l.ed.markErrors(sets[idx]));
}

function renderProblems(){
  const box = $("#problems"); box.innerHTML = "";
  const probs = VIEW.problems||[], diags = VIEW.diagnostics||[];
  const errs = probs.length + diags.filter(d=>d.severity==="error").length;
  const cnt = $("#outcount");
  if(cnt){ cnt.textContent = (probs.length+diags.length) || ""; cnt.classList.toggle("bad", errs>0); }
  // Collapsible output: sleeps when clean, auto-wakes + reddens on real problems
  // (mere notes keep it collapsed but bump the count badge).
  const out = $("#output");
  out.classList.toggle("bad", errs>0);
  out.classList.toggle("open", errs>0);
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

// The glyphs to show for the active tab. "anchored" lists the glyphs some rule
// placed an anchor on; with "show unused" (or the "all" tab) the whole font is
// shown, affected glyphs keeping their anchors/overlays and the rest drawn dimmed.
function glyphList(){
  if(GRID_TAB === "composites"){
    if(!SHOW_UNUSED) return compositeList();
    // reveal precomposed glyphs no construction builds (from the full-font geometry)
    const gap = UNCOVERED.map(n => ALLMAP[n]).filter(Boolean).map(g => ({...g, anchors: [], uncovered: true}));
    return compositeList().concat(gap.sort(_bySort));
  }
  if(GRID_TAB === "anchored" && !SHOW_UNUSED) return sortedGlyphs();
  return (ALLGLYPHS || []).map(g => GLYPHS[g.name] || {...g, anchors: []}).sort(_bySort);
}

function compositeList(){
  return Object.values(COMPOSITES).sort((a,b)=> a.name<b.name?-1:a.name>b.name?1:0);
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
        holder.appendChild(e.target._composite
          ? drawComposite(e.target._glyph, {small:true})
          : drawGlyph(e.target._glyph, {small:true}));
      }
    }
  }, {root: $(".gridwrap"), rootMargin: "250px"});
  return gridObserver;
}

function setGridCount(shown, total, filtered){
  const label = GRID_TAB === "composites" ? (SHOW_UNUSED ? "composites + uncovered" : "composites")
              : GRID_TAB === "all" ? "all"
              : (SHOW_UNUSED ? "anchored + unused" : "anchored");
  $("#count").textContent = `${label} · ` + (filtered ? `${shown}/${total}` : total);
}

function renderGrid(){
  const needsAll = GRID_TAB === "all" || ((GRID_TAB === "anchored" || GRID_TAB === "composites") && SHOW_UNUSED);
  if(needsAll && ALLGLYPHS === null){ fetchAllGlyphs().then(renderGrid); return; }
  const grid = $("#grid"); grid.innerHTML="";
  const obs = ensureObserver(); obs.disconnect();     // stop watching the old cards
  const all = glyphList();
  const f = GLYPH_FILTER.toLowerCase();
  const shown = f ? all.filter(g => g.name.toLowerCase().includes(f)) : all;
  setGridCount(shown.length, all.length, !!f);
  for(const g of shown){
    const isComp = !!g.components;                     // a built composite (vs an uncovered/plain glyph)
    // dimmed: "anchored + unused" untouched glyphs, or "composites + uncovered" gaps
    const dim = (GRID_TAB === "anchored" && !GLYPHS[g.name]) || g.uncovered;
    const card = document.createElement("div"); card.className = "thumb" + (g.name===SELECTED?" sel":"") + (dim?" unused":"");
    card._glyph = g; card._composite = isComp;
    const holder = document.createElement("div"); holder.className = "holder ph"; card.appendChild(holder);
    const capRight = g.uncovered
      ? `<span title="no construction builds this">—</span>`
      : isComp
        ? ((g.problems && g.problems.length)
            ? `<span class="warn" title="${escapeHtml(g.problems.join('; '))}">⚠</span>`
            : `<span>${g.components.length}</span>`)
        : `<span>${g.anchors.length}</span>`;
    card.insertAdjacentHTML("beforeend", `<div class="cap"><b>${escapeHtml(g.name)}</b>${capRight}</div>`);
    card.addEventListener("click", ()=>{ SELECTED=g.name; HL_ANCHOR=null; renderGrid(); renderInspector(); });
    grid.appendChild(card);
    obs.observe(card);
  }
}

// Horizontal ink centre of a glyph/composite (falls back to the advance midpoint).
function inkMidX(g){
  if(g.bounds) return (g.bounds[0]+g.bounds[2])/2;
  return (g.advance || META.unitsPerEm/2)/2;
}

// Grid cell geometry (mirrors `.thumb` / `.thumb svg` in app.css): every
// thumbnail viewport is this fixed pixel size, so a shared viewBox → a shared scale.
const THUMB_W = 80, THUMB_H = 88;
// Fraction of the (metric-based) window the glyph fills — <1 leaves breathing room.
// The glyph's on-screen size is ∝ THUMB_H * THUMB_FILL, so when the cell grows we
// drop FILL to keep the glyph the same size (88*0.84 ≈ the old 82*0.90 = 73.8px):
// bigger, roomier cells, same-size glyph.
const THUMB_FILL = 0.84;

// A *fixed*, em-based viewBox for grid thumbnails — the thumbnail analogue of
// stableViewBox. The vertical window is the font's metric span (descender→ascender
// + headroom for stacked marks), identical for every cell, so the baseline lands
// at the same screen Y and glyphs don't jump between a bottom-accent and a
// top-accent neighbour. W/H are constant across cells, so — with the fixed cell
// viewport — every glyph shares one scale, and because the span is the font's em
// that scale is UPM-relative (consistent across fonts of different UPM). Only the
// horizontal centre follows each glyph's ink.
function thumbViewBox(midX){
  const m = META.metrics;
  const asc = (m.ascender != null ? m.ascender : Math.round(META.unitsPerEm*0.8));
  const desc = (m.descender != null ? m.descender : -Math.round(META.unitsPerEm*0.2));
  const span = asc - desc;
  const yTop = asc + span*0.26, yBot = desc - span*0.08;   // headroom for stacked marks / descenders
  const yc = (yTop + yBot)/2, hy = yTop - yBot;
  const H = hy / THUMB_FILL;                                // enlarge the window → glyphs fill THUMB_FILL of it
  const W = H * (THUMB_W/THUMB_H);                          // match the cell's aspect (no letterbox)
  return {x0: midX - W/2, y0: -(yc + H/2), W, H};          // screen coords (Y points down), centred on yc
}

// A *fixed* viewBox for the inspector: the vertical window is metric-based
// (descender→ascender + padding) and identical for every glyph, so the baseline
// and scale never jump between selections; only the horizontal centre follows the
// glyph. Aspect-matched to the canvas so `meet` maps 1:1 (no letterbox rescaling),
// and divided by ZOOM around the centre.
function stableViewBox(midX, canvasEl){
  const m = META.metrics;
  const asc = (m.ascender != null ? m.ascender : Math.round(META.unitsPerEm*0.8));
  const desc = (m.descender != null ? m.descender : -Math.round(META.unitsPerEm*0.2));
  // Asymmetric headroom: extra room on top so a mark stacked above the ascender
  // (an accented composite) and the anchor labels aren't clipped by the top edge.
  const span = asc - desc;
  const yTop = asc + span * 0.34, yBot = desc - span * 0.14;
  const yc = (yTop + yBot)/2, hy = yTop - yBot;
  const cw = (canvasEl && canvasEl.clientWidth) || 600;
  const ch = (canvasEl && canvasEl.clientHeight) || 600;
  const wx = hy * (cw/ch);
  const z = ZOOM || 1, H = hy/z, W = wx/z;
  return {x0: midX - W/2, y0: -yc - H/2, W, H};   // screen coords (Y points down)
}

// Outline class for a path: filled ink, or a stroked outline (marks tinted).
function inkClass(mark){ return RENDER_MODE === "outline" ? ("ink-outline" + (mark?" mark":"")) : "ink"; }

// Replace the canvas artwork but keep the tools overlay (#ctools).
function clearCanvas(canvas){
  for(const n of [...canvas.children]) if(n.id !== "ctools") n.remove();
}

const persistView = () => { try { localStorage.setItem("af.view", JSON.stringify({mode: RENDER_MODE, zoom: ZOOM})); } catch(_){} };
function syncView(){
  const mb = $("#ctools [data-v='mode']"); if(mb) mb.textContent = RENDER_MODE;
  const zl = $("#zoomlbl"); if(zl) zl.textContent = Math.round(ZOOM*100) + "%";
}
const scheduleInspector = debounce(() => renderInspector(), 40);

function setupView(){
  let saved=null; try { saved = JSON.parse(localStorage.getItem("af.view") || "null"); } catch(_){}
  if(saved){ RENDER_MODE = saved.mode === "outline" ? "outline" : "fill"; ZOOM = +saved.zoom || 1; }
  const setZoom = z => { ZOOM = Math.max(0.4, Math.min(6, z)); persistView(); syncView(); };
  $("#ctools").addEventListener("click", e => {
    const b = e.target.closest("[data-v]"); if(!b) return;
    const v = b.dataset.v;
    if(v === "mode") RENDER_MODE = RENDER_MODE === "fill" ? "outline" : "fill";
    else if(v === "zoom-in") setZoom(ZOOM*1.25);
    else if(v === "zoom-out") setZoom(ZOOM/1.25);
    else if(v === "zoom-reset") ZOOM = 1;
    persistView(); syncView(); renderInspector();
  });
  const cv = $("#canvas");
  cv.addEventListener("wheel", e => {
    if(!SELECTED) return;
    e.preventDefault();
    setZoom(ZOOM * (e.deltaY < 0 ? 1.1 : 1/1.1));
    scheduleInspector();
  }, {passive:false});
  // The stable viewBox is aspect-matched to the canvas, so re-render on resize.
  if(window.ResizeObserver) new ResizeObserver(debounce(() => renderInspector(), 120)).observe(cv);
  syncView();
}

function drawGlyph(g, {small=false, canvasEl=null}={}){
  let x0, minY, W, H;
  if(small){                                   // thumbnail: fixed em-based window (shared scale + baseline)
    const vb = thumbViewBox(inkMidX(g)); x0=vb.x0; minY=vb.y0; W=vb.W; H=vb.H;
  } else {                                      // inspector: fixed metric window (stable) + zoom
    const vb = stableViewBox(inkMidX(g), canvasEl); x0=vb.x0; minY=vb.y0; W=vb.W; H=vb.H;
  }
  const svg = el("svg", {viewBox:`${x0} ${minY} ${W} ${H}`, preserveAspectRatio:"xMidYMid meet"});
  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){ const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      const t=el("text",{class:"metric-lbl", x:x0+6, y:-h-4}); t.textContent=lbl; svg.appendChild(t); }
    if(g.bounds){ const [bx0,by0,bx1,by1]=g.bounds; svg.appendChild(el("rect",{class:"bbox", x:bx0, y:-by1, width:bx1-bx0, height:by1-by0})); }
  }
  const flip = el("g",{transform:"matrix(1 0 0 -1 0 0)"});
  flip.appendChild(el("path",{class: small ? "ink" : inkClass(false), d:g.path})); svg.appendChild(flip);
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

// A GlyphConstruction-assembled composite: each component outline drawn under its
// own transform, plus a ring at each anchor-join (where a mark's `_anchor` snapped
// onto the base's `anchor`). Grid thumbnails are always filled; the inspector
// follows the fill/outline mode (in outline, marks are tinted).
function drawComposite(c, {small=false, canvasEl=null}={}){
  let x0, minY, W, H;
  if(small){
    const vb = thumbViewBox(inkMidX({bounds:c.bounds, advance:c.advance})); x0=vb.x0; minY=vb.y0; W=vb.W; H=vb.H;
  } else {
    const vb = stableViewBox(inkMidX({bounds:c.bounds, advance:c.advance}), canvasEl); x0=vb.x0; minY=vb.y0; W=vb.W; H=vb.H;
  }
  const svg = el("svg", {viewBox:`${x0} ${minY} ${W} ${H}`, preserveAspectRatio:"xMidYMid meet"});
  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){ const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      const t=el("text",{class:"metric-lbl", x:x0+6, y:-h-4}); t.textContent=lbl; svg.appendChild(t); }
  }
  const flip = el("g",{transform:"matrix(1 0 0 -1 0 0)"});
  (c.components||[]).forEach((comp, i) => {
    const grp = el("g",{transform:`matrix(${comp.transform.join(" ")})`});
    grp.appendChild(el("path",{class: small ? "ink" : inkClass(i>0), d: comp.path}));
    flip.appendChild(grp);
  });
  svg.appendChild(flip);
  if(!small){
    for(const j of (c.joins||[])){
      const grp = el("g",{class:"join-g"});
      grp.appendChild(el("circle",{cx:j.x, cy:-j.y, r:14}));
      grp.appendChild(el("circle",{class:"dot", cx:j.x, cy:-j.y, r:4}));
      const t=el("text",{x:j.x+12, y:-j.y-10}); t.textContent=j.anchor; grp.appendChild(t);
      svg.appendChild(grp);
    }
  }
  return svg;
}

function renderCompositeInspector(canvas, read){
  const c = SELECTED && COMPOSITES[SELECTED];
  clearCanvas(canvas);
  if(!c){
    const g = SELECTED && glyphData(SELECTED);        // an "uncovered" precomposed glyph
    if(g){
      canvas.appendChild(drawGlyph(g, {small:false, canvasEl:canvas}));
      read.innerHTML = `<h3>${escapeHtml(g.name)}</h3><div class="sub">uncovered · no construction builds this</div>`;
    } else {
      canvas.insertAdjacentHTML("beforeend", '<div class="empty">no composite selected</div>');
      read.innerHTML = "";
    }
    return;
  }
  canvas.appendChild(drawComposite(c,{small:false, canvasEl:canvas}));
  let html = `<h3>${escapeHtml(c.name)}</h3><div class="sub">adv ${Math.round(c.advance)} · `+
    `${c.components.length} component${c.components.length!==1?"s":""}</div>`;
  // click-to-rule: jump the Construction editor to the line that builds this composite
  if(c.line!=null)
    html += `<div class="rule" data-gcline="${c.line}">→ construction L${c.line}</div>`;
  if(c.problems && c.problems.length)
    html += `<div class="comp-problems">`+ c.problems.map(p=>"⚠ "+escapeHtml(p)).join("<br>") +`</div>`;
  html += c.components.map((comp,i)=>
    `<div class="comp-row"><span class="b">${escapeHtml(comp.base)}</span>${i===0?' <span class="j">base</span>':''}</div>`).join("");
  html += (c.joins||[]).map(j=>
    `<div class="comp-row">↦ <span class="j">${escapeHtml(j.anchor)}</span> at ${Math.round(j.x)}, ${Math.round(j.y)}</div>`).join("");
  read.innerHTML = html;
  const jump = read.querySelector(".rule[data-gcline]");
  if(jump && gcEd) jump.addEventListener("click", ()=>{ activeEd = gcEd; gcEd.gotoLine(+jump.dataset.gcline); });
}

function renderInspector(){
  const canvas=$("#canvas"), read=$("#readout");
  if(GRID_TAB === "composites"){ renderCompositeInspector(canvas, read); return; }
  const g = SELECTED && glyphData(SELECTED);
  clearCanvas(canvas);
  if(!g){ canvas.insertAdjacentHTML("beforeend", '<div class="empty">no glyph selected</div>'); read.innerHTML=""; return; }
  canvas.appendChild(drawGlyph(g,{small:false, canvasEl:canvas}));
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
