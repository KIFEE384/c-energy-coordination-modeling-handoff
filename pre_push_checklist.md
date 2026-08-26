# Pre-push Checklist

- [x] Public repository stores only `02_data/raw/source_manifest.csv` and derived summaries; raw attachments remain local.
- [x] Model-semantic acceptance tests pass with numerical-result claims blocked pending solver outputs.
- [x] Tracked-file scan found no private raw attachments, local caches or credential files.
- [ ] Main branch contains the latest module reports.
- [x] `03_models/统一双柔性模型_复审修订版.md`, rationale, algorithm interface, acceptance tests, ledger and decision log exist.
- [x] Current entry points reference the reviewed model; the earlier model is retained only as history.
- [x] 2406 convention and B3_ref/x0 comparison are logged before result tables are pushed.
- [x] Feasible common task baseline `x_base` is generated, hashed and independently replayed.
- [x] Result claims are labelled `EXPECTED` or `BLOCKED` until computations complete.
- [x] Four-cell and Q3 runs require an explicit `ExportPolicy`; `M00_Q1` is separately labelled as a no-export Q1-only baseline.
