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
let gcLayers = [], activeGc = 0;        // construction tabs (concatenated for the engine)
let activeEd = null;
let projectDir = null;                 // the opened folder's handle (Chromium), for Save as
let RENDER_MODE = "fill";              // inspector outline style: "fill" | "outline" (grid is always filled)
let ZOOM = 1;                          // inspector preview zoom (grid thumbnails ignore it)
const lastPos = {};                          // glyph -> {anchor -> {x,y}} for tweening

const $ = s => document.querySelector(s);
const el = (n, a={}) => { const e=document.createElementNS(SVGNS,n); for(const k in a) e.setAttribute(k,a[k]); return e; };
const round = v => Math.round(v*10)/10;
const escapeHtml = s => String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const debounce = (fn, ms) => { let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), ms);}; };
const allRulesText = () => anchorLayers.map(l => l.ed.getValue()).join("\n");
// layer index -1 is the constructions editor (problems prefixed "constructions:")
const editorForLayer = i => (i === -1 ? (gcLayers[activeGc] || {}).ed : anchorLayers[i] ? anchorLayers[i].ed : null);
// the anchor layers as compute sends them (a file's name makes it an !extends target)
const sentLayers = () => anchorLayers.map(l => ({name: l.name, text: l.ed.getValue(), ...(l.file ? {file: l.file.name} : {})}));
// jump to a problem / rule line: layer -1 is the constructions (a line of the concatenated text)
function gotoLoc(layer, line){
  if(layer === -1) return gcGoto(line);
  const ed = editorForLayer(layer); if(!ed) return;
  setActiveLayer(layer); activeEd = ed; ed.gotoLine(line);
}

async function boot(){
  const status = $("#status");
  studioApi.onStatus(text => { status.className = "pill"; status.textContent = text; });
  // the web start screen and its drop zone work while Python is still loading
  if(studioApi.kind === "worker") showStart();
  setupFontDrop();
  try { META = await studioApi.call("state"); }
  catch(err){ status.className = "pill bad"; status.textContent = "failed to start";
    $("#fontmeta").textContent = String(err.message || err); throw err; }
  initVocabulary(META.vocabulary);
  setFontMeta();
  renderFontCards();
  const sel = $("#preset");
  for(const p of META.presets){ const o=document.createElement("option"); o.value=o.textContent=p; sel.appendChild(o); }
  setupEditors();
  setupGrid();
  setupTheme();
  setupFind();
  setupSplitters();
  setupView();
  $("#outbar").addEventListener("click", () => $("#output").classList.toggle("open"));
  $("#compareMasters").addEventListener("click", compareMasters);
  // locally, the start screen only when no font was given (the demo is up)
  if(studioApi.kind !== "worker" && META.font === "demo" && (META.fonts || []).length <= 1) showStart();
  compute();
  bootResolve();
}

function setFontMeta(){
  let s = placeholderFont ? "" : `${META.font}  ${META.unitsPerEm}upm  ital ${META.italicAngle}°`;
  if(META.save) s += `  · autosave → ${META.save}`;
  if(studioApi.kind === "worker") s += `${s ? "  · " : ""}v${META.version}, runs in this tab: fonts are not uploaded`;
  $("#fontmeta").textContent = s;
}

/* ===================================================================== *
 *  Rules: tabbed *layers*. Anchors merge bottom→top ([0] = "default");
 *  constructions are concatenated in tab order (later definitions win).
 *  The active tab is only which layer you edit; compute always sends them all.
 *  A layer opened from a file (the project folder, a picker, a drop) keeps
 *  `file = {name, handle, saved}`: Save writes back to it, and an .anchors
 *  file's name is a set `!extends` can inherit.
 * ===================================================================== */
const persist = debounce(() => {
  try {
    localStorage.setItem("af.rules", JSON.stringify({
      preset: $("#preset").value,
      layers: anchorLayers.map(l => ({name: l.name, text: l.ed.getValue(), file: l.file ? l.file.name : null})),
      active: activeLayer,
    }));
  } catch(_){}
}, 400);

const persistGC = debounce(() => {
  try {
    localStorage.setItem("af.gc", JSON.stringify({
      layers: gcLayers.map(l => ({name: l.name, text: l.ed.getValue(), file: l.file ? l.file.name : null})),
      active: activeGc,
    }));
  } catch(_){}
}, 400);

const STACKS = {
  anchors: {ext: ".anchors", strip: "#anchorTabs", hosts: "#anchorEditors",
            layers: () => anchorLayers, active: () => activeLayer, persist: () => persist()},
  gc:      {ext: ".glyphsConstruction", strip: "#gcTabs", hosts: "#edGC",
            layers: () => gcLayers, active: () => activeGc, persist: () => persistGC()},
};
const isDirty = l => !!(l.file && l.file.saved != null && l.ed.getValue() !== l.file.saved);

function renderTabs(kind){
  const st = STACKS[kind], layers = st.layers(), strip = $(st.strip); strip.innerHTML = "";
  layers.forEach((l, idx) => {
    const b = document.createElement("button");
    b.className = "ltab" + (idx === st.active() ? " sel" : "") + (isDirty(l) ? " dirty" : "");
    b.textContent = l.name;
    b.title = (kind === "anchors" && idx === 0 ? "default layer (bottom of the merge)" : `layer: ${l.name}`) +
      (l.file ? `\nfile: ${l.file.name}${l.file.handle ? "" : " (not linked: Save asks where)"}` : "");
    b.addEventListener("click", () => setActive(kind, idx));
    const closable = kind === "anchors" ? idx > 0 : layers.length > 1;
    if(closable){
      const x = document.createElement("span"); x.className = "lclose"; x.textContent = "×"; x.title = "close this layer";
      x.addEventListener("click", e => { e.stopPropagation(); closeLayer(kind, idx); });
      b.appendChild(x);
    }
    strip.appendChild(b);
  });
  const add = document.createElement("button");
  add.className = "ltab add"; add.textContent = "+ file";
  add.title = `open another ${st.ext} file as a layer on top`;
  add.addEventListener("click", () => openRulesFile(kind));
  strip.appendChild(add);
}
const renderAnchorTabs = () => renderTabs("anchors");

function setActive(kind, i){
  const layers = STACKS[kind].layers();
  i = Math.max(0, Math.min(layers.length - 1, i));
  if(kind === "anchors") activeLayer = i; else activeGc = i;
  layers.forEach((l, idx) => l.host.classList.toggle("active", idx === i));
  activeEd = layers[i].ed;
  renderTabs(kind);
}
const setActiveLayer = i => setActive("anchors", i);

