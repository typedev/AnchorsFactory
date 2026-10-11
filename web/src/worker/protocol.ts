// Messages between the page and the Python worker.

/** A file of a dropped font, its path relative to the drop root. */
export type FontFile = { path: string; bytes: ArrayBuffer }

export type Request =
  | { id: number; kind: 'call'; method: string; body: unknown }
  | { id: number; kind: 'loadFont'; files: FontFile[] }

export type Reply =
  | { id: number; ok: true; result: unknown }
  | { id: number; ok: false; error: string; detail?: string }

/** Startup progress, and a fatal error if Python cannot start. */
export type WorkerEvent =
  | { type: 'status'; text: string }
  | { type: 'ready'; versions: Record<string, string>; ms: number }
  | { type: 'fatal'; error: string }

export type WorkerMessage = Reply | WorkerEvent
