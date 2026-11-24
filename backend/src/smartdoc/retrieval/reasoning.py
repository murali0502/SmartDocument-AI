import re
from decimal import Decimal, localcontext
from uuid import UUID

from smartdoc.graph.analysis import shortest_path
from smartdoc.graph.contracts import GraphNode, GraphPath
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.persistence.graph_queries import Filters, GraphQueries
from smartdoc.persistence.graph_store import GraphStore
from smartdoc.retrieval.ranking import tokens

DEPENDENCY_REQUEST = re.compile(
    r"(?:how does|does) (.+?) depend(?: directly or indirectly)? on (.+?)[?.]?",
    re.IGNORECASE,
)
CONVERSION_REQUEST = re.compile(
    r"(?:what is|convert) (.+?) (?:in|to) (mV|kV|V|mA|A|mW|kW|W|mΩ|kΩ|Ω)[?.]?",
    re.IGNORECASE,
)
UNITS = {
    "mV": ("voltage", -3),
    "V": ("voltage", 0),
    "kV": ("voltage", 3),
    "mA": ("current", -3),
    "A": ("current", 0),
    "mW": ("power", -3),
    "W": ("power", 0),
    "kW": ("power", 3),
    "mΩ": ("resistance", -3),
    "Ω": ("resistance", 0),
    "kΩ": ("resistance", 3),
}
QUANTITY = re.compile(
    r"(?<![\w.,-])([+−-]?\d{1,12}(?:\.\d{1,9})?)\s*(mV|kV|V|mA|A|mW|kW|W|mΩ|kΩ|Ω)\b"
)


def convert_stated_quantity(excerpt: str, target: str) -> str | None:
    quantities = QUANTITY.findall(excerpt)
    if len(quantities) != 1 or target not in UNITS:
        return None
    number, unit = quantities[0]
    family, exponent = UNITS[unit]
    target_family, target_exponent = UNITS[target]
    if family != target_family:
        return None
    with localcontext() as context:
        context.prec = 24
        value = Decimal(number.replace("−", "-")).scaleb(exponent - target_exponent)
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{rendered} {target}"


def concept_matches(graph: GraphQueries, label: str, document_id: UUID) -> list[GraphNode]:
    label = " ".join(tokens(label)).removeprefix("the ").removeprefix("a ").removeprefix("an ")
    if not label:
        return []
    return [
        node
        for _, node in graph.nodes(0, 101, document_id, query=label)
        if node.kind not in {"document", "section", "chunk", "definition"}
        and " ".join(tokens(node.label)) == label
    ]


def dependency_path(
    storage: GraphStore, document_id: UUID, source: str, target: str, snapshot_id: str
) -> tuple[GraphPath | None, dict[UUID, GraphNode], bool]:
    try:
        revision = storage.load()
    except ExtractionError as error:
        if error.code in {"graph_failed", "graph_pending"}:
            return None, {}, False
        raise
    if not any(
        item.document_id == document_id and str(item.snapshot_id) == snapshot_id
        for item in revision.sources
    ):
        return None, {}, False
    graph = GraphQueries(storage.engine, revision.id)
    first = concept_matches(graph, source, document_id)
    last = concept_matches(graph, target, document_id)
    if len(first) > 1 or len(last) > 1:
        return None, {}, True
    if not first or not last or first[0].id == last[0].id:
        return None, {}, False
    path = shortest_path(
        graph,
        first[0].id,
        last[0].id,
        "out",
        4,
        Filters(document_id=document_id, view="dependencies", validation="source_validated"),
    )
    if path.status != "found" or not path.steps:
        return None, {}, False
    return path, graph.nodes_by_id(set(path.node_ids), document_id), False