function addLayer(kind, name, text, {activate = false, file = null} = {}){
  const st = STACKS[kind], layers = st.layers();
  const host = document.createElement("div");
  host.className = "lhost";
  $(st.hosts).appendChild(host);
  const onChange = () => { st.persist(); scheduleCompute(); syncDirty(kind); };
  const ed = kind === "anchors"
    ? makeEditor(host, onChange, () => { activeEd = ed; })
    : makeEditor(host, onChange, () => { activeEd = ed; }, highlightGC, GC_COMPLETE);
  ed.setValue(text || "");
  const idx = layers.push({name, host, ed, file}) - 1;
  if(activate) setActive(kind, idx); else renderTabs(kind);
  return idx;
}
const addAnchorLayer = (name, text, opts) => addLayer("anchors", name, text, opts);

// the dirty dot only flips on the first edit after a save, so re-render then
const syncDirty = debounce(kind => {
  const strip = $(STACKS[kind].strip);
  STACKS[kind].layers().forEach((l, idx) => { const b = strip.children[idx]; if(b) b.classList.toggle("dirty", isDirty(l)); });
}, 150);

function closeLayer(kind, idx){
  const st = STACKS[kind], layers = st.layers(), l = layers[idx];
  if(isDirty(l) && !confirm(`${l.name} has unsaved changes. Close it anyway?`)) return;
  l.host.remove(); layers.splice(idx, 1);
  const active = st.active();
  setActive(kind, active > idx ? active - 1 : Math.min(active, layers.length - 1));
  st.persist(); SELECTED = null; HL_ANCHOR = null; compute();
}

/** Add a rules file as a layer, or refresh the layer already opened from it. */
function addRulesLayer(kind, name, text, file, {activate = true} = {}){
  const st = STACKS[kind], layers = st.layers();
  const stem = name.replace(/\.(anchors|af|dsl|txt|glyphsConstruction|glyphConstruction)$/i, "");
  const same = layers.findIndex(l => l.file && l.file.name === name);
  file = file ? {...file, name, saved: text} : null;
  if(same >= 0){ layers[same].ed.setValue(text); layers[same].file = file; if(activate) setActive(kind, same); else renderTabs(kind); }
  else addLayer(kind, stem, text, {activate, file});
  st.persist();
}

const GC_FILE = /\.glyphs?Construction$/i;
const kindOf = name => GC_FILE.test(name) ? "gc" : RULES_FILE.test(name) ? "anchors" : null;

/** "+ file": a file picker that links the file (Chromium), else an <input>. */
async function openRulesFile(kind){
  if(!window.showOpenFilePicker){ $("#rulesfile").dataset.kind = kind; $("#rulesfile").click(); return; }
  let handles;
  try { handles = await showOpenFilePicker({id: "rules", multiple: true, types: [{description: "rules",
    accept: {"text/plain": kind === "gc" ? [".glyphsConstruction", ".glyphConstruction", ".txt"] : [".anchors", ".af", ".dsl", ".txt"]}}]}); }
  catch(_){ return; }
  for(const h of handles){
    const text = await (await h.getFile()).text();
    addRulesLayer(kindOf(h.name) || kind, h.name, text, {handle: h});
  }
  SELECTED = null; HL_ANCHOR = null; compute();
}

/** Save a layer back to its file; with no linked file, ask where (or download). */
async function saveLayer(kind){
  const st = STACKS[kind], l = st.layers()[st.active()]; if(!l) return;
  const text = l.ed.getValue(), status = $("#status");
  let handle = l.file && l.file.handle;
  try {
    if(handle && (await handle.queryPermission({mode: "readwrite"})) !== "granted"
       && (await handle.requestPermission({mode: "readwrite"})) !== "granted") handle = null;
    if(!handle){
      if(!window.showSaveFilePicker){ downloadText(text, (l.file ? l.file.name : l.name + st.ext)); return; }
      try {
        handle = await showSaveFilePicker({id: "rules", suggestedName: l.file ? l.file.name : l.name + st.ext,
          ...(projectDir ? {startIn: projectDir} : {}),
          types: [{description: "rules", accept: {"text/plain": [st.ext]}}]});
      } catch(_){ return; }                          // the picker was dismissed
    }
    const w = await handle.createWritable(); await w.write(text); await w.close();
    l.file = {name: handle.name, handle, saved: text};
    if(kind === "anchors" && handle.name.toLowerCase().endsWith(".anchors")) l.name = handle.name.replace(/\.anchors$/i, "");
    renderTabs(kind); st.persist();
    status.className = "pill ok"; status.textContent = `saved ${handle.name}`;
    if(kind === "anchors") compute();                // the file name may now be an !extends target
  } catch(err){
    status.className = "pill bad"; status.textContent = "save failed";
    $("#problems").innerHTML = `<div class="row err"><span class="tag">save</span><span>${escapeHtml(String(err.message || err))}</span></div>`;
  }
}

function activeKind(){ return gcLayers.some(l => l.ed === activeEd) ? "gc" : "anchors"; }

/* -- constructions: one text for the engine, lines mapped back to tabs ---- */

function gcCombined(){
  const starts = []; let line = 1;
  const text = gcLayers.map(l => { const t = l.ed.getValue(); starts.push(line); line += t.split("\n").length; return t; }).join("\n");
  return {text, starts};
}
function gcLocate(line){
  const {starts} = gcCombined();
  let i = starts.length - 1; while(i > 0 && starts[i] > line) i--;
  return {idx: i, line: line - starts[i] + 1};
}
function gcGoto(line){
  const {idx, line: local} = gcLocate(line);
  setActive("gc", idx); activeEd = gcLayers[idx].ed; gcLayers[idx].ed.gotoLine(local);
}
function gcSplitLines(lines){
  const {starts} = gcCombined(), sets = gcLayers.map(() => new Set());
  for(const n of lines){ let i = starts.length - 1; while(i > 0 && starts[i] > n) i--; sets[i].add(n - starts[i] + 1); }
  return sets;
}

