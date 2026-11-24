import { Explore } from "./features/explore/Explore"
import { SystemStatus } from "./features/status/SystemStatus"
import { Workspace } from "./features/workspace/Workspace"

export function App() {
  const params = new URLSearchParams(window.location.search)
  const view = params.has("status") ? "status" : params.get("view") ?? "ask"
  const explore = view === "documents" || view === "concepts" || view === "graph" || view === "compare" || view === "search"
  return (
    <>
      <header className="masthead">
        <div className="layout masthead-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <i /><i /><i /><i />
            </span>
            <div>
              <strong>SmartDoc AI</strong>
              <span>Next Concept Modelling</span>
            </div>
          </div>
          <nav className="workspace-nav" aria-label="Workspace">
            <a className="text-link" href="/" aria-current={view === "ask" ? "page" : undefined}>Ask SmartDoc</a>
            <a className="text-link" href="/?view=documents" aria-current={view === "documents" ? "page" : undefined}>Documents</a>
            <a className="text-link" href="/?view=search" aria-current={view === "search" ? "page" : undefined}>Search</a>
            <a className="text-link" href="/?view=concepts" aria-current={view === "concepts" ? "page" : undefined}>Concepts</a>
            <a className="text-link" href="/?view=graph" aria-current={view === "graph" ? "page" : undefined}>Knowledge graph</a>
            <a className="text-link" href="/?view=compare" aria-current={view === "compare" ? "page" : undefined}>Compare</a>
            <a className="text-link" href="/?status" aria-current={view === "status" ? "page" : undefined}>System status</a>
            <a className="text-link" href="/api/v1/docs">API workspace</a>
          </nav>
        </div>
      </header>
      <main className="layout main">
        {view === "status" ? <SystemStatus /> : explore ? <Explore page={view} /> : <Workspace />}
      </main>
    </>
  )
}
