# NBA Time Machine frontend

React + TypeScript + Vite. Run `npm install`, `npm run dev`, `npm test` and
`npm run build`; `./dev.py` at the repository root starts both applications.

The viewing guide uses real backend timeline and explicit two-mode `/guide` endpoints.
See [Viewing guide](../docs/VIEWING_GUIDE.md) for Browse / Time Machine and spoiler consent.
Vite proxies `/api` to the local backend. Production needs equivalent same-origin
routing. No provider or database credentials belong here.

See [Frontend integration](../docs/FRONTEND_INTEGRATION.md) for profile initialization,
forward-only cursor behavior, 2025/26 backfill and 2026/27 date selection,
explicit disclosure and historical coverage limits. Fixtures remain test-only.