/** The project folder's rules: every .anchors / .glyphsConstruction at its top. */
async function loadProjectRules(nodes, dir){
  projectDir = dir || null;
  const files = [];
  for(const n of nodes){
    const kind = kindOf(n.name); if(!kind || kind === "anchors" && !/\.anchors$/i.test(n.name)) continue;
    try { files.push({kind, name: n.name, text: await (await readRetrying(n.file, n.name)).text()}); }
    catch(err){ /* an unreadable rules file is skipped, the font still opens */ }
  }
  if(!files.length) return [];
  // anchors: bases before the files that `!extends` them, else by name
  const anchors = files.filter(f => f.kind === "anchors").sort((a, b) => a.name.localeCompare(b.name));
  const stem = f => f.name.replace(/\.anchors$/i, "");
  const order = [], seen = new Set();
  const visit = (f, path = new Set()) => {
    if(seen.has(f) || path.has(f)) return; path.add(f);
    for(const m of f.text.matchAll(/^\s*!extends\s+(.+)$/gm))
      for(const ref of m[1].split(/[\s,]+/)){ const base = anchors.find(g => stem(g) === ref && g !== f); if(base) visit(base, path); }
    seen.add(f); order.push(f);
  };
  anchors.forEach(f => visit(f));
  const gcs = files.filter(f => f.kind === "gc").sort((a, b) => a.name.localeCompare(b.name));
  for(const f of [...order, ...gcs]){
    const handle = dir ? await dir.getFileHandle(f.name).catch(() => null) : null;
    addRulesLayer(f.kind, f.name, f.text, {handle}, {activate: false});
  }
  if(order.length) setActive("anchors", anchorLayers.findIndex(l => l.file && l.file.name === order[order.length - 1].name));
  if(gcs.length) setActive("gc", gcLayers.findIndex(l => l.file && l.file.name === gcs[gcs.length - 1].name));
  return files.map(f => f.name);
}

function setupEditors(){
  // Constructions (GlyphConstruction): tabs, concatenated for the engine.
  let savedGC = null; try { savedGC = localStorage.getItem("af.gc"); } catch(_){}
  let gcState = null; try { gcState = JSON.parse(savedGC); } catch(_){ gcState = null; }
  if(gcState && Array.isArray(gcState.layers) && gcState.layers.length){
    gcState.layers.forEach(l => addLayer("gc", l.name || "constructions", l.text || "",
                                         {file: l.file ? {name: l.file, handle: null, saved: null} : null}));
    setActive("gc", Number.isInteger(gcState.active) ? gcState.active : 0);
  } else {                                           // older sessions kept one plain text
    addLayer("gc", "constructions", typeof savedGC === "string" && !gcState ? savedGC : (META.gc || ""));
    setActive("gc", 0);
  }

  // Anchor layers — restore the saved stack, or seed one "default" layer from the preset.
  let saved = null; try { saved = JSON.parse(localStorage.getItem("af.rules") || "null"); } catch(_){}
  if(saved && Array.isArray(saved.layers) && saved.layers.length){
    $("#preset").value = saved.preset || presetOf(META.rules) || META.presets[0] || "";
    saved.layers.forEach((l, idx) => addAnchorLayer(
      l.name || (idx === 0 ? "default" : `layer ${idx}`),
      // with --save on, the default (bottom) layer is authoritative from disk
      (idx === 0 && META.save) ? META.rules : (l.text || ""),
      {file: l.file ? {name: l.file, handle: null, saved: null} : null}));
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
      else if(a === "find-gc"){ activeEd = gcLayers[activeGc].ed; openFind(); }
      else if(a === "save-anchor") saveLayer("anchors");
      else if(a === "save-gc") saveLayer("gc");
      else if(a === "dl-anchor"){ const l = anchorLayers[activeLayer]; downloadText(l.ed.getValue(), l.file ? l.file.name : (l.name || "anchors") + ".anchors"); }
      else if(a === "dl-gc"){ const l = gcLayers[activeGc]; downloadText(l.ed.getValue(), l.file ? l.file.name : (l.name || "constructions") + ".glyphsConstruction"); }
    });
  });
  // Ctrl/Cmd+S saves the layer being edited.
  addEventListener("keydown", e => {
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s"){ e.preventDefault(); saveLayer(activeKind()); }
  });

  // "+ file" without a file picker API: an <input>, not linked (Save asks where).
  $("#rulesfile").addEventListener("change", async e => {
    const kind = e.target.dataset.kind || "anchors";
    for(const f of [...e.target.files]) addRulesLayer(kindOf(f.name) || kind, f.name, await f.text(), {handle: null});
    e.target.value = "";
    SELECTED = null; HL_ANCHOR = null; compute();
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
    const j = await studioApi.call("allglyphs");
    ALLGLYPHS = j.glyphs || [];
  } catch(err){ ALLGLYPHS = []; }
  ALLMAP = {}; for(const g of ALLGLYPHS) ALLMAP[g.name] = g;
}

const scheduleCompute = debounce(() => compute(), 300);
function presetOf(text){ return META.presets.find(p => META.presetTexts[p] === text) || ""; }

/* ---- a code editor bound to a host element (one per layer) ---- */
// The DSL vocabulary is not spelled here: the server sends it from
// anchorsfactory.vocabulary (the same tables the parser itself is built from),
// so highlighting and completion cannot drift from what the parser accepts.
let KW = new Set(), METRICS = [], METRIC_SET = new Set(), DIRECTIVES = new Set(),
    FRAMES = [], ALIGNS = [], EDGES = [], RUNS = [], RUN_SET = new Set(),
    CENTROID = "centroid", AFTER_DOT = {}, FOR_SLOT = {}, FRAME_SET = new Set(),
    COMP_HEAD_RE = /^comp(\d+|last)$/,
    COND_DIRS = new Set(), COND_KW = [], COND_FIELDS = [], AXIS_KINDS = [];
let CHAR_W = 0;

function initVocabulary(v){
  FRAMES = v.frames; ALIGNS = v.xAligns; EDGES = v.yEdges; RUNS = v.runs;
  METRICS = v.metrics; CENTROID = v.centroid; AFTER_DOT = v.completionsAfterDot;
  FOR_SLOT = v.completionsForSlot;
  RUN_SET = new Set(RUNS); FRAME_SET = new Set(FRAMES);
  METRIC_SET = new Set(METRICS);
  DIRECTIVES = new Set(v.directives);
  KW = new Set([...FRAMES, ...ALIGNS, ...EDGES, ...RUNS, CENTROID]);
  COMP_HEAD_RE = new RegExp("^" + v.componentHeadPattern + "$");
  COND_DIRS = new Set(v.conditionalDirectives || []);
  COND_KW = v.conditionKeywords || []; COND_FIELDS = v.conditionFields || [];
  AXIS_KINDS = v.axisValueKinds || [];
}

// `!if` / `!elif` lines hold a condition (a language of its own, shared by both
// editors): `ital.xvalue == 1 and "Bold" in styleName`.
const COND_LINE_RE = /^\s*!(if|elif)\b/;
const isCondDirective = line => /^\s*!(if|elif|else|endif)\b/.test(line);

