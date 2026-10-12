// The web Studio: the local Studio's page and script, talking to Python in a
// worker instead of the HTTP server. The transport must exist before app.js
// runs (it starts at once), so it is imported first.
import './transport'
import '../../anchorsfactory/studio/static/app.css'
import '../../anchorsfactory/studio/static/app.js'
import { PYODIDE_VERSION } from './worker/pyodide-version'

// Offline start after the first visit (public/sw.js). Not in dev: it would
// cache Vite's modules.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  const url = `${import.meta.env.BASE_URL}sw.js?pyodide=${PYODIDE_VERSION}`
  navigator.serviceWorker.register(url).catch((err) => console.warn('[studio] service worker not registered', err))
}
