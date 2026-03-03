# Customer Retention System — Unified Monorepo

A unified monorepo combining the **Customer Retention Web Application** (FastAPI) and the **Customer Retention Trigger Agent** (Azure Durable Functions) into a single, cohesive project.

## Overview

The Customer Retention System helps retail banking teams identify customers at risk of leaving by:

1. Evaluating customer service notes against a configurable rule set to produce scored **lead cards**.
2. Running batch **n-gram discovery** to surface new churn-signal phrases from historical notes, which SMEs can approve and promote to the live rules library.

---

## Project Structure

```
customer-retention-agl/
├── shared/                     # Shared Python package (used by all components)
│   ├── __init__.py
│   ├── rules.py                # Rule loader (SQL or local YAML) and event scorer
│   ├── sql_client.py           # Azure SQL client
│   ├── azure_openai_predict.py # Azure OpenAI integration
│   ├── aoai_text_matcher.py    # Text rule matcher
│   ├── guardrails.py           # Confidence-floor and evidence guards
│   ├── logging_utils.py        # Metrics / Application Insights client
│   └── pii.py                  # PII scrubber
├── webapp/                     # FastAPI web application
│   ├── app/
│   │   ├── main.py             # API routes and app factory
│   │   └── db.py               # Trigger database helpers
│   └── static/                 # Built frontend assets
├── functions/                  # Azure Durable Functions trigger agent
│   └── function_app.py         # Orchestrator, activities, and HTTP starters
├── batch/                      # Workflow-2 discovery pipeline
│   └── discovery_workflow.py
├── sql/
│   ├── sample_rules.yaml       # Default rule set (used when USE_SQL_RULES=0)
│   └── tables.sql              # Azure SQL DDL
├── tests/                      # Shared test suite
├── Dockerfile                  # Webapp container image
├── requirements.txt
└── .env.example
```

---

## Architecture

```
Browser / API client
       │
       ▼
  FastAPI webapp  ──── POST /api/evaluate ────▶  Azure Durable Functions
  (webapp/)                                       (functions/)
       │                                               │
       │                                     ┌─────────┴──────────┐
       │                                     │  Orchestrator       │
       │                              ┌──────┴───────┐            │
       │                              │ text_agent   │   rule_     │
       │                              │ (AOAI)       │   scorer   │
       │                              └──────────────┘            │
       │                                               │
       │                              Lead card → Azure SQL
       │
       ├── GET /api/predict ──▶ Azure OpenAI (direct, for discovery UI)
       ├── GET/POST/DELETE /api/triggers ──▶ Azure SQL triggers table
       └── GET / ──▶ Static frontend (webapp/static/)

shared/  ◀── imported by both webapp/ and functions/ and batch/
```

---

## Workflows

### Workflow 1 — Operational: Evaluate Customer Notes

1. The webapp receives a customer note via `POST /api/evaluate`.
2. It calls the Azure Durable Functions HTTP starter (`http_start_single_analysis`).
3. The **orchestrator** fans out to:
   - `text_agent_activity` — calls Azure OpenAI to extract churn-signal triggers from the note.
   - `rule_scorer_activity` — scores structured features against the active rule set.
4. Scores above `LEAD_SCORE_THRESHOLD` create a **lead card** written to Azure SQL.
5. The webapp polls `GET /api/evaluate/status/{instance_id}` for progress.

### Workflow 2 — Discovery: Batch N-Gram Mining

1. `batch/discovery_workflow.py` reads historical customer notes from Azure SQL.
2. It mines n-grams, computes statistical significance (lift, odds-ratio, FDR), and writes **discovery cards** to the database.
3. SMEs review discovery cards in the webapp (`GET /api/predict`, `/api/triggers/approve`).
4. Approved triggers are inserted into the **rules library** and can be promoted to `ACTIVE` status for Workflow 1.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness check — returns `{"status": "ok"}` |
| `POST` | `/api/evaluate` | Start evaluation of a customer note (triggers Durable Function) |
| `GET` | `/api/evaluate/status/{instance_id}` | Poll status of a running evaluation |
| `POST` | `/api/predict` | Generate churn-trigger predictions via Azure OpenAI |
| `GET` | `/api/triggers` | List approved triggers (`?limit=25`) |
| `POST` | `/api/triggers/approve` | Approve a discovered trigger (inserts into DB) |
| `DELETE` | `/api/triggers/{trigger_id}` | Delete a trigger by ID |
| `GET` | `/` | Serve the static frontend |