// Completion on a directive line: `!…` → the block words; after `axis.` →
// xvalue/uservalue; otherwise the condition's own words.
function condComplete({word, head, line}){
  if(word[0] === "!") return line.trim() === word ? _mk([...COND_DIRS], "dir") : [];
  if(!COND_LINE_RE.test(line)) return null;
  if(head != null) return _mk(AXIS_KINDS, "axis");
  return [..._mk(COND_FIELDS, "field"), ..._mk(COND_KW, "kw")];
}

function highlightCond(line){
  let out = "";
  const hash = line.indexOf("#");
  let code = line, tail = "";
  if(hash >= 0){ code = line.slice(0, hash); tail = line.slice(hash); }
  const re = /(!\w+)|("[^"]*"?)|([A-Za-z_]\w*)(\.(?:xvalue|uservalue))|(-?\d+(?:\.\d+)?)|(==|!=|<=|>=|<|>|\(|\))|([A-Za-z_]\w*)/g;
  let m, last = 0;
  const put = (cls, txt) => { out += cls ? `<span class="t-${cls}">${escapeHtml(txt)}</span>` : escapeHtml(txt); };
  while((m = re.exec(code))){
    if(m.index > last) put(null, code.slice(last, m.index));
    if(m[1]) put("dir", m[1]);
    else if(m[2]) put("str", m[2]);
    else if(m[3]){ put("var", m[3]); put("kw", m[4]); }      // axis . xvalue|uservalue
    else if(m[5]) put("num", m[5]);
    else if(m[6]) put("op", m[6]);
    else if(m[7]) put(COND_KW.includes(m[7]) ? "kw" : COND_FIELDS.includes(m[7]) ? "metric" : null, m[7]);
    last = re.lastIndex;
  }
  if(last < code.length) put(null, code.slice(last));
  if(tail) put("comment", tail);
  return out || "&nbsp;";
}

// ---- completion providers (one per editor language) ------------------------
// Each returns [{v, k}] for a context {word, head, seg, axis}: `head` is the
// token before the last dot (a frame / $glyph / compN), `seg` the part being
// typed, `axis` the anchor slot the caret sits in ("x"/"y", null if unknown).
const _mk = (arr, k) => arr.map(v => ({v, k}));
const _kindOf = v => FRAME_SET.has(v) ? "frame" : RUN_SET.has(v) ? "run"
                   : METRIC_SET.has(v) ? "metric" : v === CENTROID ? "kw" : "align";

// distinct anchor names across the current view (base anchors omit the `_`).
function anchorNames(baseOnly){
  const s = new Set();
  for(const g of Object.values(GLYPHS)) for(const a of (g.anchors||[])){
    if(baseOnly && a.name[0] === "_") continue;
    s.add(a.name);
  }
  return [...s];
}

// The anchor DSL: keywords, @labels, &vars, %anchors, and after-a-dot positions.
function ANCHOR_COMPLETE({word, head, seg, axis, line}){
  if(word[0] === "!") return line.trim() === word ? _mk([...DIRECTIVES, ...COND_DIRS], "dir") : [];
  const cond = condComplete({word, head, line});
  if(cond) return cond;
  if(word[0] === "@"){ const s=new Set(); for(const x of allRulesText().matchAll(/@[\w.]+/g)) s.add(x[0]); return _mk([...s],"label"); }
  if(word[0] === "&"){ const s=new Set(); for(const x of allRulesText().matchAll(/&\w+/g)) s.add(x[0]); return _mk([...s],"var"); }
  if(word[0] === "%"){                                   // another anchor's position on this glyph
    const g = SELECTED && GLYPHS[SELECTED];
    const names = g ? (g.anchors||[]).map(a=>a.name) : anchorNames(false);
    return _mk([...new Set(names)].map(n=>"%"+n),"anchor");
  }
  if(head != null){                                     // after a dot: position words for `head`
    if(head[0] === "$") return _mk(EDGES,"edge");        // $Glyph.top / .middle / .bottom
    if(COMP_HEAD_RE.test(head)) return _mk(FRAMES,"frame");
    // the library's own per-axis table: `width` has no vertical form, `outline`
    // also takes runs and the centroid — none of that is decided here.
    const words = (AFTER_DOT[head] || {})[axis || ""] || [];
    return words.map(v => ({v, k: _kindOf(v)}));
  }
  // opening a slot: frames + this axis's alignments, and metrics only where a
  // height term is legal (the Y slot) — again the library's call, not ours.
  return (FOR_SLOT[axis || ""] || []).map(v => ({v, k: _kindOf(v)}));
}

// GlyphConstruction: @anchor names, otherwise glyph names.
function GC_COMPLETE({word, head, line}){
  const cond = condComplete({word, head, line});
  if(cond) return cond;
  if(word[0] === "@") return _mk(anchorNames(true).map(n=>"@"+n),"anchor");
  const names = ALLGLYPHS ? ALLGLYPHS.map(g=>g.name)
              : [...new Set([...Object.keys(GLYPHS), ...Object.keys(COMPOSITES||{})])];
  return _mk(names,"glyph");
}

