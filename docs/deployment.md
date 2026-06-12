# Deployment

<!-- BEGIN GENERATED: deployment-options -->
## Deployment Options

`sql-mcp` exposes its MCP server (console script `sql-mcp`) four ways. Pick the row that
matches where the server runs relative to your MCP client, then copy the matching
`mcp_config.json` below. Add the service-connection environment variables documented in the **Configuration** section.

| # | Option | Transport | Where it runs | `mcp_config.json` key |
|---|--------|-----------|---------------|------------------------|
| 1 | stdio | `stdio` | client launches a subprocess | `command` |
| 2 | Streamable-HTTP (local) | `streamable-http` | a local network port | `command` or `url` |
| 3 | Local container / uv | `stdio` or `streamable-http` | Docker / Podman / uv on this host | `command` or `url` |
| 4 | Remote URL | `streamable-http` | a remote host behind Caddy | `url` |

### 1. stdio (local subprocess)

The client launches the server over stdio via `uvx` — best for local IDEs
(Cursor, Claude Desktop, VS Code):

```json
{
  "mcpServers": {
    "sql-mcp": {
      "command": "uvx",
      "args": ["--from", "sql-mcp", "sql-mcp"]
    }
  }
}
```

### 2. Streamable-HTTP (local process)

Run the server as a long-lived HTTP process:

```bash
uvx --from sql-mcp sql-mcp --transport streamable-http --host 0.0.0.0 --port 8000
curl -s http://localhost:8000/health        # {"status":"OK"}
```

Then either let the client launch it:

```json
{
  "mcpServers": {
    "sql-mcp": {
      "command": "uvx",
      "args": ["--from", "sql-mcp", "sql-mcp", "--transport", "streamable-http", "--port", "8000"],
      "env": {
        "TRANSPORT": "streamable-http",
        "HOST": "0.0.0.0",
        "PORT": "8000"
      }
    }
  }
}
```

…or connect to the already-running process by URL:

```json
{
  "mcpServers": {
    "sql-mcp": { "url": "http://localhost:8000/mcp" }
  }
}
```

### 3. Local container / uv

**(a) Launch a container directly from `mcp_config.json`** (stdio over the container —
no ports to manage). Swap `docker` for `podman` for a daemonless runtime:

```json
{
  "mcpServers": {
    "sql-mcp": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "TRANSPORT=stdio",
        "knucklessg1/sql-mcp:latest"
      ]
    }
  }
}
```

**(b) Run a local streamable-http container, then connect by URL:**

```bash
docker run -d --name sql-mcp -p 8000:8000 \
  -e TRANSPORT=streamable-http \
  -e PORT=8000 \
  knucklessg1/sql-mcp:latest
# or, from a clone of this repo:
docker compose -f docker/mcp.compose.yml up -d
```

```json
{
  "mcpServers": {
    "sql-mcp": { "url": "http://localhost:8000/mcp" }
  }
}
```

**(c) From a local checkout with `uv`:**

```bash
uv run sql-mcp --transport streamable-http --port 8000
```

### 4. Remote URL (deployed behind Caddy)

When the server is deployed remotely (e.g. as a Docker service) and published through
Caddy on the internal `*.arpa` zone, connect with the `"url"` key — no local process or
image required:

```json
{
  "mcpServers": {
    "sql-mcp": { "url": "http://sql-mcp.arpa/mcp" }
  }
}
```

Caddy reverse-proxies `http://sql-mcp.arpa` to the container's `:8000`
streamable-http listener; `http://sql-mcp.arpa/health` returns
`{"status":"OK"}` when the service is live.
<!-- END GENERATED: deployment-options -->

This page covers running `sql-mcp` as long-lived servers.

> `sql-mcp` ships both an **MCP server** (console script `sql-mcp`) and an
> **A2A agent server** (console script `sql-agent`).

## Run the MCP server

=== "stdio (default)"

    ```bash
    sql-mcp
    ```

=== "streamable-http"

    ```bash
    sql-mcp --transport streamable-http --host 0.0.0.0 --port 8000
    ```

=== "sse"

    ```bash
    sql-mcp --transport sse --host 0.0.0.0 --port 8000
    ```

Health check (HTTP transports):

```bash
curl -s http://localhost:8000/health        # {"status":"OK"}
```

## Docker Compose

```bash
docker compose -f docker/mcp.compose.yml up -d      # MCP server only
docker compose -f docker/agent.compose.yml up -d    # MCP + agent
```

Connections, policy, and toggles come from `../.env` (see
[`.env.example`](https://github.com/Knuckles-Team/sql-mcp/blob/main/.env.example)).

## Run the A2A agent server

```bash
sql-agent --mcp-config mcp_config.json --web
```

## Ingress & DNS

Behind the fleet's Caddy reverse proxy, publish the streamable-http MCP
endpoint and register the hostname in Technitium DNS; point clients at
`https://sql-mcp.<zone>/mcp`.
