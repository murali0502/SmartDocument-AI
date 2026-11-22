# Known limitations

- Phase 1 is a system foundation. Document ingestion, OCR application integration, concepts, graph, retrieval, reasoning, and answers are scheduled for later phases.
- User, workspace, and membership records are defined in storage. Sign-in and workspace workflows are scheduled separately.
- The shipped profile is a loopback development setup. Production deployment, authentication and dependency security review are pending.
- Health checks validate live connectivity, expected migration revisions, and required tables. Schema drift is checked separately with Alembic.
- Verification used Linux and Chromium. Other browsers and Windows remain to be checked.