function highlightLine(line){
  if(isCondDirective(line)) return highlightCond(line);
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
  if(isCondDirective(line)) return highlightCond(line);
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

function makeEditor(host, onChange, onFocus, highlight = highlightLine, complete = ANCHOR_COMPLETE){
  host.innerHTML =
    '<div class="ed"><div class="ed-gutter"><div class="gnums"></div></div>'+
    '<div class="ed-body"><pre class="ed-hl" aria-hidden="true"><div class="ed-hl-in"></div></pre>'+
    '<textarea class="ed-ta" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off"></textarea>'+
    '<div class="ac" hidden></div></div></div>';
  const ta = host.querySelector(".ed-ta"), hl = host.querySelector(".ed-hl-in"),
        gnums = host.querySelector(".gnums"),
        ac = host.querySelector(".ac");
  let errLines = new Set(), offLines = new Set(), acItems = [], acSel = 0, acStart = 0;

  if(!CHAR_W){
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;font-family:var(--mono);font-size:var(--fs);white-space:pre";
    probe.textContent = "0".repeat(40); document.body.appendChild(probe);
    CHAR_W = probe.getBoundingClientRect().width / 40; probe.remove();
  }

  function refresh(){
    const lines = ta.value.split("\n");
    const cls = i => (errLines.has(i+1) ? " err" : "") + (offLines.has(i+1) ? " off" : "");
    hl.innerHTML = lines.map((l,i) => `<div class="ln${cls(i)}">${highlight(l)}</div>`).join("");
    gnums.innerHTML = lines.map((_,i) => `<div class="gl${cls(i)}">${i+1}</div>`).join("");
    sync();
  }
  // Follow the textarea's scroll by translating, not by copying scrollTop: the
  // textarea can scroll further than the overlay and gutter (its horizontal
  // scrollbar shortens it), and a clamped overlay sat half a line off.
  function sync(){
    hl.style.transform = `translate(${-ta.scrollLeft}px,${-ta.scrollTop}px)`;
    gnums.style.transform = `translateY(${-ta.scrollTop}px)`;
  }
  function markErrors(set){ errLines = set || new Set(); refresh(); }
  // lines an `!if` block drops for the active master — dimmed, still editable
  function markInactive(set){ offLines = set || new Set(); refresh(); }

  // Which slot of `name ( X Y )` the caret sits in — the anchor DSL uses one
  // grammar for both axes but a different alignment table per axis, so knowing
  // the slot narrows the menu from six words to three.
  function slotAxis(upto){
    const line = upto.slice(upto.lastIndexOf("\n") + 1);
    const open = line.lastIndexOf("(");
    if(open < 0 || line.indexOf(")", open) >= 0) return null;
    const inner = line.slice(open + 1).replace(/^\s+/, "");
    const done = inner.split(/\s+/).length - 1;         // whole tokens before the caret
    return done === 0 ? "x" : done === 1 ? "y" : null;  // beyond two → not a slot
  }
  function currentWord(){
    const pos = ta.selectionStart, upto = ta.value.slice(0, pos);
    const m = /[@&%$!]?[\w.]*$/.exec(upto);
    const word = m ? m[0] : "";
    // split at the last dot: `outline.ce` → head "outline", seg "ce"; complete only seg
    const dot = word.lastIndexOf(".");
    const head = dot >= 0 ? word.slice(0, dot) : null;
    const seg = dot >= 0 ? word.slice(dot + 1) : word;
    const start = dot >= 0 ? pos - seg.length : pos - word.length;
    const line = upto.slice(upto.lastIndexOf("\n") + 1);
    return { word, head, seg, start, pos, axis: slotAxis(upto), line };
  }
  function acUpdate(){
    const {word, head, seg, start, pos, axis, line} = currentWord();
    // require ≥1 char normally, but pop immediately right after a dot (empty seg ok)
    if((head == null && seg.length < 1) || pos !== ta.selectionStart) return acHide();
    const lower = seg.toLowerCase();
    acItems = complete({word, head, seg, axis, line})
      .filter(c => c.v.toLowerCase().startsWith(head != null ? lower : word.toLowerCase()) && c.v !== word)
      .slice(0, 12);
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
           refresh, markErrors, markInactive, gotoLine, focus: () => ta.focus(), ta };
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
    fonth: {sel:".sidebar",   axis:"y", sign: 1, min: 80, def:320, max:()=>$(".sidebar").clientHeight*0.7},
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
  const overlay = $("#drop"), zone = $("#stzone");
  let depth = 0;
  // on the start screen its drop zone lights up; over the workspace, the overlay
  const target = () => startShown() ? zone : overlay;
  addEventListener("dragenter", e => { e.preventDefault(); if(depth++ === 0) target().classList.add(startShown() ? "over" : "on"); });
  addEventListener("dragover", e => e.preventDefault());
  addEventListener("dragleave", e => { e.preventDefault(); if(--depth <= 0){ depth=0; overlay.classList.remove("on"); zone.classList.remove("over"); } });
  addEventListener("drop", e => {
    e.preventDefault(); depth=0; overlay.classList.remove("on"); zone.classList.remove("over");
    // the DataTransfer empties after the event: take the entries now
    const entries = [...e.dataTransfer.items].filter(i => i.kind === "file")
      .map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    // Chromium: a writable handle for the same item, also only during the event
    const item = [...e.dataTransfer.items].find(i => i.kind === "file");
    const handle = item && item.getAsFileSystemHandle ? item.getAsFileSystemHandle().catch(() => null) : Promise.resolve(null);
    if(entries.length) guarded(openEntries(entries, handle));
  });
  $("#loadfont").addEventListener("click", () => $("#fontfile").click());
  $("#addfont").addEventListener("click", () => $("#fontfile").click());
  $("#addfolder").addEventListener("click", pickFolder);
  $("#stfolder").addEventListener("click", pickFolder);
  $("#stufoz").addEventListener("click", () => $("#fontfile").click());
  // without the File System Access API: a directory <input>, read whole
  // (its browser prompt calls this local read an "upload")
  $("#folderfile").addEventListener("change", e => {
    const list = [...e.target.files].filter(f => !f.webkitRelativePath.split("/").some(p => p.startsWith(".")));
    e.target.value = "";
    if(list.length) guarded(sendFont(list[0].webkitRelativePath.split("/")[0] || "font",
                                     list.map(f => ({path: f.webkitRelativePath, file: f}))));
  });
  $("#fontfile").addEventListener("change", e => {
    const list = [...e.target.files]; e.target.value = "";
    if(list.length) guarded(sendFont(list[0].name, list.map(f => ({path: f.name, file: f}))));
  });
}

const RULES_FILE = /\.(anchors|af|dsl|txt)$/i;
const unsupported = name => new Error(`${name}: drop a .ufo folder, a .ufoz file or a folder with a .designspace.`);
const guarded = promise => promise.catch(err => fontError(err));

/** A folder: the File System Access picker (Chrome asks to *view* the files),
 *  else a directory <input>. */
async function pickFolder(){
  if(!window.showDirectoryPicker){ $("#folderfile").click(); return; }
  let dir;
  try { dir = await showDirectoryPicker({id: "font", mode: "read"}); }
  catch(err){ return; }                              // the picker was dismissed
  await guarded(openFolder(handleFolder(dir), dir));
}

async function openEntries(entries, handlePromise){
  if(entries.length > 1) throw new Error("Drop one font at a time.");
  const entry = entries[0];
  if(entry.isDirectory) return openFolder(entryFolder(entry), handlePromise);
  const file = await readRetrying(() => new Promise((res, rej) => entry.file(res, rej)), entry.name);
  const kind = kindOf(entry.name);
  if(kind){                                          // a rules file → a new layer, linked for Save
    await bootDone;                                  // (on the start screen: ready for the font)
    const handle = await handlePromise;
    addRulesLayer(kind, entry.name, await file.text(), {handle: handle && handle.kind === "file" ? handle : null});
    SELECTED = null; HL_ANCHOR = null; compute(); return;
  }
  if(!/\.(ufoz|zip)$/i.test(entry.name)) throw unsupported(entry.name);
  return sendFont(entry.name, [{path: entry.name, file}]);
}

/* -- folders: drop entries and picker handles behind one interface -------- */

function entryFolder(dir){
  return {
    name: dir.name,
    async list(){
      const reader = dir.createReader(), all = []; let batch;
      do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); all.push(...batch); } while(batch.length);
      return all.map(e => e.isFile
        ? {kind: "file", name: e.name, file: () => new Promise((res, rej) => e.file(res, rej))}
        : {kind: "directory", name: e.name, folder: entryFolder(e)});
    },
    sub: path => new Promise((res, rej) => dir.getDirectory(path, {}, d => res(entryFolder(d)), rej)),
  };
}

