# Build from the repo root, not this folder, since this server also
# needs xbrl_pipeline/, a sibling folder it imports directly:
#   docker build -f services/mcp_server/Dockerfile -t mcp-server .
#   docker run -p 8000:8000 mcp-server
FROM python:3.11-slim

WORKDIR /app
COPY services/mcp_server/requirements.txt services/mcp_server/requirements.txt
RUN pip install --no-cache-dir -r services/mcp_server/requirements.txt

COPY xbrl_pipeline/ xbrl_pipeline/
COPY services/mcp_server/ services/mcp_server/

WORKDIR /app/services/mcp_server
ENV PORT=8000
CMD ["python", "server.py"]
