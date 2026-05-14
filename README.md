# Lab: Build a Database MCP Server with FastMCP and SQLite

**Tên** Bùi Trần Gia Bảo  
**Mã HV:** 2A202600009

This project implements a FastMCP server backed by a relational database.  
The server exposes exactly three MCP tools:

- `search`
- `insert`
- `aggregate`

It also exposes these MCP resources:

- `schema://database`
- `schema://table/{table_name}`

The default backend is SQLite, but the same MCP surface also supports PostgreSQL through a shared adapter interface.

---

# Features

## MCP Tools

### `search`

Search validated database tables with:

- filters
- ordering
- pagination
- selected columns

Supported operators:

```text
eq, ne, gt, gte, lt, lte, like, in, is_null, not_null
```

---

### `insert`

Insert validated rows safely using parameterized SQL.

---

### `aggregate`

Supports:

- `count`
- `avg`
- `sum`
- `min`
- `max`

Optional grouping is supported.

---

# MCP Resources

## Full database schema

```text
schema://database
```

## Per-table schema template

```text
schema://table/{table_name}
```

---

# Safety Features

The server rejects:

- unknown tables
- unknown columns
- unsupported operators
- invalid aggregate requests
- empty inserts

Additional protections:

- parameterized SQL values
- validated identifiers
- pagination limits
- structured validation errors

---

# Bonus Features

## PostgreSQL Support

The same MCP interface supports:

- SQLite
- PostgreSQL

through a shared adapter abstraction.

---

## HTTP Authentication

The HTTP transport supports bearer-token authentication using FastMCP `StaticTokenVerifier`.

---

## Pagination Metadata

Search responses include:

- `has_more`
- `next_offset`

---

## Automated Verification

Included:

- repeatable verification script
- automated tests
- Inspector workflow

---

---

# Requirements

Install:

- Python 3.11+
- Node.js/npm
- Git Bash or terminal
- PostgreSQL

---

# Setup

## 1. Create virtual environment

From the repo root:

### Git Bash / macOS / Linux

```bash
python -m venv venv
source venv/Scripts/activate
```

### Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

---

## 2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

# SQLite Setup

Initialize SQLite database:

```bash
python implementation/init_db.py --backend sqlite
```

Expected output:

```text
SQLite database initialized at: .../implementation/lab26.sqlite3
```

---

# PostgreSQL Setup (Bonus)

## 1. Install PostgreSQL

Install:

https://www.postgresql.org/download/

During installation:

- keep port `5432`
- remember your password for user `postgres`

---

## 2. Create database

Open PostgreSQL terminal:

```bash
psql -U postgres
```

Create database:

```sql
CREATE DATABASE lab26;
```

---

## 3. Create `.env`

Create `.env` in the repo root:

```env
DB_BACKEND=postgres
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/lab26
LAB26_AUTH_TOKEN=dev-lab26-token
```

Replace:

- `YOUR_PASSWORD`

with your actual PostgreSQL password.

---

## 4. Initialize PostgreSQL database

```bash
python implementation/init_db.py --backend postgres
```

Expected output:

```text
PostgreSQL database initialized from DATABASE_URL: ...
```

---

# Verification

Run the repeatable verification script:

```bash
python implementation/verify_server.py
```

Expected output includes:

```text
Tools discovered: ['aggregate', 'insert', 'search']
Resources discovered: ['schema://database']
Resource templates discovered: ['schema://table/{table_name}']
```

The script intentionally performs an invalid request using:

```text
table = "missing_table"
```

to verify safe validation and error handling.

Expected validation output:

```text
Expected invalid request error:
Error calling tool 'search': Validation error: Unknown table 'missing_table'
```

Successful completion ends with:

```text
All Lab 26 MCP checks passed.
```

---

# Automated Tests

Run:

```bash
python -m pytest
```

---

# Run MCP Server

From repo root:

```bash
python implementation/mcp_server.py
```

Expected output:

```text
Starting MCP server 'SQLite Lab MCP Server' with transport 'stdio'
```

---

# MCP Inspector

## 1. Install Node.js

Download:

https://nodejs.org/

Verify:

```bash
node -v
npm -v
```

---

## 2. Run Inspector

From repo root:

```bash
cd implementation
./start_inspector.sh
```

Open the printed URL.

---

# Example Inspector Calls

## Search A1 students

Tool: `search`

Fill the fields like this:

### table

```text
students
```

### filters

```json
{
  "cohort": "A1"
}
```

### columns

```json
["id", "name", "cohort", "score"]
```

### order_by

```text
score
```

### descending

```text
true
```

### limit

```text
5
```

Then click **Run Tool**.

---

## Insert student

Tool: `insert`

Fill the fields like this:

### table

```text
students
```

### values

```json
{
  "name": "Dorothy Vaughan",
  "email": "dorothy@example.edu",
  "cohort": "A1",
  "score": 89.0
}
```

Then click **Run Tool**.

---

## Aggregate average score

Tool: `aggregate`

Fill the fields like this:

### table

```text
students
```

### metric

```text
avg
```

### column

Uncheck `null`, then enter:

```text
score
```

### group_by

```text
cohort
```

### filters

Leave blank or use:

```json
{}
```

Then click **Run Tool**.

---

## Invalid validation example

Tool: `search`

Fill the fields like this:

### table

```text
missing_table
```

Leave the other fields empty.

Then click **Run Tool**.

This should fail with a validation error. That failure is expected and demonstrates safe error handling.

---

# Gemini CLI MCP Client Setup

## 1. Install Gemini CLI

```bash
npm install -g @google/gemini-cli
```

Verify:

```bash
gemini --version
```

---

## 2. Login

```bash
gemini auth login
```

If unavailable:

```bash
gemini login
```

Complete browser authentication.

---

## 3. Add MCP server

From repo root:

```bash
gemini mcp add sqlite-lab "E:/ABSOLUTE/PATH/TO/venv/Scripts/python.exe" "E:/ABSOLUTE/PATH/TO/implementation/mcp_server.py" --description "SQLite lab FastMCP server" --timeout 10000
```

Example:

```bash
gemini mcp add sqlite-lab "E:/Desktop/Day26-Track3-MCP-tool-integration/venv/Scripts/python.exe" "E:/Desktop/Day26-Track3-MCP-tool-integration/implementation/mcp_server.py" --description "SQLite lab FastMCP server" --timeout 10000
```

---

## 4. Open Gemini CLI

```bash
gemini
```

If prompted about IDE integration:

```text
Select: No
```

---

## 5. Test MCP server

Inside Gemini CLI:

```text
Use the sqlite-lab MCP server. Read schema://database and show the top 2 students by score.
```

Successful output confirms:

- MCP client integration
- tool discovery
- resource access
- live MCP functionality

---

# HTTP Transport with Authentication (Bonus)

## Run HTTP server

### Git Bash / macOS / Linux

```bash
python implementation/mcp_server.py --transport http --host 127.0.0.1 --port 8000
```

### Windows PowerShell

```powershell
python implementation/mcp_server.py --transport http --host 127.0.0.1 --port 8000
```

---

## Health check

```bash
curl http://127.0.0.1:8000/health
```

---

## MCP endpoint

```text
http://127.0.0.1:8000/mcp
```

Clients must send:

```text
Authorization: Bearer dev-lab26-token
```