function handleFolder(dir){
  return {
    name: dir.name,
    async list(){
      const out = [];
      for await (const h of dir.values()) out.push(h.kind === "file"
        ? {kind: "file", name: h.name, file: () => h.getFile()}
        : {kind: "directory", name: h.name, folder: handleFolder(h)});
      return out;
    },
    async sub(path){ let d = dir; for(const part of path.split("/")) d = await d.getDirectoryHandle(part); return handleFolder(d); },
  };
}

async function listRetrying(folder, path){
  for(let attempt = 1; ; attempt++){
    try { return await folder.list(); }
    catch(err){ if(attempt >= 4) throw new Error(`${path}/: ${err.message || err}`);
      await new Promise(r => setTimeout(r, 50 * attempt)); }
  }
}

/** Every file under a folder (names only, nothing read yet), hidden ones skipped. */
async function collect(folder, rel, out){
  for(const node of await listRetrying(folder, rel)){
    if(node.name.startsWith(".")) continue;          // .git, .DS_Store: never part of a font
    const path = `${rel}/${node.name}`;
    if(node.kind === "file") out.push({path, get: node.file}); else await collect(node.folder, path, out);
  }
  return out;
}

// A failed read is retried on a fresh handle: on a large folder Chrome now and
// then refuses a perfectly readable file (NotReadableError), and one such file
// would otherwise fail the whole font. The bytes are kept as an ArrayBuffer, not
// a Blob: Chrome pages large Blob totals out to disk, and reading them back can
// fail the same way.
const inMemory = bytes => ({arrayBuffer: async () => bytes, text: async () => new TextDecoder().decode(bytes)});
async function readRetrying(getFile, path){
  for(let attempt = 1; ; attempt++){
    try { return inMemory(await (await getFile()).arrayBuffer()); }
    catch(err){ if(attempt >= 4) throw new Error(`${path}: ${err.message || err}`);
      await new Promise(r => setTimeout(r, 50 * attempt)); }
  }
}

async function readPending(pending){
  const out = [];
  for(let i = 0; i < pending.length; i += 64){
    progress("Reading files", i, pending.length);
    out.push(...await Promise.all(pending.slice(i, i + 64).map(async ({path, get}) => ({path, file: await readRetrying(get, path)}))));
  }
  return out;
}

/** UFO paths a designspace's <source>s reference, in order, deduplicated. */
function designspaceSources(xml){
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  return [...new Set([...doc.querySelectorAll("sources > source[filename]")].map(s => s.getAttribute("filename")))];
}

/** `a/./b/../c` → `a/c`; null when the path leaves the folder or is absolute. */
function normalizeRelative(path){
  if(path.startsWith("/") || /^[a-z]:/i.test(path)) return null;
  const parts = [];
  for(const p of path.replace(/\\/g, "/").split("/")){
    if(!p || p === ".") continue;
    if(p === ".."){ if(!parts.length) return null; parts.pop(); } else parts.push(p);
  }
  return parts.length ? parts.join("/") : null;
}

/**
 * A dropped or picked folder. A .ufo is read whole. A project folder: pick one
 * of the .designspace files at its top, then read only that file and the UFOs
 * it references (projects hold builds, proofs and other masters too). A source
 * outside the folder or missing from it is left for Python to report.
 */
async function openFolder(folder, dirPromise = null){
  progress("Listing the files", 0, 0);
  if(/\.ufo$/i.test(folder.name))
    return sendFont(folder.name, await readPending(await collect(folder, folder.name, [])));
  const top = await listRetrying(folder, folder.name);
  // the rules next to the font: loaded once it opens, linked for Save
  const project = {rules: top.filter(n => n.kind === "file" && kindOf(n.name)), dir: dirPromise};
  const found = top.filter(n => n.kind === "file" && /\.designspace$/i.test(n.name))
                   .sort((a, b) => a.name.localeCompare(b.name));
  if(!found.length){
    const ufo = top.filter(n => n.kind === "directory" && /\.ufo$/i.test(n.name))
                   .sort((a, b) => a.name.localeCompare(b.name))[0];
    if(!ufo) throw new Error(`${folder.name}: no .designspace or .ufo at the top of this folder.`);
    return sendFont(ufo.name, await readPending(await collect(ufo.folder, `${folder.name}/${ufo.name}`, [])), project);
  }
  let chosen = found[0];
  if(found.length > 1){
    progress("Choose a designspace", 0, 0);
    const name = await chooseDesignspace(found.map(n => n.name));
    if(!name){ progressDone(); return; }
    chosen = found.find(n => n.name === name);
  }
  const ds = await readRetrying(chosen.file, chosen.name);
  const sources = designspaceSources(await ds.text());
  const pending = [];
  for(const [i, source] of sources.entries()){
    progress("Listing the masters", i, sources.length);
    const rel = normalizeRelative(source);
    let ufo = null;
    if(rel) try { ufo = await folder.sub(rel); } catch(err){ /* reported by Python */ }
    if(ufo) await collect(ufo, `${folder.name}/${rel}`, pending);
  }
  const files = [{path: `${folder.name}/${chosen.name}`, file: ds}, ...await readPending(pending)];
  return sendFont(folder.name, files, project);
}

// Which designspace of a dropped folder to open: resolves to its path, or null.
function chooseDesignspace(choices){
  const dlg = $("#dspick"), list = dlg.querySelector(".dp-list");
  list.innerHTML = "";
  return new Promise(resolve => {
    const done = v => { dlg.close(); resolve(v); };
    for(const c of choices){
      const b = document.createElement("button"); b.className = "ghost dp-item"; b.textContent = c;
      b.addEventListener("click", () => done(c)); list.appendChild(b);
    }
    dlg.querySelector(".dp-cancel").onclick = () => done(null);
    dlg.oncancel = e => { e.preventDefault(); done(null); };     // Esc
    dlg.showModal();
  });
}

