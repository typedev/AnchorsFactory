// Web Worker that owns Python (Pyodide): the engine, the Studio's api.py and
// every loaded font live here. The page calls Studio.dispatch(method, body)
// with the same method names the local server routes as /api/<method>.
import type { FontFile, Reply, Request, WorkerEvent } from './protocol'
import { PYODIDE_VERSION } from './pyodide-version'

const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
/** From the Pyodide distribution; the pinned pure wheels come on top. */
const PYODIDE_PACKAGES = ['fonttools', 'lxml', 'pyclipper']

// The engine and the Studio from this checkout (the Studio is not in the
// wheel), and the sample rule sets offered in the preset menu.
const engine = import.meta.glob('../../../anchorsfactory/**/*.py', {
  query: '?raw', import: 'default', eager: true,
}) as Record<string, string>
const rules = import.meta.glob(
  ['../../../examples/rules/*.anchors', '../../../examples/rules/*.glyphsConstruction'],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>

// The surface of Pyodide used here is small, so it is typed locally.
type PyCallable = (...args: unknown[]) => string
type Pyodide = {
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: string | Uint8Array): void }
  loadPackage(names: string[]): Promise<void>
  runPython(code: string): unknown
  globals: { get(name: string): PyCallable }
}

const post = (msg: Reply | WorkerEvent) => self.postMessage(msg)
const status = (text: string) => post({ type: 'status', text })

const APP = '/app'
let py: Pyodide
let call: PyCallable
let openTree: PyCallable

function write(path: string, data: string | Uint8Array) {
  py.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')))
  py.FS.writeFile(path, data)
}

async function boot(): Promise<void> {
  const t0 = performance.now()
  status('starting Python…')
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  py = (await loadPyodide({ indexURL: PYODIDE_URL })) as Pyodide

  status('loading font libraries…')
  const base = new URL(import.meta.env.BASE_URL, self.location.origin)
  const manifest = await (await fetch(new URL('wheels/manifest.json', base))).json()
  const wheels = (manifest.wheels as string[]).map((f) => new URL(`wheels/${f}`, base).href)
  await py.loadPackage([...PYODIDE_PACKAGES, ...wheels])

  status('starting the Studio…')
  for (const [path, source] of Object.entries(engine)) {
    write(`${APP}/anchorsfactory/${path.split('/anchorsfactory/')[1]}`, source)
  }
  // importlib.metadata gives anchorsfactory.__version__; the sources come
  // without the wheel's dist-info, so write the one field it reads.
  write(`${APP}/anchorsfactory-${__AF_VERSION__}.dist-info/METADATA`,
    `Metadata-Version: 2.1\nName: anchorsfactory\nVersion: ${__AF_VERSION__}\n`)
  for (const [path, source] of Object.entries(rules)) write(`/rules/${path.split('/').pop()}`, source)

  py.runPython(`
import sys
sys.path.insert(0, "${APP}")
import json
from anchorsfactory import speedups, presets
from anchorsfactory.presets import construction_text, has_construction
from anchorsfactory.studio.api import Studio, _seed_rules
from anchorsfactory.studio.demo import build_demo_font

speedups.enable()
presets.set_search_paths(["/rules"])
_studio = Studio(build_demo_font(), _seed_rules("default"), "demo",
                 gc_text=construction_text("default") if has_construction("default") else None)

def _call(method, body):
    return json.dumps(_studio.dispatch(method, json.loads(body))[1])

def _open_tree(root):
    return json.dumps(_studio.open_font_tree(root, warm=True)[1])
`)
  call = py.globals.get('_call')
  openTree = py.globals.get('_open_tree')
  const versions = JSON.parse(py.runPython(`
from importlib.metadata import version
json.dumps({"python": sys.version.split()[0], "pyodide": "${PYODIDE_VERSION}",
            **{name: version(name) for name in ("anchorsfactory", "fonttools", "fontParts", "defcon")}})`) as string)
  post({ type: 'ready', versions, ms: Math.round(performance.now() - t0) })
}

let drops = 0

/** A dropped font: write its files under a fresh directory and open it. */
function loadFont(files: FontFile[]): unknown {
  const root = `/fonts/${++drops}`
  status('reading the font…')
  for (const f of files) {
    const rel = f.path.split('/').filter((p) => p && p !== '.' && p !== '..').join('/')
    if (rel) write(`${root}/${rel}`, new Uint8Array(f.bytes))
  }
  status('drawing outlines…')
  return JSON.parse(openTree(root))
}

/** Python errors carry a full traceback; the page shows the last line. */
function describe(err: unknown): { error: string; detail?: string } {
  const text = err instanceof Error ? err.message : String(err)
  const lines = text.trim().split('\n')
  return lines.length > 1 ? { error: lines[lines.length - 1], detail: text } : { error: text }
}

const booted = boot().catch((err) => {
  post({ type: 'fatal', error: describe(err).error })
  throw err
})

self.onmessage = async (e: MessageEvent<Request>) => {
  const req = e.data
  try {
    await booted
    const result = req.kind === 'loadFont'
      ? loadFont(req.files)
      : JSON.parse(call(req.method, JSON.stringify(req.body ?? {})))
    post({ id: req.id, ok: true, result })
  } catch (err) {
    post({ id: req.id, ok: false, ...describe(err) })
  }
}
