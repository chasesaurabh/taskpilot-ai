# Demo capture guide

The repository does not commit a binary screenshot or animated GIF. To capture reproducible portfolio media:

1. Run `docker compose up --build` and open `http://localhost:5173` at a 1440×900 viewport.
2. Start the prefilled product-pagination task against `/opt/taskpilot/examples/sample-api`.
3. Capture the graph while the Approval node is waiting, including the plan and risk panel.
4. Approve the run and capture the completed graph with the Testing node selected so the tool call, duration, and model/token metadata are visible.
5. Save optimized output under `docs/assets/` and add its Markdown image immediately below the README title.

Do not capture API keys, absolute personal paths, raw source proposals, or PostgreSQL credentials.
