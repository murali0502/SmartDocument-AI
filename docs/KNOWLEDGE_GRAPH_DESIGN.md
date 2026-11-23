# Phase 6 knowledge graph

## Publication and storage

The local worker projects the latest ready NCM snapshot for each document in the active NLP and scoring configuration. A graph version freezes the selected document, extraction job, NCM snapshot ID and revision for each source. A new upload or review produces a new graph when the set changes. A fingerprint check under the write transaction prevents publishing stale inputs after a concurrent change.

SQLite tables store versions, nodes, document membership, typed edges and ordered evidence. Each endpoint foreign key includes the graph version. Each edge evidence row belongs to an edge in that version. Nodes and edges are published in the same transaction. The last ready graph remains available if a newer projection fails. Historical reads use the explicit version ID.

A graph can include up to 100 ready documents, 35,000 nodes, 75,000 edges and 100,000 evidence rows. The worker records an explicit failed version for larger or inconsistent inputs. Versions are full projections in this local phase, so history grows with revisions. Version retention and production storage sizing remain future work.

## Identity and evidence

Documents, sections and chunks identify provenance. Concepts keep their document-scoped NCM IDs. Typed entities, events, methods, algorithms, attributes, measurements and topics are represented where classifications or anchored labels support them. Definition nodes have an exact source expression.

A document concept can link to a shared definition node when it has one resolved, unqualified definition and a unique normalized label and category within its document. The definition text preserves case and punctuation, with only Unicode NFC and whitespace normalization. This avoids aligning terms whose definitions differ by case-sensitive units. Each concept-to-definition edge retains evidence from its own document. Cross-document navigation can traverse these links in both directions. Homonyms with differing definitions retain separate definition nodes. The shared node is an alignment for exploration. The original concepts and their source assertions remain identifiable.

Every edge contains one or more evidence references to the immutable extraction. Before publication, the worker verifies document and job identity, chunk membership, physical locator, field path, Unicode range and text equality. Assertion and hierarchy endpoints must belong to their own source snapshot. Assertion edges retain the NCM type, polarity, modality, validation, extraction method and timestamp. Provenance edges describe scope and source placement. A graph path lists original edges and an evidence excerpt for each hop.

## Navigation and analytics

SQLite handles browsing and bounded adjacency through endpoint indexes. The version ID in each response lets consumers pin pagination to one version. Supported scopes include document, edge predicate and edge kind.

Path and neighborhood traversal use admitted edges. A source assertion must be source-validated, positive and unqualified or explicitly necessary. Conflicted, rejected, unresolved and conditional assertion records remain available in edge browsing. The default semantic view excludes structural provenance and section-membership links. The dependencies view uses only dependency assertions. The all view can include structural navigation. A path is a route through the graph. Its hops retain their own directions and do not establish an inferred relationship between the endpoints.

Neighborhoods allow up to 100 nodes over three hops. Paths search up to eight hops, 160 incident edges per expansion, 400 expansions and 5,000 admitted edge scans. A truncated path result distinguishes budget exhaustion from an exhausted view. A found route reports any earlier truncation, since the budget may have omitted another route.

NetworkX runs on a bounded in-memory view of up to 2,000 nodes and 6,000 stored edges. It computes connected components, isolated nodes, simple undirected degree centrality, directed strongly connected cycles and optional modularity communities. Parallel assertions collapse to one arc in the analytics projection. The version summary retains actual stored node and edge counts. Orphan detection uses the selected traversal view, excluding provenance-only node kinds. Community membership is a navigation aid.

## Technology choice

SQLite keeps document, evidence and graph publication in one transaction on the existing CPU-first installation. Indexed relational adjacency supports bounded filtered requests without loading the collection into memory. NetworkX provides tested algorithms for the smaller analytical view. A dedicated graph database adds a second persistence system and would need measured scale, latency or distributed-operation gains before adoption.
