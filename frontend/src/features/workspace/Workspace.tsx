import { useEffect, useState } from "react"
import type { FormEvent } from "react"

import type { components } from "../../generated/api"

type DocumentJob = components["schemas"]["DocumentJob"]
type DocumentList = components["schemas"]["DocumentList"]
type Structure = components["schemas"]["StructureInfo"]
type Upload = components["schemas"]["UploadReceipt"]
type Answer = components["schemas"]["Answer"]
type Hit = components["schemas"]["SearchHit"]
type Source = components["schemas"]["ChunkSource"]

const api = "/api/v1/workspaces/local"

type Entry = DocumentJob & { structure?: Structure }

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, cache: "no-store" })
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    throw new Error(problem?.detail ?? `Request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

function state(entry: Entry) {
  return entry.job.status === "failed" || entry.structure?.status === "failed" ? "Failed"
    : entry.structure?.status === "ready" ? "Ready" : "Processing"
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}

function merge(current: Entry[], next: Entry[]) {
  const entries = new Map(current.map(entry => [entry.document.id, entry]))
  for (const entry of next) entries.set(entry.document.id, entry)
  return [...entries.values()]
}

function location(hit: Hit) {
  const parts = [
    hit.locator.page && `Page ${hit.locator.page}`,
    hit.locator.slide && `Slide ${hit.locator.slide}`,
    hit.locator.sheet && `Sheet ${hit.locator.sheet}`,
    hit.locator.cell && `Cell ${hit.locator.cell}`,
    hit.section_path.map(section => section.title).join(" / "),
  ].filter(Boolean)
  return parts.join(" · ") || `Source unit ${hit.evidence.source.unit}`
}

export function Workspace() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [selected, setSelected] = useState("")
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [source, setSource] = useState<{ hit: Hit; text: string } | null>(null)
  const [libraryError, setLibraryError] = useState("")
  const [answerError, setAnswerError] = useState("")
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [asking, setAsking] = useState(false)
  const [sourceBusy, setSourceBusy] = useState(false)

  async function load(after?: string) {
    setLoading(true)
    setLibraryError("")
    try {
      const result = await json<DocumentList>(`${api}/documents${after ? `?after=${after}` : ""}`)
      setEntries(current => merge(current, result.items.map(item => ({
        ...item,
        structure: current.find(entry => entry.document.id === item.document.id)?.structure,
      }))))
      setCursor(result.next_cursor)
    } catch (error) {
      setLibraryError(message(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const pending = entries.filter(entry => state(entry) === "Processing").map(entry => entry.document.id)
  const pendingKey = pending.join(",")
  useEffect(() => {
    if (!pendingKey) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      const updates = await Promise.allSettled(pendingKey.split(",").map(async id => ({
        id,
        structure: await json<Structure>(`${api}/documents/${id}/structure`),
      })))
      if (stopped) return
      setEntries(current => current.map(entry => {
        const update = updates.find(item => item.status === "fulfilled" && item.value.id === entry.document.id)
        return update?.status === "fulfilled" ? { ...entry, structure: update.value.structure } : entry
      }))
      timer = setTimeout(() => void poll(), 1500)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [pendingKey])

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const file = new FormData(form).get("document")
    if (!(file instanceof File) || !file.size) return
    setUploading(true)
    setLibraryError("")
    try {
      const receipt = await json<Upload>(`${api}/uploads?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-SmartDoc-Upload": "1" },
        body: file,
      })
      setEntries(current => merge(current, [receipt]))
      form.reset()
    } catch (error) {
      setLibraryError(message(error))
    } finally {
      setUploading(false)
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !question.trim()) return
    setAsking(true)
    setAnswer(null)
    setSource(null)
    setAnswerError("")
    try {
      setAnswer(await json<Answer>(`${api}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, document_id: selected }),
      }))
    } catch (error) {
      setAnswerError(message(error))
    } finally {
      setAsking(false)
    }
  }

  async function openSource(hit: Hit) {
    setSourceBusy(true)
    setAnswerError("")
    try {
      const result = await json<Source>(hit.source_url)
      setSource({ hit, text: result.primary.text })
    } catch (error) {
      setAnswerError(message(error))
    } finally {
      setSourceBusy(false)
    }
  }

  const ready = entries.filter(entry => state(entry) === "Ready")
  const hits = (answer?.status === "answered" ? answer.citations : answer?.related_passages) ?? []

  return (
    <>
      <div className="page-title"><div><h1>Ask SmartDoc</h1>
        <p>Upload a document, ask a question, and check the source.</p></div></div>
      <div className="workspace-grid">
        <section className="workspace-panel" aria-labelledby="library">
          <h2 id="library">Document library</h2>
          <form onSubmit={upload} className="workspace-form">
            <label htmlFor="document">Choose a document</label>
            <input id="document" name="document" type="file" required
              accept=".pdf,.docx,.txt,.md,.html,.csv,.xlsx,.pptx,.json,.yaml,.yml,.png,.jpg,.jpeg,.tif,.tiff" />
            <button disabled={uploading}>{uploading ? "Uploading…" : "Upload document"}</button>
          </form>
          {libraryError && <p role="alert">{libraryError}</p>}
          {loading && <p role="status">Loading documents…</p>}
          {!loading && entries.length === 0 && <p className="muted">Your uploads will appear here.</p>}
          <ul className="document-list">
            {entries.map(entry => <li key={entry.document.id}>
              <strong>{entry.document.filename}</strong>
              <span data-state={state(entry) === "Ready" ? "ready" : state(entry) === "Failed" ? "issue" : "pending"}>
                {state(entry)}
              </span>
              {state(entry) === "Failed" && <small>{entry.job.error_message ?? "Processing failed. Check the file and format."}</small>}
            </li>)}
          </ul>
          {cursor && <button disabled={loading} onClick={() => void load(cursor)}>Load more</button>}
          {libraryError && <button disabled={loading} onClick={() => void load()}>Refresh library</button>}
        </section>
        <section className="workspace-panel" aria-labelledby="question-title">
          <h2 id="question-title">Ask a question</h2>
          <form className="workspace-form" onSubmit={ask}>
            <label htmlFor="scope">Document</label>
            <select id="scope" value={selected} required disabled={asking || sourceBusy}
              onChange={event => { setSelected(event.target.value); setAnswer(null); setSource(null) }}>
              <option value="">Choose a ready document</option>
              {ready.map(entry => <option key={entry.document.id} value={entry.document.id}>
                {entry.document.filename}
              </option>)}
            </select>
            <label htmlFor="question">Question</label>
            <textarea id="question" rows={3} maxLength={512} required disabled={asking || sourceBusy}
              placeholder="What does the pump require?" value={question}
              onChange={event => setQuestion(event.target.value)} />
            <small className="muted">Ask for a definition, requirement, or dependency.</small>
            <button disabled={asking || sourceBusy || !selected || !question.trim()}>{asking ? "Searching…" : "Ask SmartDoc"}</button>
          </form>
          {answerError && <p role="alert">{answerError}</p>}
          {answer && <section className="answer-result" aria-live="polite">
            <h3>{answer.status === "answered" ? "Answer" : "Insufficient evidence"}</h3>
            <p>{answer.answer ?? "SmartDoc couldn’t verify a direct answer in this document."}</p>
            {hits.length > 0 && <ul className="citation-list">{hits.map(hit => <li key={hit.chunk_id}>
              {answer.status !== "answered" && <p className="muted">{hit.evidence.text.slice(0, 240)}{hit.evidence.text.length > 240 && "…"}</p>}
              <button type="button" disabled={asking || sourceBusy} onClick={() => void openSource(hit)}>
                {answer.status === "answered" ? "Open citation" : "Open related passage"} · {location(hit)}
              </button>
            </li>)}</ul>}
          </section>}
          {source && <section className="source-card" aria-live="polite">
            <h3>Source excerpt</h3>
            <p className="muted">{source.hit.filename} · {location(source.hit)}</p>
            <blockquote>{source.text}</blockquote>
            <p><a href={`${api}/documents/${source.hit.document_id}/original`} download>Download original</a></p>
          </section>}
        </section>
      </div>
    </>
  )
}
