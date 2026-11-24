import { useEffect, useState } from "react"
import { json, message } from "./api"

export function useResource<T>(url: string) {
  const [value, setValue] = useState<{ url: string; data?: T; error?: string }>()
  const [attempt, reload] = useState(0)
  const key = url ? `${url}|${attempt}` : ""
  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    json<T>(url, { signal: controller.signal }).then(
      data => { if (!controller.signal.aborted) setValue({ url: key, data }) },
      error => { if (!controller.signal.aborted) setValue({ url: key, error: message(error) }) },
    )
    return () => controller.abort()
  }, [url, key])
  const current = value?.url === key ? value : undefined
  return { data: current?.data, error: current?.error, loading: Boolean(url && !current), refresh: () => reload(n => n + 1) }
}

export function RequestState({ result }: { result: { loading: boolean; error?: string; refresh: () => void } }) {
  return <>
    {result.loading && <p role="status">Loading…</p>}
    {result.error && <div><p role="alert">{result.error}</p><button onClick={result.refresh}>Try again</button></div>}
  </>
}
