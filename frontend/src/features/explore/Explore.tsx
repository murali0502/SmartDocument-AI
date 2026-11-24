import { useEffect, useState } from "react"
import type { components } from "../../generated/api"
import { api, json, message } from "../../api"

type Schema = components["schemas"]
type Anchor = Schema["Anchor"]
type Node = Schema["GraphNode"]
type Page = "documents" | "concepts" | "graph" | "compare" | "search"

function useResource<T>(url: string) {
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

function RequestState({ result }: { result: { loading: boolean; error?: string; refresh: () => void } }) {
  return <>
    {result.loading && <p role="status">Loading…</p>}
    {result.error && <div><p role="alert">{result.error}</p><button onClick={result.refresh}>Try again</button></div>}
  </>
}

function AnchorCard({ anchor }: { anchor: Anchor }) {
  const location = Object.entries(anchor.locator).map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`).join(" · ")
  return <blockquote className="evidence-block">
    {anchor.text}
    <footer>{location || `Source unit ${anchor.source.unit}`} · <a href={`${api}/documents/${anchor.document_id}/original`} download>Download original</a></footer>
  </blockquote>
}

function DocumentDetail({ id }: { id: string }) {
  const [after, setAfter] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const info = useResource<Schema["StructureInfo"]>(`${api}/documents/${id}/structure`)
  const chunks = useResource<Schema["ChunkPage"]>(info.data?.status === "ready" ? `${api}/documents/${id}/chunks?after=${after}` : "")
  return <section className="workspace-panel">
    <h2>Document detail</h2>
    <p><a href={`${api}/documents/${id}/original`} download>Download original</a></p>
    <RequestState result={info} />
    {info.data && <p>{info.data.status === "ready" ? `${info.data.chunk_count ?? 0} source passages` : `Processing status: ${info.data.status}`}</p>}
    {info.data?.status === "pending" && <button onClick={info.refresh}>Refresh status</button>}
    <RequestState result={chunks} />
    {chunks.data?.items.map(chunk => <details key={chunk.id} className="explore-row">
      <summary>{chunk.section_path.at(-1)?.title ?? chunk.element_type.replaceAll("_", " ")} · Passage {chunk.ordinal}</summary>
      <p className="passage">{chunk.text}</p>
    </details>)}
    <Pagination cursor={chunks.data?.next_cursor} after={after} history={history} setAfter={setAfter} setHistory={setHistory} />
  </section>
}

function Pagination({ cursor, after, history, setAfter, setHistory }: {
  cursor?: number | null; after: number; history: number[]
  setAfter: (value: number) => void; setHistory: (history: number[]) => void
}) {
  return <div className="explore-actions">
    {history.length > 0 && <button onClick={() => { setAfter(history.at(-1) ?? 0); setHistory(history.slice(0, -1)) }}>Previous page</button>}
    {cursor != null && <button onClick={() => { setHistory([...history, after]); setAfter(cursor) }}>Next page</button>}
  </div>
}

function Concepts({ id }: { id: string }) {
  const [after, setAfter] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const result = useResource<Schema["Page_Concept_"]>(`${api}/documents/${id}/ncm/concepts?after=${after}`)
  return <section className="workspace-panel">
    <h2>Concepts</h2><RequestState result={result} />
    {result.data?.items.length === 0 && <p>No concepts were extracted.</p>}
    {result.data?.items.map(concept => <details key={concept.id} className="explore-row">
      <summary>{concept.label} <span className="muted">· {concept.category}</span></summary>
      {concept.aliases?.length ? <p>Aliases · {concept.aliases.map(alias => alias.surface).join(", ")}</p> : null}
      {concept.definitions?.map((definition, index) => <AnchorCard key={index} anchor={definition.quote} />)}
      {concept.mentions.slice(0, 5).map((mention, index) => <AnchorCard key={index} anchor={mention.evidence} />)}
    </details>)}
    <Pagination cursor={result.data?.next_cursor} after={after} history={history} setAfter={setAfter} setHistory={setHistory} />
  </section>
}

function Graph() {
  const [term, setTerm] = useState("")
  const [query, setQuery] = useState("")
  const [after, setAfter] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const [selected, select] = useState<Node>()
  const nodes = useResource<Schema["GraphPage_GraphNode_"]>(
    `${api}/graph/nodes?kind=concept&after=${after}${query ? `&query=${encodeURIComponent(query)}` : ""}`,
  )
  const graph = useResource<Schema["Neighborhood"]>(
    selected && nodes.data ? `${api}/graph/neighbors?node_id=${selected.id}&version_id=${nodes.data.version_id}` : "",
  )
  const version = useResource<Schema["GraphRevision"]>(nodes.data ? `${api}/graph/versions/${nodes.data.version_id}` : "")
  const labels = new Map(graph.data?.nodes.map(node => [node.id, node.label]))
  return <div className="workspace-grid">
    <section className="workspace-panel">
      <h2>Find a concept</h2>
      {version.data && <p className="muted">{version.data.document_count} documents · {version.data.node_count} nodes · {version.data.edge_count} relationships</p>}
      <form className="workspace-form" onSubmit={event => {
        event.preventDefault(); setQuery(term.trim()); setAfter(0); setHistory([]); select(undefined)
      }}>
        <label htmlFor="node-query">Concept name</label>
        <input id="node-query" value={term} maxLength={120} onChange={event => setTerm(event.target.value)} />
        <button>Find concepts</button>
      </form>
      <RequestState result={nodes} />
      {nodes.data?.items.length === 0 && <p>No matching concepts.</p>}
      <ul className="explore-list">{nodes.data?.items.map(node => <li key={node.id}>
        <button aria-pressed={selected?.id === node.id} onClick={() => select(node)}>{node.label}</button>
      </li>)}</ul>
      <Pagination cursor={nodes.data?.next_cursor} after={after} history={history} setAfter={next => { select(undefined); setAfter(next) }} setHistory={setHistory} />
    </section>
    <section className="workspace-panel">
      <h2>{selected ? `Connections for ${selected.label}` : "Concept connections"}</h2>
      {!selected && <p className="muted">Select a concept to inspect its relationships and supporting passages.</p>}
      <RequestState result={graph} />
      {graph.data?.edges.length === 0 && <p>No connected relationships.</p>}
      {graph.data?.edges.map(({ edge, evidence }) => <details className="explore-row" key={edge.id}>
        <summary>{labels.get(edge.source_id) ?? "Concept"} → {edge.predicate.toLowerCase().replaceAll("_", " ")} → {labels.get(edge.target_id) ?? "Concept"}</summary>
        <AnchorCard anchor={evidence} />
      </details>)}
      {graph.data?.truncated && <p className="muted">Showing the first set of connections.</p>}
    </section>
  </div>
}

function Comparison({ left, right }: { left: string; right: string }) {
  const [after, setAfter] = useState(0)
  const [history, setHistory] = useState<number[]>([])
  const result = useResource<Schema["Comparison"]>(
    left && right && left !== right ? `${api}/ncm/compare?left=${left}&right=${right}&after=${after}` : "",
  )
  return <section className="workspace-panel">
    <h2>Concept differences</h2><RequestState result={result} />
    {!left || !right || left === right ? <p>Choose two different documents.</p> : null}
    {result.data?.changes.items.length === 0 && <p>No concept differences found.</p>}
    {result.data?.changes.items.map((change, index) => <details className="explore-row" key={index}>
      <summary>{change.left_label ?? change.right_label} · {change.kind.replaceAll("_", " ")}</summary>
      <div className="comparison-columns">
        <div><h3>First document</h3>{change.left_evidence.map((anchor, i) => <AnchorCard key={i} anchor={anchor} />)}</div>
        <div><h3>Second document</h3>{change.right_evidence.map((anchor, i) => <AnchorCard key={i} anchor={anchor} />)}</div>
      </div>
    </details>)}
    <Pagination cursor={result.data?.changes.next_cursor} after={after} history={history} setAfter={setAfter} setHistory={setHistory} />
  </section>
}

function Search() {
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<Schema["SearchResponse"]>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  return <section className="workspace-panel">
    <form className="workspace-form" onSubmit={async event => {
      event.preventDefault()
      if (!query.trim() || busy) return
      setBusy(true)
      setResult(undefined)
      setError("")
      try {
        setResult(await json<Schema["SearchResponse"]>(`${api}/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query }),
        }))
      } catch (cause) {
        setError(message(cause))
      } finally {
        setBusy(false)
      }
    }}>
      <label htmlFor="passage-query">Search uploaded documents</label>
      <input id="passage-query" maxLength={512} value={query} required onChange={event => setQuery(event.target.value)} />
      <button disabled={busy || !query.trim()}>{busy ? "Searching…" : "Search passages"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {result?.items.length === 0 && <p role="status">No matching passages.</p>}
    {result?.items.map(hit => <details className="explore-row" key={hit.chunk_id}>
      <summary>{hit.filename} · {hit.section_path.at(-1)?.title ?? `Source unit ${hit.evidence.source.unit}`}</summary>
      <blockquote className="evidence-block">{hit.evidence.text}</blockquote>
      <a href={`/?view=documents&document=${hit.document_id}`}>Open document</a>
    </details>)}
  </section>
}

