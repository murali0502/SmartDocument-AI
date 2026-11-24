import { useState } from "react"
import type { ReactNode } from "react"
import { apiFetch, apiOrigin, message } from "./api"

export function ApiFile({ path, children, download = false }: {
  path: string
  children: ReactNode
  download?: boolean
}) {
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  if (!apiOrigin) {
    return <a href={path} download={download || undefined} target={download ? undefined : "_blank"} rel="noreferrer">{children}</a>
  }
  return <>
    <button type="button" disabled={busy} onClick={async () => {
      setBusy(true)
      setError("")
      const tab = download ? null : window.open("", "_blank")
      if (tab) tab.opener = null
      try {
        const response = await apiFetch(path)
        if (!response.ok) throw new Error(`Could not open the source (${response.status}).`)
        const url = URL.createObjectURL(await response.blob())
        if (tab) {
          tab.location.href = url
        } else {
          const disposition = response.headers.get("Content-Disposition") ?? ""
          const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
          const filename = encoded ? decodeURIComponent(encoded) : disposition.match(/filename="([^"]+)"/i)?.[1]
          const link = document.createElement("a")
          link.href = url
          link.download = filename ?? (download ? "smartdoc-document" : "smartdoc-page.jpg")
          link.click()
        }
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      } catch (cause) {
        tab?.close()
        setError(message(cause))
      } finally {
        setBusy(false)
      }
    }}>{busy ? "Opening…" : children}</button>
    {error && <small role="alert">{error}</small>}
  </>
}
