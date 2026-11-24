import { useEffect, useState } from "react"
import { Explore } from "./features/explore/Explore"
import { Insights } from "./features/insights/Insights"
import { SystemStatus } from "./features/status/SystemStatus"
import { Workspace } from "./features/workspace/Workspace"

const links = [
  { view: "ask", name: "Ask SmartDoc", glyph: "✦", href: "/" },
  { view: "documents", name: "Documents", glyph: "▤", href: "/?view=documents" },
  { view: "search", name: "Search", glyph: "⌕", href: "/?view=search" },
  { view: "concepts", name: "Concepts", glyph: "◇", href: "/?view=concepts" },
  { view: "graph", name: "Knowledge graph", glyph: "⌘", href: "/?view=graph" },
  { view: "compare", name: "Compare", glyph: "⇄", href: "/?view=compare" },
  { view: "analytics", name: "Analytics", glyph: "▥", href: "/?view=analytics" },
  { view: "evaluation", name: "Evaluation", glyph: "✓", href: "/?view=evaluation" },
  { view: "status", name: "System status", glyph: "◎", href: "/?status" },
  { view: "settings", name: "Settings", glyph: "⚙", href: "/?view=settings" },
] as const

export function App() {
  const params = new URLSearchParams(window.location.search)
  const requested = params.has("status") ? "status" : params.get("view")
  const view = links.find(link => link.view === requested)?.view ?? "ask"
  const explore = view === "documents" || view === "concepts" || view === "graph" || view === "compare" || view === "search"
  const [theme, setTheme] = useState(() => localStorage.getItem("smartdoc-theme") === "dark" ? "dark" : "light")
  const [motion, setMotion] = useState(() => localStorage.getItem("smartdoc-motion") !== "off")
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.dataset.motion = motion ? "on" : "off"
    localStorage.setItem("smartdoc-theme", theme)
    localStorage.setItem("smartdoc-motion", motion ? "on" : "off")
  }, [theme, motion])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="masthead">
        <div className="masthead-inner">
          <a className="brand" href="/">
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
            <div><strong>SmartDoc<span>AI</span></strong><small>Document intelligence</small></div>
          </a>
          <nav className="workspace-nav" aria-label="Workspace">
            {links.map(link => <a key={link.view} className="text-link" href={link.href}
              aria-current={view === link.view ? "page" : undefined}>
              <span aria-hidden="true">{link.glyph}</span>{link.name}
            </a>)}
          </nav>
          <a className="api-link" href="/api/v1/docs">API workspace <span aria-hidden="true">→</span></a>
        </div>
      </header>
      <main id="main-content" className="layout main">
        <div className="topline"><span>Workspace</span><span aria-hidden="true">/</span><strong>{links.find(link => link.view === view)?.name}</strong></div>
        {view === "status" ? <SystemStatus /> : explore ? <Explore page={view} /> :
          view === "analytics" || view === "evaluation" ? <Insights page={view} /> :
          view === "settings" ? <>
            <div className="page-title"><h1>Settings</h1></div>
            <section className="workspace-panel settings-panel">
              <h2>Appearance</h2>
              <label htmlFor="theme">Color theme</label>
              <select id="theme" value={theme} onChange={event => setTheme(event.target.value === "dark" ? "dark" : "light")}>
                <option value="light">Light</option><option value="dark">Dark</option>
              </select>
              <label className="toggle"><input type="checkbox" checked={motion} onChange={event => setMotion(event.target.checked)} /> Interface animations</label>
            </section>
          </> : <Workspace />}
      </main>
    </div>
  )
}
