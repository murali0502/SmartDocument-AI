import { SystemStatus } from "./features/status/SystemStatus"

export function App() {
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
          <a className="text-link" href="/api/v1/docs">API workspace</a>
        </div>
      </header>
      <main className="layout main">
        <SystemStatus />
      </main>
    </>
  )
}
