# README screenshot guide

The README uses two screenshots captured from the deterministic Docker Compose demo:

- [`taskpilot-hero.png`](assets/taskpilot-hero.png) shows a completed delivery graph with validation
  evidence, elapsed time, model-call count, and token usage.
- [`taskpilot-approval.png`](assets/taskpilot-approval.png) shows the persisted approval gate with
  proposed files, validation commands, risks, and parallel-analysis results.

To refresh them:

1. Run `docker compose up --build` and open `http://localhost:5173` at a 1440×900 viewport.
2. Start the prefilled product-pagination task against `/opt/taskpilot/examples/sample-api`.
3. Capture the graph while the Approval node is waiting, including the plan, file, command, and risk
   evidence and save it as `taskpilot-approval.png`.
4. Approve the run and capture the completed graph with **Validate** selected so the subprocess
   result, duration, and model/token metadata remain visible.
5. Save optimized output under `docs/assets/`. Update the README image only after checking that text
   remains legible in GitHub's rendered width.

Do not capture API keys, absolute personal paths, raw source proposals, or PostgreSQL credentials.
