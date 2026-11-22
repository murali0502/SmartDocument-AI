import type { components, paths } from "../../generated/api"

type DatabaseStatus = components["schemas"]["Readiness"]["database"]
type HealthPath = Extract<keyof paths, `/api/v1/health/${string}`>

export type Snapshot = {
  api: boolean
  database: DatabaseStatus | "unknown"
  checkedAt: string
}

const databaseStates = {
  ready: true,
  missing: true,
  migration_required: true,
  unavailable: true,
} satisfies Record<DatabaseStatus, true>

function isDatabaseStatus(value: unknown): value is DatabaseStatus {
  return typeof value === "string" && Object.hasOwn(databaseStates, value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

async function probe(path: HealthPath, signal: AbortSignal) {
  const response = await fetch(path, { signal, cache: "no-store" })
  const data: unknown = await response.json()
  return { code: response.status, data }
}

export async function checkServices(signal: AbortSignal): Promise<Snapshot> {
  const deadline = AbortSignal.any([signal, AbortSignal.timeout(5_000)])
  const [live, ready] = await Promise.allSettled([
    probe("/api/v1/health/live", deadline),
    probe("/api/v1/health/ready", deadline),
  ])

  const api = live.status === "fulfilled" && live.value.code === 200
    && isRecord(live.value.data) && live.value.data.status === "alive"
  const result: Snapshot = { api, database: "unknown", checkedAt: new Date().toISOString() }

  if (ready.status === "fulfilled") {
    const { code, data } = ready.value
    if ((code === 200 || code === 503) && isRecord(data)
      && isDatabaseStatus(data.database)
      && typeof data.checked_at === "string" && Number.isFinite(Date.parse(data.checked_at))) {
      const databaseReady = data.database === "ready"
      if (databaseReady === (code === 200) && data.status === (databaseReady ? "ready" : "unavailable")) {
        result.database = data.database
        result.checkedAt = data.checked_at
      }
    }
  }

  return result
}