const titles = { search: "Passage search", documents: "Document details", concepts: "Concept explorer", graph: "Knowledge graph", compare: "Compare documents" }

export function Explore({ page }: { page: Page }) {
  const [cursor, setCursor] = useState("")
  const [library, setLibrary] = useState<Schema["DocumentJob"][]>([])
  const [left, setLeft] = useState(() => new URLSearchParams(window.location.search).get("document") ?? "")
  const [right, setRight] = useState("")
  const documents = useResource<Schema["DocumentList"]>(
    page === "graph" || page === "search" ? "" : `${api}/documents?limit=100${cursor ? `&after=${cursor}` : ""}`,
  )
  const items = [...library, ...(documents.data?.items ?? [])]
  const options = items.map(({ document }) => <option key={document.id} value={document.id}>{document.filename}</option>)
  return <>
    <div className="page-title"><h1>{titles[page]}</h1></div>
    {page === "graph" ? <Graph /> : page === "search" ? <Search /> : <>
      <section className="workspace-panel explore-picker workspace-form">
        <label htmlFor="explore-left">{page === "compare" ? "First document" : "Document"}</label>
        <select id="explore-left" value={left} onChange={event => setLeft(event.target.value)}>
          <option value="">Choose a document</option>{options}
        </select>
        {page === "compare" && <>
          <label htmlFor="explore-right">Second document</label>
          <select id="explore-right" value={right} onChange={event => setRight(event.target.value)}>
            <option value="">Choose another document</option>{options}
          </select>
        </>}
        <RequestState result={documents} />
        {documents.data?.next_cursor && <button onClick={() => {
          setLibrary(items); setCursor(documents.data?.next_cursor ?? "")
        }}>Load more documents</button>}
        {documents.data && items.length === 0 && <p><a href="/">Upload a document to get started</a></p>}
      </section>
      {page === "compare" ? <Comparison key={`${left}:${right}`} left={left} right={right} /> : left &&
        (page === "concepts" ? <Concepts key={left} id={left} /> : <DocumentDetail key={left} id={left} />)}
    </>}
  </>
}