/* -- start screen and progress ------------------------------------------- */

let bootDone, bootResolve, pythonReady = false;
bootDone = new Promise(r => bootResolve = r);
const startShown = () => !$("#start").hidden;

/** Shown until a font opens: always on the web, locally when no font was given.
 *  The session's placeholder font (the demo) is dropped when the first one opens. */
let placeholderFont = false;
function showStart(){
  const start = $("#start");
  placeholderFont = true;
  start.style.setProperty("--hdr", $("header").offsetHeight + "px");
  start.hidden = false;
  if(studioApi.kind !== "worker"){
    $("#stprivacy").textContent = "The Studio runs on this computer as a local server: nothing is sent anywhere. " +
      "The font is only read; rules are saved by downloading an .anchors file.";
  }
  const STAGES = {"starting Python…": .15, "loading font libraries…": .5, "starting the Studio…": .85};
  studioApi.onStatus(text => {
    if(pythonReady || !(text in STAGES)) return;
    $("#strtlbl").textContent = text[0].toUpperCase() + text.slice(1);
    $("#strtbar").style.width = `${STAGES[text] * 100}%`;
  });
  studioApi.onReady(info => {
    pythonReady = true;
    $("#struntime").classList.add("ready");
    $("#strtlbl").textContent = info
      ? `Ready · Python ${info.versions.python} · started in ${(info.ms / 1000).toFixed(1)} s`
      : `Ready · local server · v${META.version || ""}`;
    if(info) $("#strtlbl").title = JSON.stringify(info.versions);
  });
}

function hideStart(){ $("#start").hidden = true; progressDone(); }

/** Opening progress: the status pill, and the start screen's bar while it is up. */
function progress(label, done, total){
  const status = $("#status"); status.className = "pill";
  status.textContent = total ? `${label.toLowerCase()} ${done}/${total}` : `${label.toLowerCase()}…`;
  if(!startShown()) return;
  $("#sterror").hidden = true; $("#stidle").hidden = true; $("#stopening").hidden = false;
  $("#stopenlbl").textContent = pythonReady ? `${label}…` : `${label}… (waiting for Python)`;
  $("#stopenbar").style.width = total ? `${Math.max(5, 100 * done / total)}%` : "5%";
  $("#stopencount").textContent = total ? `${done} / ${total}` : "";
}

function progressDone(){ $("#stidle").hidden = false; $("#stopening").hidden = true; }

function fontError(err){
  const status = $("#status"); status.className = "pill bad"; status.textContent = "font error";
  const text = err ? String(err.message || err) : "load failed";
  if(startShown()){ progressDone(); const box = $("#sterror"); box.textContent = text; box.hidden = false; return; }
  $("#problems").innerHTML = `<div class="row err"><span class="tag">font</span><span>${escapeHtml(text)}</span></div>`;
}

async function sendFont(name, collected, project = null){
  progress("Opening the font", 0, 0);
  await bootDone;
  const status = $("#status");
  let j;
  try { j = await studioApi.loadFont(name, collected); }
  catch(err){ j = {ok:false, error:String(err.message || err)}; }
  // a zip with several designspaces: ask which one (the drop waits in Python)
  if(j.ok && j.choose){
    status.textContent = "choose a designspace…";
    const path = await chooseDesignspace(j.choose);
    if(path) progress("Loading the masters", 0, 0);
    try { j = await studioApi.call("font/designspace", {path}); }
    catch(err){ j = {ok:false, error:String(err.message || err)}; }
    if(j.ok && !path){ progressDone(); compute(); return; }   // cancelled
  }
  if(!j.ok) return fontError(j.error);
  if(placeholderFont){                               // the first real font: drop the placeholder
    placeholderFont = false;
    try { const r = await studioApi.call("font/remove", {index: 0}); if(r.ok && r.state) j.state = r.state; }
    catch(_){ /* keep it listed */ }
  }
  hideStart();
  Object.assign(META, j.state); setFontMeta(); renderFontCards();
  // a designspace opened: say which, and which sources were not in the drop
  const box = $("#masters");
  if(j.designspace){
    box.hidden = false;
    box.innerHTML = `<div class="m-row muted">${escapeHtml(j.designspace)}: ${j.masters} master${j.masters === 1 ? "" : "s"}</div>` +
      (j.problems || []).map(m => `<div class="m-row warn">${escapeHtml(m)}</div>`).join("");
  }
  if(project){
    if(!j.designspace) box.innerHTML = "";
    const dir = await Promise.resolve(project.dir).catch(() => null);
    const names = await loadProjectRules(project.rules, dir && dir.kind === "directory" ? dir : null);
    if(names.length){
      box.hidden = false;
      box.insertAdjacentHTML("beforeend", `<div class="m-row muted">rules: ${escapeHtml([...names].sort().join(", "))}</div>`);
    }
  }
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
    const style = f.styleName != null ? f.styleName : "";
    card.innerHTML =
      `<div class="fc-body"><div class="fc-name">${escapeHtml(f.name)}</div>`+
      `<div class="fc-meta">${Math.round(f.unitsPerEm)}upm · ital ${Math.round(f.italicAngle)}°`+
      (f.designspace ? ` · designspace` : "") + `</div>`+
      // the master this font stands for — what `!if` blocks see
      `<label class="fc-field" title="axis location for !if conditions: AXIS.xvalue=N (design) / AXIS.uservalue=N (user)">`+
      `<span>location</span><input class="fc-loc" spellcheck="false" placeholder="ital.xvalue=1, wght.uservalue=700" value="${escapeHtml(f.location || "")}"></label>`+
      `<label class="fc-field" title="styleName for !if conditions (empty → the font's fontinfo styleName)">`+
      `<span>style</span><input class="fc-style" spellcheck="false" placeholder="${escapeHtml(f.fontStyleName || "(fontinfo)")}" value="${escapeHtml(style)}"></label>`+
      `<div class="fc-err" hidden></div></div>`+
      (fonts.length > 1 ? `<button class="fc-x" title="remove this font">✕</button>` : "");
    card.addEventListener("click", e => { if(i !== active && !e.target.closest("input")) activateFont(i); });
    const x = card.querySelector(".fc-x");
    if(x) x.addEventListener("click", e => { e.stopPropagation(); removeFont(i); });
    for(const inp of card.querySelectorAll("input")){
      inp.addEventListener("keydown", e => { if(e.key === "Enter") inp.blur(); });
      inp.addEventListener("change", () => setFontContext(i, card));
    }
    box.appendChild(card);
  });
  $("#compareMasters").hidden = fonts.length < 2;
}

