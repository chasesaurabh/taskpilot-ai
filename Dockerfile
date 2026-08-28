FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/taskpilot/.venv/bin:$PATH

RUN apt-get update && \
    apt-get install --yes --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system taskpilot && \
    useradd --system --gid taskpilot --create-home taskpilot
WORKDIR /opt/taskpilot

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
COPY config.example.yaml ./config.example.yaml
RUN python -m venv .venv && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[postgres]" pytest && \
    mkdir -p .taskpilot && chown -R taskpilot:taskpilot /opt/taskpilot

USER taskpilot
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["taskpilot-api"]
