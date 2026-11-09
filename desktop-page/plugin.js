// Annotary for Hermes: the desktop page (native Desktop and the Webapp, so phones too).
//
// Installed by the agent half as a standalone desktop plugin in <root>/desktop-plugins/annotary/
// (no package marker), so it loads switched on in every browser. Plain ESM, loaded uncompiled:
// imports only @hermes/plugin-sdk, react and react/jsx-runtime. Everything goes through ctx.rest
// to the plugin's backend (/api/plugins/annotary/), which works from every surface.

import {
  Button,
  host,
  ROUTES_AREA,
  SandboxedFrame,
  SIDEBAR_NAV_AREA,
  TRANSCRIPT_DIRECTIVE_AREA
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'annotary'
const PATH = '/annotary'
const POLL_MS = 10000
// Must match the frame width Annotary's embedded page folds its own Action buttons at (its `cd` container breakpoint).
export const FRAME_ACTIONS_MIN_WIDTH = 850
const DOC_RE = /^[a-z0-9]{1,16}$/

let rest = null
let os = null
const listeners = new Set() // page and cards re-fetch when the backend broadcasts a change
const frames = new Set() // live embed frames: a change makes them poll at once

function changed(payload) {
  for (const fn of listeners) {
    try { fn(payload) } catch (err) { console.warn('[annotary] listener failed', err) }
  }
  for (const frame of frames) {
    try { frame?.contentWindow?.postMessage({ type: 'annotary-event' }, '*') } catch (err) { /* frame gone */ }
  }
}

function useLive(load, deps) {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const fn = () => setTick(n => n + 1)
    listeners.add(fn)
    const timer = setInterval(fn, POLL_MS) // cleared on unmount; the SDK says sockets can drop
    return () => { listeners.delete(fn); clearInterval(timer) }
  }, [])
  useEffect(() => { load() }, [tick, ...deps])
  return () => setTick(n => n + 1)
}

function hashDoc() {
  const h = window.location.hash || ''
  const q = h.indexOf('?')
  const doc = q >= 0 ? new URLSearchParams(h.slice(q + 1)).get('doc') : null
  return doc && DOC_RE.test(doc) ? doc : null
}

