# Backing Platform — SQL Databases

`sql-mcp` is a **client** of one or more relational databases. This page
provides Docker recipes for deploying local instances to serve as targets of
`SQL_CONNECTIONS` / `SQL_URL`.

!!! note "Backing-system recipe"
    Each connector in the ecosystem follows the same convention — a
    `docs/platform.md` recipe for the system it integrates with, accompanied by a
    sample Compose stack. Systems offered only as a managed service have no local
    recipe.

## Single-node deployment (Compose)

```yaml
# platform.compose.yml — pick the engines you need
services:
  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_USER: svc
      POSTGRES_PASSWORD: change-me
      POSTGRES_DB: app
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data

  mariadb:
    image: mariadb:11
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: change-me
      MARIADB_DATABASE: app
    ports:
      - "3306:3306"
    volumes:
      - mariadb-data:/var/lib/mysql

  mssql:
    image: mcr.microsoft.com/mssql/server:2022-latest
    restart: unless-stopped
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "Change-Me-123"
    ports:
      - "1433:1433"

volumes:
  postgres-data:
  mariadb-data:
```

Matching connection strings:

```bash
SQL_CONNECTIONS={"pg": "postgresql+psycopg://svc:change-me@localhost:5432/app", "maria": "mysql+pymysql://root:change-me@localhost:3306/app", "mssql": "mssql+pyodbc://sa:Change-Me-123@localhost:1433/master?driver=ODBC+Driver+18+for+SQL+Server"}
```

SQLite needs no platform at all — `sqlite:///app.db` (or `sqlite://` in
memory) works out of the box.
