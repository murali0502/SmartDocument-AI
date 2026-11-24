import re
from datetime import date
from decimal import Decimal, localcontext
from uuid import UUID

from smartdoc.graph.analysis import shortest_path
from smartdoc.graph.contracts import GraphNode, GraphPath
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ncm.contracts import Snapshot
from smartdoc.persistence.graph_queries import Filters, GraphQueries
from smartdoc.persistence.graph_store import GraphStore
from smartdoc.retrieval.ranking import tokens

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
    if re.search(r"\d\s*(?:[–—-]|\bto\b)\s*[+−-]?\d", excerpt):
        return None
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


def concept_matches(snapshot: Snapshot, label: str) -> set[UUID]:
    label = " ".join(tokens(label)).removeprefix("the ").removeprefix("a ").removeprefix("an ")
    matches = {
        concept.id
        for concept in snapshot.concepts
        if any(
            " ".join(tokens(name)) == label
            for name in [
                concept.label,
                *(alias.surface for alias in concept.aliases),
            ]
        )
    }
    for ambiguous in snapshot.ambiguous_aliases:
        if " ".join(tokens(ambiguous.surface)) == label:
            matches.update(ambiguous.alternatives)
    return matches


def relationship_path(
    storage: GraphStore,
    snapshot: Snapshot,
    source: str,
    target: str,
    snapshot_id: str,
    *,
    dependencies: bool,
) -> tuple[GraphPath | None, dict[UUID, GraphNode], bool]:
    document_id = snapshot.document_id
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
    first = concept_matches(snapshot, source)
    last = concept_matches(snapshot, target)
    if len(first) > 1 or len(last) > 1:
        return None, {}, True
    if not first or not last or first == last:
        return None, {}, False
    path = shortest_path(
        graph,
        next(iter(first)),
        next(iter(last)),
        "out" if dependencies else "both",
        4,
        Filters(
            document_id=document_id,
            kind="assertion",
            view="dependencies" if dependencies else "semantic",
            validation="source_validated",
        ),
    )
    if path.status != "found" or not path.steps:
        return None, {}, False
    return path, graph.nodes_by_id(set(path.node_ids), document_id), False


def stated_date_interval(excerpt: str) -> tuple[date, date] | None:
    matches = re.findall(r"\b([0-9]{4})(-[0-9]{2}-[0-9]{2})?\b", excerpt)
    if len(matches) != 1:
        return None
    year, precision = matches[0]
    try:
        if precision:
            day = date.fromisoformat(year + precision)
            return day, day
        if re.search(r"\b(?:on|in)\s+" + year + r"\b(?![-/])", excerpt, re.IGNORECASE):
            return date(int(year), 1, 1), date(int(year), 12, 31)
    except ValueError:
        pass
    return None
