import { SystemStatus } from "./features/status/SystemStatus"
import { Workspace } from "./features/workspace/Workspace"

export function App() {
  const showStatus = new URLSearchParams(window.location.search).has("status")
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
            <a className="text-link" href={showStatus ? "/" : "/?status"}>{showStatus ? "Documents" : "System status"}</a>
            <a className="text-link" href="/api/v1/docs">API workspace</a>
          </nav>
        </div>
      </header>
      <main className="layout main">
        {showStatus ? <SystemStatus /> : <Workspace />}
      </main>
    </>
  )
}
