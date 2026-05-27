FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist


FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl[http] && rm /tmp/*.whl

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    SERVICENOW_MAX_RETRIES=3 \
    SERVICENOW_REQUEST_TIMEOUT_S=30

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/mcp')" || exit 1

ENTRYPOINT ["servicenow-mcp"]
CMD ["--transport", "streamable-http"]
