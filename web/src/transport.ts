// The web Studio's `studioApi` (see anchorsfactory/studio/static/api.js for
// the HTTP one): the same calls, answered by Python in a worker. The worker
// starts as soon as this module loads, so Pyodide downloads while the page
// draws.
import type { FontFile, Request, WorkerMessage } from './worker/protocol'

/** A request before it gets its id (Omit over each member of the union). */
type Unsent = Request extends infer R ? (R extends Request ? Omit<R, 'id'> : never) : never

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void }

const worker = new Worker(new URL('./worker/python.worker.ts', import.meta.url), { type: 'module' })
const pending = new Map<number, Pending>()
const listeners = new Set<(text: string) => void>()
let nextId = 1
let lastStatus = 'starting…'

function setStatus(text: string) {
  lastStatus = text
  listeners.forEach((fn) => fn(text))
}

worker.onmessage = (e: MessageEvent<WorkerMessage>) => {
  const msg = e.data
  if ('type' in msg) {
    if (msg.type === 'status') setStatus(msg.text)
    else if (msg.type === 'ready') {
      console.info(`[studio] Python ready in ${msg.ms} ms`, msg.versions)
      setStatus('ready')
    } else {
      setStatus('failed to start Python')
      pending.forEach((p) => p.reject(new Error(msg.error)))
      pending.clear()
    }
    return
  }
  const p = pending.get(msg.id)
  if (!p) return
  pending.delete(msg.id)
  if (msg.ok) p.resolve(msg.result)
  else {
    if (msg.detail) console.error(msg.detail)
    p.reject(new Error(msg.error))
  }
}

function send(req: Unsent, transfer: Transferable[] = []): Promise<unknown> {
  const id = nextId++
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    worker.postMessage({ ...req, id } as Request, transfer)
  })
}

type Collected = { path: string; file: File }

const studioApi = {
  kind: 'worker' as const,
  call: (method: string, body?: unknown) => send({ kind: 'call', method, body: body ?? {} }),
  async loadFont(_name: string, collected: Collected[]) {
    const files: FontFile[] = await Promise.all(
      collected.map(async (c) => ({ path: c.path, bytes: await c.file.arrayBuffer() })),
    )
    return send({ kind: 'loadFont', files }, files.map((f) => f.bytes))
  },
  onStatus(fn: (text: string) => void) {
    listeners.add(fn)
    fn(lastStatus)
  },
}

declare global {
  interface Window { studioApi: typeof studioApi }
}
window.studioApi = studioApi