---

## Local Development

### Prerequisites

- Python 3.11+
- ODBC Driver 18 for SQL Server (for database features)
- Azure Functions Core Tools v4 (for functions)

### Webapp

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and populate environment variables
cp .env.example .env
# Edit .env with your values

# Run the development server
uvicorn webapp.app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. The interactive docs are at `http://localhost:8000/docs`.

### Azure Functions (local)

```bash
cd functions
func start
```

The Functions runtime will start on `http://localhost:7071`. Set `FUNCTION_BASE_URL=http://localhost:7071` in `.env` when running the webapp locally alongside functions.

### Running Tests

```bash
pytest
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZSQL_SERVER` | Yes | — | Azure SQL server hostname |
| `AZSQL_DB` | Yes | — | Azure SQL database name |
| `AZSQL_UID` | Yes | — | Azure SQL username |
| `AZSQL_PWD` | Yes | — | Azure SQL password |
| `AZSQL_DRIVER` | No | `{ODBC Driver 18 for SQL Server}` | ODBC driver string |
| `AZURE_OPENAI_ENDPOINT` | Yes* | — | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | Yes* | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Yes* | — | Azure OpenAI deployment/model name |
| `USE_SQL_RULES` | No | `0` | Set to `1` to load the active rule set from SQL instead of `sql/sample_rules.yaml` |
| `LEAD_SCORE_THRESHOLD` | No | `0.7` | Minimum score to generate a lead card |
| `CONFIDENCE_FLOOR` | No | `0.60` | Minimum AOAI hit confidence |
| `EVIDENCE_MIN_LEN` | No | `4` | Minimum evidence string length |
| `FUNCTION_START_URL` | No | — | Full URL of the Functions HTTP starter (overrides `FUNCTION_BASE_URL` + `FUNCTION_CODE`) |
| `FUNCTION_BASE_URL` | No | `http://localhost:7071` | Base URL of the Functions host |
| `FUNCTION_CODE` | No* | — | Azure Functions host key (required when `FUNCTION_START_URL` is not set in production) |
| `AzureWebJobsStorage` | Yes† | — | Azure Storage connection string (required by Durable Functions) |
| `APPINSIGHTS_INSTRUMENTATIONKEY` | No | — | Application Insights key for telemetry |
| `REPLAY_QUEUE_NAME` | No | `event-replay` | Azure Storage Queue for event replay |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

\* Required for Azure OpenAI features; the app falls back to deterministic sample data if not configured.  
† Required when running Azure Functions.

---

## Docker

### Build

```bash
docker build -t customer-retention-webapp .
```

### Run

```bash
docker run -p 8000:8000 \
  -e AZSQL_SERVER=myserver.database.windows.net \
  -e AZSQL_DB=retentiondb \
  -e AZSQL_UID=svc-retention \
  -e AZSQL_PWD=<secret> \
  -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com \
  -e AZURE_OPENAI_API_KEY=<key> \
  -e AZURE_OPENAI_DEPLOYMENT=<deployment> \
  customer-retention-webapp
```

### Azure Container Registry

```bash
# Tag and push
az acr login --name <your-registry>
docker tag customer-retention-webapp <your-registry>.azurecr.io/customer-retention-webapp:latest
docker push <your-registry>.azurecr.io/customer-retention-webapp:latest
```

---

## Deployment

### Webapp — Azure Container Apps

```bash
az containerapp create \
  --name customer-retention-webapp \
  --resource-group <rg> \
  --environment <env> \
  --image <your-registry>.azurecr.io/customer-retention-webapp:latest \
  --target-port 8000 \
  --ingress external \
  --env-vars AZSQL_SERVER=... AZSQL_DB=... ...
```

### Azure Functions

Deploy the `functions/` directory using the Azure Functions Core Tools or CI/CD:

```bash
cd functions
func azure functionapp publish <your-function-app-name>
```

Set all required environment variables (see table above) in the Function App's Application Settings.
