# Security

Phase 1 serves a local status interface. The default listener binds to loopback, and Vite uses a same-origin proxy. Readiness returns a small set of states and omits file paths, SQL statements and exception text. Access logs include generated request IDs, route patterns, status, and elapsed time. They omit request bodies, query strings and raw paths. SQLite foreign keys enforce the membership references.

The phase introduces storage constraints for membership roles. Session management, route authorization, upload isolation, workspace isolation across business operations, production TLS, and rate limiting are planned. Keep the development listeners local until deployment controls are available and verified.
