import { useCallback, useEffect, useRef, useState } from "react"
import { checkServices, type Snapshot } from "./health"

const databaseLabels: Record<Snapshot["database"], string> = {
  ready: "Schema current",
  missing: "Database missing",
  migration_required: "Migration required",
  unavailable: "Connection failed",
  unknown: "Status unavailable",
}

const timeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
})

type CheckRowProps = {
  name: string
  description: string
  label: string
  state: "ready" | "issue" | "pending"
}

function CheckRow({ name, description, label, state }: CheckRowProps) {
  return (
    <li className="check-row">
      <div className="check-label">
        <span className="check-icon" data-state={state} aria-hidden="true">
          {state === "ready" ? "✓" : state === "issue" ? "!" : "·"}
        </span>
        <div>
          <strong>{name}</strong>
          <p>{description}</p>
        </div>
      </div>
      <span className="check-result" data-state={state}>{label}</span>
    </li>
  )
}

export function SystemStatus() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [checking, setChecking] = useState(true)
  const active = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setChecking(true)
    const next = await checkServices(controller.signal)
    if (!controller.signal.aborted) {
      setSnapshot(next)
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => active.current?.abort()
  }, [refresh])

  const ready = snapshot?.api && snapshot.database === "ready"
  const summary = !snapshot ? "Checking services" : ready ? "System ready" : "System needs attention"
  const guidance = !snapshot
    ? "Contacting the local API and checking database readiness."
    : !snapshot.api
      ? "Start the local FastAPI server, then refresh the checks."
      : snapshot.database === "missing" || snapshot.database === "migration_required"
        ? "Run the database migrations, then refresh the checks."
        : ready
          ? "The API is responding and the SQLite schema is current."
          : "Check that the database file is readable, then refresh the checks."

  return (
    <>
      <div className="page-title">
        <div>
          <h1>System status</h1>
          <p>Local development workspace</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={checking}>
          {checking ? "Checking…" : "Refresh checks"}
        </button>
      </div>
      <section className="status-panel" aria-label="Service checks" aria-busy={checking}>
        <div className="status-summary" role="status">
          <span className="status-dot" data-state={!snapshot ? "pending" : ready ? "ready" : "issue"} />
          <div>
            <h2>{summary}</h2>
            <p>{guidance}</p>
          </div>
        </div>
        <ul className="check-list">
          <CheckRow
            name="API"
            description="FastAPI process"
            label={!snapshot ? "Checking" : snapshot.api ? "Responding" : "Unreachable"}
            state={!snapshot ? "pending" : snapshot.api ? "ready" : "issue"}
          />
          <CheckRow
            name="Database"
            description="SQLite connection and migrations"
            label={snapshot ? databaseLabels[snapshot.database] : "Checking"}
            state={!snapshot ? "pending" : snapshot.database === "ready" ? "ready" : "issue"}
          />
        </ul>
        {snapshot ? (
          <div className="status-footer">
            Last checked <time dateTime={snapshot.checkedAt}>{timeFormat.format(new Date(snapshot.checkedAt))}</time>
          </div>
        ) : null}
      </section>
    </>
  )
}
