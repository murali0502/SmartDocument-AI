# Security

Phase 2 provides a local status interface and ingestion API. The default listener binds to loopback, and Vite uses a same-origin proxy. Readiness responses omit file paths, SQL statements and exception text. Access logs include generated request IDs, route patterns, status and elapsed time. They omit request bodies, raw paths and query strings.

Ingestion checks the loopback peer and host. Browser origins must match, uploads require an explicit header, and the launcher ignores forwarded client addresses. Raw uploads stream to a bounded staging file. User filenames never form storage paths. Before parsing Office archives, the worker checks entry count, expansion size, package shape, unsafe entries, macros and XML declarations. Spreadsheet formulas and document links are read as data.

A separate parser subprocess has a timeout, bounded output and an allowlisted environment. Linux also enforces process resource limits. Where Bubblewrap is available, the worker launches the parser in isolated namespaces with no network and a limited filesystem view. The fallback process blocks Python networking and shell invocation through an audit hook, with a narrow exception for Tesseract. Native-code isolation in the fallback and Windows containment remain unverified for production use.

Membership roles have database constraints. User sign-in, tenant authorization, production TLS and rate limiting remain planned. Keep the development listeners local until deployment controls are available and verified.
