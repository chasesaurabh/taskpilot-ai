# Demo capture guide

The repository includes two reproducible portfolio screenshots:

- [`taskpilot-hero.png`](assets/taskpilot-hero.png) shows a completed delivery graph with validation
  evidence, elapsed time, model-call count, and token usage.
- [`taskpilot-approval.png`](assets/taskpilot-approval.png) shows the persisted approval gate with
  proposed files, validation commands, risks, and parallel-analysis results.

Both were captured from the Docker Compose stack at a 1440×900 viewport using the deterministic
pagination scenario. To recapture them or produce an animated GIF:

1. Run `docker compose up --build` and open `http://localhost:5173` at a 1440×900 viewport.
2. Start the prefilled product-pagination task against `/opt/taskpilot/examples/sample-api`.
3. Capture the graph while the Approval node is waiting, including the plan, file, command, and risk
   evidence. Use this frame for `taskpilot-approval.png` or as the GIF pause point.
4. Approve the run and capture the completed graph with **Validate** selected so the subprocess
   result, duration, and model/token metadata remain visible.
5. For a GIF, record from run creation through completion, hold the approval state for 2–3 seconds,
   then optimize the result to a width near 1200 px. Keep the committed GIF below 10 MB.
6. Save optimized output under `docs/assets/`. Update the README image only after checking that text
   remains legible in GitHub's rendered width.

Do not capture API keys, absolute personal paths, raw source proposals, or PostgreSQL credentials.