// Where the frame went, for the page: a Document (any Version, any Thread) selects it; the list
// clears the selection so the review bar goes and the same Document can be opened again.
export function applyNav(path, current, { setDoc, toList }) {
  const m = /^\/d\/([a-z0-9]{1,16})(?=$|[/?#])/.exec(path || '')
  if (m) {
    if (m[1] !== current) setDoc(m[1])
    return m[1]
  }
  if (/^\/(?:$|[?#])/.test(path || '')) {
    if (current !== null) { setDoc(null); toList() }
    return null
  }
  return current // another page in the frame (an error page): leave the selection as it is
}

function errText(err) { return String(err?.message || err || 'failed').slice(0, 300) }

// The rendered Document in a sandboxed frame (opaque origin, no scripts in its HTML). Colors come
// from the app's theme variables, resolved now, so it follows light and dark.
function themed(html) {
  const cs = getComputedStyle(document.documentElement)
  const v = (name, fallback) => (cs.getPropertyValue(name) || '').trim() || fallback
  const fg = v('--foreground', 'CanvasText')
  const muted = v('--muted-foreground', 'GrayText')
  const border = v('--border', 'GrayText')
  const accent = v('--accent', 'LinkText')
  const css = `:root{color-scheme:light dark}body{margin:0;padding:12px 16px;font:15px/1.55 system-ui,-apple-system,sans-serif;color:${fg};background:transparent}` +
    `a{color:${accent}}code,pre{font-family:ui-monospace,monospace;font-size:13px}pre{overflow:auto;padding:8px;border:1px solid ${border};border-radius:6px}` +
    `blockquote{margin:0;padding-left:12px;border-left:3px solid ${border};color:${muted}}table{border-collapse:collapse}td,th{border:1px solid ${border};padding:4px 8px}img{max-width:100%}`
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style>${html}`)
}

const muted = { color: 'var(--ui-text-tertiary)' }
const box = { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 8, padding: 10 }

function TextBox({ value, onChange, placeholder, rows = 2 }) {
  return jsx('textarea', {
    value, placeholder, rows,
    onChange: e => onChange(e.target.value),
    style: { width: '100%', fontSize: 16, padding: 6, borderRadius: 6, border: '1px solid var(--ui-stroke-secondary)', background: 'transparent', color: 'inherit', resize: 'vertical' }
  })
}

function ThreadCard({ doc, t, onDone }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async resolve => {
    setBusy(true)
    try {
      if (text.trim()) await rest('/reply', { method: 'POST', body: { doc, thread: t.id, text, resolve } })
      else if (resolve) await rest('/resolve', { method: 'POST', body: { doc, thread: t.id } })
      setText(''); onDone()
    } catch (err) { host.notifyError(err, 'Could not reply') } finally { setBusy(false) }
  }
  const quote = t.anchor?.original?.exact
  return jsxs('div', {
    'data-annotary-thread': t.id,
    style: { ...box, display: 'flex', flexDirection: 'column', gap: 6 },
    children: [
      jsxs('div', { style: { fontSize: 12, ...muted }, children: [`${t.id} · @${t.author}`, quote ? ` · “${quote.slice(0, 80)}”` : ' · whole Document'] }),
      jsx('div', { style: { whiteSpace: 'pre-wrap' }, children: t.body }),
      ...(t.replies || []).map(r => jsxs('div', {
        key: r.id,
        style: { marginLeft: 12, paddingLeft: 8, borderLeft: '2px solid var(--ui-stroke-secondary)', whiteSpace: 'pre-wrap' },
        children: [jsx('span', { style: { fontSize: 12, ...muted }, children: `@${r.author}  ` }), r.body]
      })),
      jsx(TextBox, { value: text, onChange: setText, placeholder: 'Reply…', rows: 1 }),
      jsxs('div', {
        style: { display: 'flex', gap: 6 },
        children: [
          jsx(Button, { size: 'sm', disabled: busy || !text.trim(), onClick: () => send(false), children: 'Reply' }),
          jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => send(true), children: text.trim() ? 'Reply and resolve' : 'Resolve' })
        ]
      })
    ]
  })
}

// Embed mode, protocol v1 (Annotary's docs/dev/web-document-view.md, "Embed mode"): Annotary's own
// server-rendered pages in a sandboxed frame with an opaque origin. The frame posts each HTTP
// request here; it goes to the backend (/proxy, which adds the owner Token) and the answer goes
// back. The frame is mounted once; picking another Document re-sends annotary-init.
function b64ToBytes(b64) {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function openExternal(d) {
  if (typeof d.url === 'string' && /^(https?:|mailto:)/i.test(d.url)) { await os?.openExternal(d.url); return }
  if (typeof d.path !== 'string' || !d.path.startsWith('/') || d.path.startsWith('//')) return
  // A server path (an Asset): fetch it through the backend and hand the browser a file.
  const r = await rest('/proxy', { method: 'POST', body: { method: 'GET', path: d.path, headers: {}, body: null, binary: true }, timeoutMs: 60000 })
  if (r.status !== 200) { host.notify({ kind: 'warning', message: r.status === 413 ? 'Too large to open through Hermes' : `Could not open it (${r.status})` }); return }
  const blob = new Blob([b64ToBytes(r.body)], { type: r.headers?.['content-type'] || 'application/octet-stream' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = decodeURIComponent(d.path.split('/').pop() || 'annotary-asset')
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 60000)
}

function EmbedFrame({ doc, onNav }) {
  const ref = useRef(null)
  const ready = useRef(false)
  const shown = useRef(null) // the path the frame last said it shows
  const [src, setSrc] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let live = true
    rest('/shell').then(r => { if (live) setSrc('data:text/html;charset=utf-8,' + encodeURIComponent(r.html)) })
      .catch(err => { if (live) setError(errText(err)) })
    return () => { live = false }
  }, [])
  const init = useCallback(() => {
    const frame = ref.current
    if (!frame || !ready.current) return
    const msg = doc ? { type: 'annotary-init', doc } : { type: 'annotary-init', path: '/' }
    frame.contentWindow?.postMessage(msg, '*')
  }, [doc])
  useEffect(() => {
    // Another Document picked in the list: show it in place, unless the frame already does.
    if (doc && shown.current && shown.current.startsWith(`/d/${doc}`)) return
    init()
  }, [doc, init])
  useEffect(() => {
    const onMessage = async e => {
      const frame = ref.current
      if (!frame || e.source !== frame.contentWindow) return
      const d = e.data
      if (!d || typeof d !== 'object') return
      if (d.type === 'annotary-ready') {
        ready.current = true
        init()
      } else if (d.type === 'annotary-req') {
        let res
        try {
          const r = await rest('/proxy', {
            method: 'POST', timeoutMs: 60000,
            body: { method: d.method, path: d.path, headers: d.headers || {}, body: d.body ?? null, binary: !!d.binary }
          })
          res = { type: 'annotary-res', id: d.id, status: r.status, headers: r.headers || {}, body: r.body, ...(r.encoding ? { encoding: r.encoding } : {}) }
        } catch (err) {
          res = { type: 'annotary-res', id: d.id, status: 0, headers: {}, body: '' }
        }
        try { ref.current?.contentWindow?.postMessage(res, '*') } catch (err) { /* frame gone */ }
      } else if (d.type === 'annotary-nav' && typeof d.path === 'string') {
        shown.current = d.path
        onNav?.(d.path)
      } else if (d.type === 'annotary-open-external') {
        openExternal(d).catch(err => host.notifyError(err, 'Could not open it'))
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [init, onNav])
  if (error) return jsx('div', { style: { padding: 12, ...muted }, children: error })
  return src && jsx(SandboxedFrame, {
    ref: el => { if (ref.current && ref.current !== el) { frames.delete(ref.current); ready.current = false } ref.current = el; if (el) frames.add(el) },
    src, title: 'Annotary', sandbox: 'allow-scripts allow-forms',
    style: { width: '100%', height: '100%', border: 0, flex: 1 }
  })
}

function DocView({ doc, status, onChanged, onNav }) {
  if (status?.embed) return jsx(EmbedDocView, { doc, onChanged, onNav })
  return jsx(NativeDocView, { doc, onChanged })
}

function EmbedDocView({ doc, onChanged, onNav }) {
  const box = useRef(null)
  const [frameWidth, setFrameWidth] = useState(null)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setFrameWidth(entry.contentRect.width))
    if (box.current) observer.observe(box.current)
    return () => observer.disconnect()
  }, [])
  return jsxs('div', {
    ref: box,
    style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 },
    children: [jsx(ReviewBar, { doc, frameWidth, onChanged }), jsx(EmbedFrame, { doc, onNav })]
  })
}

// Above the embedded page: the editor (D11), the last Action, and Send back / Approve only while
// the frame is too narrow to show its own, so one set is on screen at every width.
export function ReviewBar({ doc, frameWidth, onChanged }) {
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { rest(`/doc?id=${doc}`).then(setD).catch(() => {}) }, [doc])
  const refresh = useLive(load, [doc])
  const act = async action => {
    setBusy(true)
    try { await rest('/act', { method: 'POST', body: { doc, action } }); refresh(); onChanged(); changed({ doc }) } catch (err) { host.notifyError(err, 'Could not take the Action') } finally { setBusy(false) }
  }
  if (!d) return null
  const frameFolded = frameWidth != null && frameWidth < FRAME_ACTIONS_MIN_WIDTH
  return jsxs('div', {
    'data-annotary-reviewbar': doc,
    style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid var(--ui-stroke-secondary)' },
    children: [
      jsx('div', { 'data-annotary-editor': '', style: { fontSize: 12, ...muted }, children: `Editor: ${d.editor || 'none yet'}` }),
      d.action && jsx('div', { style: { fontSize: 12, fontWeight: 600 }, children: `${d.action.label} by @${d.action.by}` }),
      jsx('div', { style: { flex: 1 } }),
      ...(frameFolded ? d.actions || [] : []).map(a => jsx(Button, {
        key: a.id, size: 'sm', disabled: busy, variant: a.intent === 'positive' ? 'default' : 'outline',
        'data-annotary-action': a.id, onClick: () => act(a.id), children: a.label
      }))
    ]
  })
}

function NativeDocView({ doc, onChanged }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => {
    rest(`/doc?id=${doc}`).then(r => { setD(r); setError(null) }).catch(err => setError(errText(err)))
  }, [doc])
  const refresh = useLive(load, [doc])
  const act = async action => {
    setBusy(true)
    try { await rest('/act', { method: 'POST', body: { doc, action } }); refresh(); onChanged() } catch (err) { host.notifyError(err, 'Could not take the Action') } finally { setBusy(false) }
  }
  const post = async () => {
    setBusy(true)
    try { await rest('/comment', { method: 'POST', body: { doc, text: comment } }); setComment(''); refresh() } catch (err) { host.notifyError(err, 'Could not comment') } finally { setBusy(false) }
  }
  if (error) return jsx('div', { style: { padding: 12, ...muted }, children: error })
  if (!d) return jsx('div', { style: { padding: 12, ...muted }, children: 'Loading…' })
  return jsxs('div', {
    'data-annotary-doc': d.id,
    style: { display: 'flex', flexDirection: 'column', gap: 10, padding: 12, minHeight: 0, overflow: 'auto', height: '100%' },
    children: [
      jsxs('div', {
        style: { display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 8 },
        children: [
          jsx('div', { style: { fontSize: 18, fontWeight: 600 }, children: d.name }),
          jsx('div', { style: muted, children: `v${d.version} by @${d.by}${d.message ? ` · ${d.message}` : ''}` }),
          jsx('div', { 'data-annotary-editor': '', style: muted, children: `Editor: ${d.editor || 'none yet'}` }),
          d.action && jsx('div', { style: { fontWeight: 600 }, children: `${d.action.label} by @${d.action.by}` })
        ]
      }),
      jsx('div', {
        style: { display: 'flex', gap: 8 },
        children: (d.actions || []).map(a => jsx(Button, {
          key: a.id, disabled: busy, variant: a.intent === 'positive' ? 'default' : 'outline',
          'data-annotary-action': a.id, onClick: () => act(a.id), children: a.label
        }))
      }),
      d.html != null && jsx('div', {
        style: { ...box, padding: 0, height: '45vh', minHeight: 200 },
        children: jsx(SandboxedFrame, { src: themed(d.html), title: d.name, style: { width: '100%', height: '100%', border: 0 } })
      }),
      jsx('div', { style: { fontWeight: 600 }, children: `${d.threads.length} open Thread${d.threads.length === 1 ? '' : 's'}${d.resolved ? ` · ${d.resolved} resolved` : ''}` }),
      ...d.threads.map(t => jsx(ThreadCard, { key: t.id, doc: d.id, t, onDone: refresh })),
      jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', gap: 6 },
        children: [
          jsx(TextBox, { value: comment, onChange: setComment, placeholder: 'Comment on the whole Document (@mention a Bot to ask it)…' }),
          jsx('div', { children: jsx(Button, { size: 'sm', disabled: busy || !comment.trim(), onClick: post, children: 'Comment' }) })
        ]
      })
    ]
  })
}

function AnnotaryPage() {
  const [docs, setDocs] = useState(null)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [doc, setDoc] = useState(hashDoc())
  const load = useCallback(() => {
    rest('/docs').then(r => { setDocs(r.docs); setError(null) }).catch(err => setError(errText(err)))
    rest('/status').then(setStatus).catch(() => {})
  }, [])
  const refresh = useLive(load, [])
  useEffect(() => {
    const onHash = () => { const h = hashDoc(); if (h) setDoc(h) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const narrow = host.state.viewport.get()?.narrow
  const open = id => { setDoc(id); host.navigate(`${PATH}?doc=${id}`) }
  const list = jsxs('div', {
    'data-annotary-list': '',
    style: { display: 'flex', flexDirection: 'column', gap: 4, padding: 8, overflow: 'auto', minWidth: narrow ? 0 : 260, maxWidth: narrow ? 'none' : 320 },
    children: [
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 4px 8px' },
        children: [
          jsx('div', { style: { fontWeight: 600, fontSize: 16 }, children: 'Annotary' }),
          status && jsx('div', { style: { fontSize: 12, ...muted }, title: 'hermes annotary wake on|off', children: status.wake ? 'Wake-ups on' : 'Wake-ups off' })
        ]
      }),
      error && jsx('div', { style: muted, children: error }),
      docs && docs.length === 0 && jsx('div', { style: muted, children: 'No Documents yet. Ask an agent to share a plan with Annotary.' }),
      ...(docs || []).map(d => jsxs('button', {
        key: d.id, type: 'button', 'data-annotary-row': d.id, onClick: () => open(d.id),
        style: { textAlign: 'left', padding: 8, borderRadius: 6, border: '1px solid ' + (d.id === doc ? 'var(--ui-accent)' : 'transparent'), background: 'transparent', color: 'inherit', cursor: 'pointer' },
        children: [
          jsx('div', { style: { fontWeight: 500 }, children: d.title }),
          jsx('div', { style: { fontSize: 12, ...muted }, children: [`v${d.version}`, d.open ? `${d.open} open` : null, d.action, d.editor].filter(Boolean).join(' · ') })
        ]
      }))
    ]
  })
  return jsxs('div', {
    style: { display: 'flex', flexDirection: narrow ? 'column' : 'row', height: '100%', minHeight: 0 },
    children: [
      (!narrow || !doc) && list,
      doc && jsxs('div', {
        style: { flex: 1, minWidth: 0, minHeight: 0, borderLeft: narrow ? 'none' : '1px solid var(--ui-stroke-secondary)', display: 'flex', flexDirection: 'column' },
        children: [
          narrow && jsx('div', { style: { padding: '8px 12px 0' }, children: jsx(Button, { size: 'sm', variant: 'ghost', onClick: () => { setDoc(null); host.navigate(PATH) }, children: '‹ Documents' }) }),
          jsx(DocView, { doc, status, onChanged: refresh, onNav: path => applyNav(path, doc, { setDoc, toList: () => host.navigate(PATH) }) })
        ]
      })
    ]
  })
}

function AnnotaryCard({ attrs }) {
  const doc = typeof attrs?.doc === 'string' && DOC_RE.test(attrs.doc) ? attrs.doc : null
  const [d, setD] = useState(null)
  const load = useCallback(() => { if (doc) rest(`/doc?id=${doc}`).then(setD).catch(() => {}) }, [doc])
  useLive(load, [doc])
  if (!doc) return null
  return jsxs('div', {
    'data-annotary-card': doc,
    style: { ...box, display: 'flex', alignItems: 'center', gap: 12, maxWidth: 520 },
    children: [
      jsxs('div', {
        style: { flex: 1, minWidth: 0 },
        children: [
          jsx('div', { style: { fontWeight: 600 }, children: d ? d.name : `Annotary ${doc}` }),
          jsx('div', { style: { fontSize: 12, ...muted }, children: d ? [`v${d.version}`, `${d.threads.length} open`, d.action ? `${d.action.label} by @${d.action.by}` : null].filter(Boolean).join(' · ') : 'Loading…' })
        ]
      }),
      jsx(Button, { size: 'sm', onClick: () => host.navigate(`${PATH}?doc=${doc}`), children: 'Open' })
    ]
  })
}

export default {
  id: ID,
  name: 'Annotary',
  register(ctx) {
    rest = ctx.rest
    os = ctx.os
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PATH }, render: () => jsx(AnnotaryPage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: PATH, label: 'Annotary', codicon: 'comment-discussion' } },
      { id: 'card', area: TRANSCRIPT_DIRECTIVE_AREA, data: { name: 'annotary', render: props => jsx(AnnotaryCard, props) } }
    ])
    ctx.onEvent(`plugin.${ID}.changed`, ev => changed(ev?.payload))
    ctx.onEvent(`plugin.${ID}.notify`, ev => {
      const p = ev?.payload || {}
      if (!p.doc || !DOC_RE.test(p.doc)) return
      const what = p.reason === 'review' ? `${p.action === 'approve' ? 'Approved' : 'Sent back'} by @${p.by}` : `@${p.by} mentioned @${p.bot}`
      try {
        os?.notify({ title: `Annotary: ${p.name || p.doc}`, body: `${what}. Wake-ups are off: open the chat and tell the agent.`, onActivate: () => host.navigate(`${PATH}?doc=${p.doc}`) })
      } catch (err) { host.notify({ kind: 'info', message: `Annotary: ${what}` }) }
      changed(p)
    })
  }
}
