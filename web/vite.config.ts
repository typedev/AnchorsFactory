import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'

// The web Studio is the local Studio's frontend (anchorsfactory/studio/static)
// with a Pyodide worker in place of the HTTP server. Its markup is not copied:
// the plugin below takes <head>/<body> from the Studio's own index.html.
const STATIC = new URL('../anchorsfactory/studio/static/', import.meta.url)

function studioMarkup(): Plugin {
  return {
    name: 'studio-markup',
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        const page = readFileSync(new URL('index.html', STATIC), 'utf-8')
        const part = (tag: string) => page.split(`<${tag}>`)[1].split(`</${tag}>`)[0]
        // the server's stylesheet and scripts: main.ts imports them instead
        const head = part('head').replace(/^\s*<link rel="stylesheet"[^>]*>\s*$/m, '')
        const body = part('body').replace(/^\s*<script src="[^"]*"><\/script>\s*$/gm, '')
        return html.replace('<!--studio-head-->', head).replace('<!--studio-body-->', body)
      },
    },
  }
}

const version = /^version\s*=\s*"([^"]+)"/m.exec(
  readFileSync(new URL('../pyproject.toml', import.meta.url), 'utf-8'),
)![1]

function commit(): string {
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
  } catch {
    return 'dev'
  }
}

// GitHub Pages serves the site under /AnchorsFactory/. The worker loads the
// wheels by absolute URL from the base, so the base must be absolute.
export default defineConfig(({ command, isPreview }) => ({
  base: command === 'build' || isPreview ? '/AnchorsFactory/' : '/',
  plugins: [studioMarkup()],
  worker: { format: 'es' },
  // the engine, the Studio and the sample rules are read from the checkout
  server: { fs: { allow: ['..'] } },
  define: {
    __AF_VERSION__: JSON.stringify(version),
    __BUILD_COMMIT__: JSON.stringify(commit()),
  },
}))
