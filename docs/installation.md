# Installation

## PyPI

```bash
pip install sql-mcp              # core: SQLite over stdlib-backed SQLAlchemy
pip install "sql-mcp[mcp]"       # + MCP server runtime
pip install "sql-mcp[agent]"     # + Pydantic-AI A2A agent server
```

## Per-dialect extras matrix

Core ships SQLite only so the base install stays thin. Each networked dialect is
one extra:

| Extra | Driver installed | Dialect |
|---|---|---|
| `sql-mcp[postgres]` | `psycopg[binary]>=3.1` | PostgreSQL |
| `sql-mcp[mysql]` | `pymysql>=1.1` | MySQL / MariaDB |
| `sql-mcp[mssql]` | `pyodbc>=5.0` | Microsoft SQL Server * |
| `sql-mcp[oracle]` | `oracledb>=2.0` | Oracle Database |
| `sql-mcp[all]` | everything above | + `mcp` + `agent` extras |

\* `pyodbc` additionally needs the platform's `unixodbc` and a Microsoft ODBC
driver (e.g. `msodbcsql18`) installed at the OS level.

Using a dialect whose driver is missing raises a self-explanatory error naming
the extra to install.

## From source

```bash
git clone https://github.com/Knuckles-Team/sql-mcp.git
cd sql-mcp
pip install -e ".[all,test]"
python -m pytest
```

## Docker

```bash
docker build -t sql-mcp -f docker/Dockerfile .
docker run --rm -e SQL_URL="postgresql+psycopg://svc:****@db:5432/app" \
  -e TRANSPORT=streamable-http -p 8000:8000 sql-mcp
```

`docker/compose.yml` runs the agent; `docker/mcp.compose.yml` runs the MCP
server.
