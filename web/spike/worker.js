// Phase-0 spike: can the released engine + the repo's Studio functions run
// unchanged under Pyodide, and how fast? Reports timings to the page.
// A module worker: recent Pyodide releases are loaded as an ES module.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

// Pure-Python wheels installed with deps=False: fontParts/defcon require
// fontTools[unicode] -> unicodedata2, which has no Pyodide build (fontTools
// falls back to the stdlib unicodedata).
const DEPS = ["defcon", "fontMath", "fontPens", "booleanOperations", "fontParts"];
const ENGINE = "anchorsfactory==0.6.0";
const STUDIO = ["__init__.py", "demo.py", "render.py", "compose.py"];

const log = text => postMessage({type: "log", text});
const ms = t => Math.round(performance.now() - t);

onmessage = async ({data}) => {
  const out = {timings: {}};
  try {
    let t = performance.now();
    const {loadPyodide} = await import(PYODIDE + "pyodide.mjs");
    const py = await loadPyodide({indexURL: PYODIDE});
    out.timings.pyodide = ms(t); log(`pyodide ${py.version}: ${out.timings.pyodide} ms`);

    t = performance.now();
    await py.loadPackage(["fonttools", "lxml", "pyclipper", "micropip"]);
    const micropip = py.pyimport("micropip");
    // engine: the PyPI release, or (engine=local) the checkout's sources served
    // by the dev server at /engine/, for measuring unreleased changes
    await micropip.install.callKwargs(data.engine === "local" ? DEPS : [...DEPS, ENGINE], {deps: false});
    if(data.engine === "local"){
      const files = await (await fetch("/engine/index.json")).json();
      const site = py.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
      for(const f of files){
        const dir = f.split("/").slice(0, -1).join("/");
        py.FS.mkdirTree(`${site}/anchorsfactory/${dir}`);
        py.FS.writeFile(`${site}/anchorsfactory/${f}`, await (await fetch("/engine/" + f)).text());
      }
    }
    out.timings.packages = ms(t); log(`packages: ${out.timings.packages} ms`);

    // The Studio is not in the wheel: put its sources next to the installed engine.
    t = performance.now();
    const site = py.runPython("import anchorsfactory, os; os.path.dirname(anchorsfactory.__file__)");
    py.FS.mkdirTree(site + "/studio");
    for(const f of STUDIO){
      const src = await (await fetch("/studio/" + f)).text();
      py.FS.writeFile(`${site}/studio/${f}`, src);
    }
    // the sample rule sets, as the web Studio would offer them
    py.FS.mkdirTree("/rules");
    const index = await (await fetch("/rules/index.json")).json();
    for(const f of index) py.FS.writeFile("/rules/" + f, await (await fetch("/rules/" + f)).text());
    if(data.font){
      const buf = new Uint8Array(await (await fetch(data.font)).arrayBuffer());
      py.FS.mkdirTree("/fonts"); py.FS.writeFile("/fonts/font.zip", buf);
    }
    out.timings.sources = ms(t);

    const report = await py.runPythonAsync(`
import json, time, zipfile, os
import anchorsfactory
from anchorsfactory import RuleContext, presets
try:
    from anchorsfactory import speedups
    speedups.enable()
except ImportError:
    pass
from anchorsfactory.studio.demo import build_demo_font
from anchorsfactory.studio.render import build_view
from anchorsfactory.studio.compose import build_composite_view, masters_report

presets.set_search_paths(["/rules"])
rules = open("/rules/default.anchors").read()
gc = open("/rules/default.glyphsConstruction").read()
layers = [{"name": "default", "text": rules}]
cond = [{"name": "default", "text": rules},
        {"name": "italic", "text": "!if ital.xvalue == 1\\n{Lu} += probe (box.center 0)\\n!endif\\n"}]

def timed(fn, *a):
    t = time.perf_counter(); r = fn(*a); return r, round((time.perf_counter() - t) * 1000)

res = {"engine": anchorsfactory.__version__, "local": os.path.exists(os.path.join(os.path.dirname(anchorsfactory.__file__), "speedups.py"))}
paths = {}

def bench(label, font):
    paths.clear()
    try:
        v, t1 = timed(build_view, font, layers, None, paths)
        _, t2 = timed(build_view, font, layers, None, paths)      # warm: path cache filled
        c, t3 = timed(build_composite_view, font, layers, gc, None, paths)
    except TypeError:                                            # 0.6.0 Studio: no path cache
        v, t1 = timed(build_view, font, layers)
        _, t2 = timed(build_view, font, layers)
        c, t3 = timed(build_composite_view, font, layers, gc)
    up, _ = timed(build_view, font, cond, RuleContext(xvalues={"ital": 0}))
    it, _ = timed(build_view, font, cond, RuleContext(xvalues={"ital": 1}))
    m, t4 = timed(masters_report, [("up", font, RuleContext(xvalues={"ital": 0})),
                                   ("it", font, RuleContext(xvalues={"ital": 1}))], cond, gc)
    res[label] = {
        "glyphs": len(font), "ok": v["ok"], "problems": v["problems"][:3],
        "anchored_glyphs": len(v["glyphs"]),
        "anchors": sum(len(g["anchors"]) for g in v["glyphs"].values()),
        "composites": len(c["composites"]), "gc_problems": c["problems"][:3],
        "inactive_upright": up["inactive"], "inactive_italic": it["inactive"],
        "masters_warnings": len(m["warnings"]),
        "ms": {"view_cold": t1, "view_warm": t2, "composites": t3, "masters": t4},
    }

bench("demo", build_demo_font())
if os.path.exists("/fonts/font.zip"):
    from fontParts.world import OpenFont
    t = time.perf_counter()
    with zipfile.ZipFile("/fonts/font.zip") as z:
        z.extractall("/fonts/x")
    path = next(os.path.join(r, d) for r, ds, _ in os.walk("/fonts/x") for d in ds if d.endswith(".ufo"))
    font = OpenFont(path)
    res["real_open_ms"] = round((time.perf_counter() - t) * 1000)
    bench("real", font)
json.dumps(res)
`);
    Object.assign(out, JSON.parse(report));
    postMessage({type: "done", result: out});
  } catch(err){
    postMessage({type: "error", error: String(err && err.message || err)});
  }
};
