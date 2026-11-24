import { api } from "../../api"
import type { components } from "../../generated/api"
import { RequestState, useResource } from "../../resources"

type Schema = components["schemas"]
const labels: Record<string, string> = {
  bm25: "Keyword baseline", structure: "Document structure", concept: "Concepts",
  graph: "Knowledge graph", dense: "Dense search", fusion: "Combined ranking",
  reranked: "Reranked search", full: "Full model-free search",
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="workspace-panel metric"><dt>{label}</dt><dd>{value}</dd></div>
}

function Analytics() {
  const status = useResource<Schema["GraphStatus"]>(`${api}/graph`)
  const version = status.data?.available_version
  const graph = useResource<Schema["Analytics"]>(version ? `${api}/graph/analytics?version_id=${version}` : "")
  const revision = useResource<Schema["GraphRevision"]>(version ? `${api}/graph/versions/${version}` : "")
  const gaps = useResource<Schema["GraphPage_GraphNode_"]>(version ? `${api}/graph/orphans?version_id=${version}&limit=10` : "")
  const data = graph.data
  return <>
    <RequestState result={status} /><RequestState result={graph} />
    {status.data && !version && <section className="workspace-panel">
      <h2>Graph unavailable</h2><p>Upload a document and let concept processing finish.</p>
      <a href="/">Upload a document</a> <button onClick={status.refresh}>Refresh</button>
    </section>}
    {data && <>
      <dl className="metric-grid">
        <Metric label="Indexed documents" value={revision.data?.document_count ?? "…"} />
        <Metric label="Graph nodes" value={data.node_count} />
        <Metric label="Relationships" value={data.edge_count} />
        <Metric label="Connected groups" value={data.component_count} />
      </dl>
      <section className="workspace-panel">
        <h2>Graph coverage</h2>
        <p>{data.isolated_count} isolated nodes and {data.cycles.length} reported cycles.</p>
        {data.groups_truncated && <p>Cycle results reached the display limit.</p>}
        <a href="/?view=graph">Explore relationships</a>
      </section>
      <section className="workspace-panel insight-section">
        <h2>Concepts without graph connections</h2>
        <RequestState result={gaps} />
        {gaps.data && <p className="muted">Review these concepts for supporting relationships in your sources.</p>}
        {gaps.data?.items.length === 0 && <p>No isolated concepts were reported.</p>}
        <ul>{gaps.data?.items.map(node => <li key={node.id}>{node.label}</li>)}</ul>
        {gaps.data?.next_cursor != null && <p className="muted">Showing the first ten results.</p>}
      </section>
    </>}
  </>
}

function Evaluation() {
  const result = useResource<Schema["EvaluationReport"]>(`${api}/evaluation`)
  return <>
    <RequestState result={result} />
    {result.data && <>
      <dl className="metric-grid">
        <Metric label="Benchmark documents" value={result.data.documents} />
        <Metric label="Labeled queries" value={result.data.queries} />
        <Metric label="Peak memory" value={`${result.data.peak_rss_mib_linux} MiB`} />
      </dl>
      <section className="workspace-panel">
        <h2>Retrieval benchmark</h2>
        <p className="muted">Frozen synthetic Linux benchmark. These results measure retrieval on the labeled fixture.</p>
        <div className="table-scroll"><table>
          <thead><tr><th scope="col">Method</th><th scope="col">Recall@5</th><th scope="col">MRR@5</th><th scope="col">Median</th><th scope="col">p95</th></tr></thead>
          <tbody>{Object.entries(result.data.variants).map(([key, values]) => <tr key={key}>
            <th scope="row">{labels[key] ?? key.replaceAll("_", " ")}</th>
            <td>{(values.recall_at_5 * 100).toFixed(1)}%</td><td>{values.mrr_at_5.toFixed(3)}</td>
            <td>{values.p50_ms.toFixed(1)} ms</td><td>{values.p95_ms.toFixed(1)} ms</td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}
  </>
}

export function Insights({ page }: { page: "analytics" | "evaluation" }) {
  return <>
    <div className="page-title"><h1>{page === "analytics" ? "Analytics" : "Evaluation"}</h1></div>
    {page === "analytics" ? <Analytics /> : <Evaluation />}
  </>
}