async function setFontContext(i, card){
  const loc = card.querySelector(".fc-loc").value, style = card.querySelector(".fc-style").value;
  const err = card.querySelector(".fc-err");
  let j; try {
    j = await studioApi.call("font/context", {index: i, location: loc, styleName: style === "" ? null : style});
  } catch(e){ j = {ok:false, error:String(e)}; }
  if(!j.ok){ err.textContent = j.error || "could not set the location"; err.hidden = false; return; }
  Object.assign(META, j.state); renderFontCards();
  if(i === (META.active ?? 0)) compute();            // the active master changed → re-resolve
}

// Every loaded master computed with its own location: which glyphs end up with
// different anchor names or composite components (allowed, but worth knowing).
async function compareMasters(){
  const box = $("#masters"); box.hidden = false;
  box.innerHTML = `<div class="m-row muted">comparing…</div>`;
  const layers = sentLayers();
  let j; try {
    j = await studioApi.call("masters", {layers, gc: gcCombined().text});
  } catch(e){ j = {ok:false, errors:[String(e)], warnings:[]}; }
  const rows = [
    ...(j.errors || []).map(m => `<div class="m-row err">${escapeHtml(m)}</div>`),
    ...(j.warnings || []).map(m => `<div class="m-row warn">${escapeHtml(m)}</div>`),
  ];
  box.innerHTML = rows.length ? rows.join("")
    : `<div class="m-row muted">masters are structurally identical</div>`;
}

async function fontOp(method, index){
  let j; try {
    j = await studioApi.call(method, {index});
  } catch(_){ j = {ok:false}; }
  if(!j.ok || !j.state) return null;
  Object.assign(META, j.state); setFontMeta(); renderFontCards();
  ALLGLYPHS = null; ALLMAP = {};                     // the active font changed → fresh geometry
  for(const k in lastPos) delete lastPos[k];
  return j;
}

async function activateFont(i){
  const status = $("#status"); status.className="pill"; status.textContent="switching font…";
  if(await fontOp("font/activate", i)) compute();   // keep SELECTED → same glyph, new master
}

async function removeFont(i){
  if(await fontOp("font/remove", i)){ if(!GLYPHS[SELECTED]){ SELECTED=null; HL_ANCHOR=null; } GLYPHS={}; compute(); }
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
  const layers = sentLayers();
  const gc = gcCombined().text;
  try {
    VIEW = await studioApi.call("compute", {layers, gc});
  } catch(err) {                                    // server 500 / dropped connection / Python error
    const where = studioApi.kind === "http" ? "studio server error — see terminal: " : "studio error: ";
    VIEW = {ok:false, problems:[where+String(err.message || err)], diagnostics:[], glyphs:{}, layers:[]};
  }
  markErrorLines();
  markInactiveLines();
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
  if(m){
    if(m[1] === (VIEW.gcLabel || "constructions")) return {layer: -1, line: +m[2]};
    const idx = anchorLayers.findIndex(l => l.name === m[1]); if(idx >= 0) return {layer: idx, line: +m[2]};
  }
  m = /^line (\d+):/.exec(p);
  return m ? {layer: 0, line: +m[1]} : null;
}

function markErrorLines(){
  const sets = anchorLayers.map(() => new Set()), gcSet = new Set();
  for(const p of VIEW.problems||[]){
    const loc = problemLoc(p); if(!loc) continue;
    if(loc.layer === -1) gcSet.add(loc.line); else if(sets[loc.layer]) sets[loc.layer].add(loc.line);
  }
  anchorLayers.forEach((l, idx) => l.ed.markErrors(sets[idx]));
  gcSplitLines(gcSet).forEach((set, i) => gcLayers[i].ed.markErrors(set));
}

// dim what the `!if` blocks drop for the active master (sent on every compute)
function markInactiveLines(){
  const inactive = VIEW.inactive || {};
  anchorLayers.forEach((l, idx) => l.ed.markInactive(new Set(inactive[idx] || [])));
  gcSplitLines(VIEW.gcInactive || []).forEach((set, i) => gcLayers[i].ed.markInactive(set));
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
    if(loc) r.addEventListener("click", () => gotoLoc(loc.layer, loc.line));
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
    card.addEventListener("click", ()=>{
      SELECTED=g.name; HL_ANCHOR=null; renderGrid(); renderInspector();
      // composites: clicking the cell also jumps the Construction editor to the rule
      if(GRID_TAB==="composites" && g.line!=null) gcGoto(g.line);
    });
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

// Font units per screen pixel in the inspector, so labels keep a fixed on-screen
// size whatever the font's UPM, the canvas size or the zoom.
const pxUnits = (H, canvasEl) => H / ((canvasEl && canvasEl.clientHeight) || 600);
// An SVG label `px` screen pixels tall, offset (dx, dy) screen pixels from (x, y).
function label(text, x, y, px, u, {cls=null, dx=0, dy=0}={}){
  const t = el("text", {x: x + dx*u, y: y + dy*u}); if(cls) t.setAttribute("class", cls);
  t.style.fontSize = `${px*u}px`; t.textContent = text; return t;
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
  const u = pxUnits(H, canvasEl);
  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){ const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      svg.appendChild(label(lbl, x0, -h, 11, u, {cls:"metric-lbl", dx:6, dy:-4})); }
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
    if(!small) grp.appendChild(label(`${a.name} (${Math.round(a.x)}, ${Math.round(a.y)})`, 0, 0, 15, u, {dx:10, dy:-9}));
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
  const u = pxUnits(H, canvasEl);
  if(!small){
    const order=[["descender","descender"],["baseline","baseline"],["xHeight","x-height"],["capHeight","cap-height"],["ascender","ascender"]];
    for(const [key,lbl] of order){ const h = META.metrics[key]; if(h===undefined) continue;
      svg.appendChild(el("line",{class:"metric", x1:x0, y1:-h, x2:x0+W, y2:-h}));
      svg.appendChild(label(lbl, x0, -h, 11, u, {cls:"metric-lbl", dx:6, dy:-4})); }
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
      grp.appendChild(label(j.anchor, j.x, -j.y, 15, u, {dx:10, dy:-9}));
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
  if(jump) jump.addEventListener("click", () => gcGoto(+jump.dataset.gcline));
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
      if(a.line!=null) gotoLoc(a.layer, a.line);
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
