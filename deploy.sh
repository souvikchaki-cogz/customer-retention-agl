#!/bin/bash
# =============================================================================
# deploy.sh — Deployment for fa-customer-retention-agl aligned with imb-customer-retention, now with User Assigned Managed Identity (UAMI)
# Uses SQL username/password authentication alongside Managed Identity and specifies ODBC Driver.
# =============================================================================

set -euo pipefail

# Robust .env loader: supports values containing '=' and strips surrounding quotes
if [ -f ".env" ]; then
  while IFS='=' read -r key value; do
    case "$key" in ''|[#]*) continue ;; esac
    raw_value=$(grep -m1 "^${key}=" .env | cut -d'=' -f2-)
    # Strip surrounding quotes
    raw_value="${raw_value%\"}"
    raw_value="${raw_value#\"}"
    export "${key}=${raw_value}"
  done < .env
else
  echo "❌ .env file not found. Please create one."
  exit 1
fi

# -- Keep TIMESTAMP and IMAGE_TAG logic --
TIMESTAMP=$(date +%Y%m%d%H%M%S)
IMAGE_TAG="${ACR_NAME}.azurecr.io/${CONTAINER_APP_NAME}:${TIMESTAMP}"

# -- Keep UAMI_ID as derived --
UAMI_ID="/subscriptions/${UAMI_SUBSCRIPTION_ID}/resourceGroups/${UAMI_RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${UAMI_NAME}"

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

log()  { echo ""; echo "──────────────────────────────────────────────"; echo "  ▶  $1"; echo "──────────────────────────────────────────────"; }
ok()   { echo "  ✅ $1"; }
info() { echo "  ℹ️  $1"; }
warn() { echo "  ⚠️  $1"; }

# ──────────────────────────────────────────────────────────────────
# Destroy Created Resources
# ──────────────────────────────────────────────────────────────────

destroy_created_resources() {
    log "Destroying previously created resources if they exist (safe cleanup)..."

    az functionapp delete --name "$FUNC_APP_NAME" --resource-group "$RESOURCE_GROUP" || true
    az containerapp delete --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --yes || true
    az storage account delete --name "$STORAGE_NAME" --resource-group "$RESOURCE_GROUP" --yes || true
    az acr delete --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --yes || true
    az monitor app-insights component delete --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" || true
    az monitor log-analytics workspace delete --workspace-name "$LOG_ANALYTICS_WORKSPACE" --resource-group "$RESOURCE_GROUP" --yes || true

    ok "Specific resources cleaned up."
}

# ──────────────────────────────────────────────────────────────────
# Prerequisites
# ──────────────────────────────────────────────────────────────────

check_prerequisites() {
    log "Prerequisites"

    if ! command -v az &>/dev/null; then
        echo "  ❌ 'az' not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    fi
    ok "az CLI: $(az version --query '"azure-cli"' -o tsv)"

    if ! command -v func &>/dev/null; then
        echo "  ❌ 'func' not found. Install: npm install -g azure-functions-core-tools@4"
        exit 1
    fi
    ok "func CLI: $(func --version 2>/dev/null | head -1)"

    if ! az account show &>/dev/null; then
        echo "  ❌ Not logged in. Run: az login"
        exit 1
    fi
    ok "Azure account: $(az account show --query 'name' -o tsv)"

    if [ ! -f "Dockerfile" ]; then
        echo "  ❌ Dockerfile not found. Run from the repository root."
        exit 1
    fi
    ok "Dockerfile found."

    if [ ! -f "function_app.py" ]; then
        echo "  ❌ function_app.py not found. Run from the repository root."
        exit 1
    fi
    ok "function_app.py found."
}

# ──────────────────────────────────────────────────────────────────
# Log Analytics Workspace
# ──────────────────────────────────────────────────────────────────

deploy_log_analytics() {
    log "Log Analytics Workspace"
    az monitor log-analytics workspace create \
        --resource-group "$RESOURCE_GROUP" \
        --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
        --location "$LOCATION" \
        --output none

    export LAW_ID=$(az monitor log-analytics workspace show \
        --resource-group "$RESOURCE_GROUP" \
        --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
        --query customerId -o tsv)

    export LAW_KEY=$(az monitor log-analytics workspace get-shared-keys \
        --resource-group "$RESOURCE_GROUP" \
        --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
        --query primarySharedKey -o tsv)

    ok "Log Analytics '$LOG_ANALYTICS_WORKSPACE' ready."
}

# ──────────────────────────────────────────────────────────────────
# Application Insights
# ──────────────────────────────────────────────────────────────────

deploy_app_insights() {
    log "Application Insights"
    az monitor app-insights component create \
        --app "$APP_INSIGHTS_NAME" \
        --location "$LOCATION" \
        --resource-group "$RESOURCE_GROUP" \
        --workspace "$LOG_ANALYTICS_WORKSPACE" \
        --output none

    export APPINSIGHTS_CONNECTION_STRING=$(az monitor app-insights component show \
        --app "$APP_INSIGHTS_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query connectionString -o tsv)

    ok "App Insights '$APP_INSIGHTS_NAME' ready."
}

# ──────────────────────────────────────────────────────────────────
# Storage Account
# ──────────────────────────────────────────────────────────────────

deploy_storage() {
    log "Storage Account"
    az storage account create \
        --name "$STORAGE_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --output none

    export STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
        --name "$STORAGE_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query connectionString -o tsv)

    ok "Storage Account '$STORAGE_NAME' ready."
}

# ──────────────────────────────────────────────────────────────────
# Azure Container Registry
# ──────────────────────────────────────────────────────────────────

deploy_acr() {
    log "Azure Container Registry"
    az acr create \
        --name "$ACR_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Basic \
        --admin-enabled true \
        --output none

    ok "ACR '$ACR_NAME' ready."
}

# ──────────────────────────────────────────────────────────────────
# Build Container Image — az acr build (no local Docker)
# ──────────────────────────────────────────────────────────────────

build_image_acr() {
    log "Build image via az acr build (no local Docker)"
    info "Image: $IMAGE_TAG"

    az acr build \
        --registry "$ACR_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "${CONTAINER_APP_NAME}:${TIMESTAMP}" \
        --file Dockerfile \
        . \
        --output none

    ok "Image built and pushed: $IMAGE_TAG"
}

# ──────────────────────────────────────────────────────────────────
# Azure Function App — Assign Managed Identity (UAMI) + SQL Settings
# ──────────────────────────────────────────────────────────────────

deploy_function_app() {

    log "Function App Plan — Create Elastic Premium (EP1)"
    az functionapp plan create \
        --name "${FUNC_APP_NAME}-plan" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku EP1 \
        --is-linux \
        --output none

    ok "Function App Plan '${FUNC_APP_NAME}-plan' created."

    log "Function App — Create (with Managed Identity)"

    az functionapp create \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --plan "${FUNC_APP_NAME}-plan" \
        --storage-account "$STORAGE_NAME" \
        --runtime python \
        --runtime-version 3.12 \
        --functions-version 4 \
        --os-type linux \
        --assign-identity "$UAMI_ID" \
        --app-insights "$APP_INSIGHTS_NAME" \
        --output none

    ok "Function App '$FUNC_APP_NAME' (UAMI assigned) created."
    echo "UAMI_CLIENT_ID is: '$UAMI_CLIENT_ID'"

    log "Function App — Configure settings"

    az functionapp config appsettings set \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --output none \
        --settings \
            "AZSQL_SERVER=${AZSQL_SERVER}" \
            "AZSQL_DB=${AZSQL_DB}" \
            "AZSQL_UID=${AZSQL_UID}" \
            "AZSQL_PWD=${AZSQL_PWD}" \
            "AZSQL_DRIVER=${AZSQL_DRIVER}" \
            "AZURE_OPENAI_API_ENDPOINT=${AZURE_OPENAI_API_ENDPOINT}" \
            "AZURE_OPENAI_DEPLOYMENTNAME=${AZURE_OPENAI_DEPLOYMENTNAME}" \
            "AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}" \
            "AzureWebJobsStorage=${STORAGE_CONNECTION_STRING}" \
            "APPLICATIONINSIGHTS_CONNECTION_STRING=${APPINSIGHTS_CONNECTION_STRING}" \
            "FUNCTIONS_EXTENSION_VERSION=~4" \
            "FUNCTIONS_WORKER_RUNTIME=python" \
            "MANAGED_IDENTITY_CLIENT_ID=${UAMI_CLIENT_ID}" \
            "PYTHON_ENABLE_WORKER_EXTENSIONS=1"

    ok "Function App settings configured."

    log "Function App — Publish (remote build via Oryx)"

    func azure functionapp publish "$FUNC_APP_NAME" \
        --python \
        --build remote \
        2>&1 | grep -E "(Deployment|successfully|Error|Failed|WARNING|warning|Uploading|Remote build|No functions found|Could not find|Exception)"

    ok "Function App published."

    log "Function App — Retrieve host key"

    FUNCTION_CODE=$(az functionapp keys list \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "functionKeys.default" \
        -o tsv)

    info "Function code to use: $FUNCTION_CODE"

    export FUNCTION_BASE_URL="https://${FUNC_APP_NAME}.azurewebsites.net"
    info "Function base URL: $FUNCTION_BASE_URL"

    export FUNCTION_START_URL="${FUNCTION_BASE_URL}/api/http_start_single_analysis?code=${FUNCTION_CODE}"
    info "Function start URL: $FUNCTION_START_URL"

    # Smoke test — POST should return 202
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"customer_id":"SMOKE","note":"smoke test"}' \
        "${FUNCTION_START_URL}")

    if [ "$HTTP_STATUS" = "202" ]; then
        ok "Function smoke test passed (HTTP 202)."
    else
        warn "Function smoke test returned HTTP $HTTP_STATUS (expected 202)."
    fi
}

# ──────────────────────────────────────────────────────────────────
# Container App Environment + Container App — Assign Managed Identity
# ──────────────────────────────────────────────────────────────────

deploy_container_app() {
    log "Container App — Environment"
    az containerapp env create \
        --name "$CONTAINER_APP_ENV" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --logs-workspace-id "$LAW_ID" \
        --logs-workspace-key "$LAW_KEY" \
        --output none
    ok "Container App Environment '$CONTAINER_APP_ENV' ready."

    log "Container App — Retrieve ACR credentials"
    ACR_USERNAME=$(az acr credential show \
        --name "$ACR_NAME" \
        --query username -o tsv)
    ACR_PASSWORD=$(az acr credential show \
        --name "$ACR_NAME" \
        --query "passwords[0].value" -o tsv)
    ok "ACR credentials retrieved."

    log "Container App — Deploy (with Managed Identity)"
    info "UAMI_ID to use: $UAMI_ID"
    info "Image: $IMAGE_TAG"

    az containerapp create \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$CONTAINER_APP_ENV" \
        --image "$IMAGE_TAG" \
        --registry-server "${ACR_NAME}.azurecr.io" \
        --registry-username "$ACR_USERNAME" \
        --registry-password "$ACR_PASSWORD" \
        --target-port 8000 \
        --ingress external \
        --min-replicas 0 \
        --max-replicas 10 \
        --cpu 1.0 \
        --memory 2.0Gi \
        --user-assigned "$UAMI_ID" \
        --output none

    az containerapp secret set \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --secrets \
            function-start-url="${FUNCTION_START_URL}" \
            azure-openai-api-key="${AZURE_OPENAI_API_KEY}" \
            azure-openai-deploymentname="${AZURE_OPENAI_DEPLOYMENTNAME}" \
            azure-openai-endpoint="${AZURE_OPENAI_API_ENDPOINT}" \
            azure-sql-database="${AZSQL_DB}" \
            azure-sql-username="${AZSQL_UID}" \
            azure-sql-password="${AZSQL_PWD}" \
            azure-sql-server="${AZSQL_SERVER}" \
            azure-sql-driver="${AZSQL_DRIVER}" \
            managed-identity-client-id="${UAMI_CLIENT_ID}"

    az containerapp update \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --set-env-vars \
            "AZURE_OPENAI_API_ENDPOINT=secretref:azure-openai-endpoint" \
            "AZURE_OPENAI_DEPLOYMENTNAME=secretref:azure-openai-deploymentname" \
            "AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key" \
            "FUNCTION_START_URL=secretref:function-start-url" \
            "AZURE_SQL_USERNAME=secretref:azure-sql-username" \
            "AZURE_SQL_PASSWORD=secretref:azure-sql-password" \
            "AZURE_SQL_DATABASE=secretref:azure-sql-database" \
            "AZURE_SQL_SERVER=secretref:azure-sql-server" \
            "AZSQL_DRIVER=secretref:azure-sql-driver" \
            "MANAGED_IDENTITY_CLIENT_ID=secretref:managed-identity-client-id"

    ok "Container App '$CONTAINER_APP_NAME' (UAMI assigned, env/secrets) deployed."
}

# ──────────────────────────────────────────────────────────────────
# Verify
# ──────────────────────────────────────────────────────────────────

verify_deployment() {
    log "Verify deployment"

    CONTAINER_APP_URL=$(az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.configuration.ingress.fqdn" -o tsv)

    info "Waiting 20s for Container App to be ready..."
    sleep 20

    HEALTH=$(curl -sf "https://${CONTAINER_APP_URL}/api/health" 2>/dev/null || echo "FAILED")
    if echo "$HEALTH" | grep -q '"ok"'; then
        ok "Health check passed."
    else
        warn "Health check failed: $HEALTH"
    fi

    EVAL=$(curl -s -X POST \
        "https://${CONTAINER_APP_URL}/api/evaluate" \
        -H "Content-Type: application/json" \
        -d '{"customer_id":"DEPLOY_TEST","note":"I want to cancel my account"}')

    if echo "$EVAL" | grep -q '"instance_id"'; then
        ok "/api/evaluate working — orchestration started."
    else
        warn "/api/evaluate response: $EVAL"
        warn "Debug: az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"
    fi

    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "  Deployment complete!"
    echo ""
    echo "  Web App  →  https://${CONTAINER_APP_URL}/"
    echo "  FinOps   →  https://${CONTAINER_APP_URL}/finops"
    echo "  Health   →  https://${CONTAINER_APP_URL}/api/health"
    echo ""
    echo "  Function →  ${FUNCTION_BASE_URL}"
    echo "  Image    →  ${IMAGE_TAG}"
    echo "════════════════════════════════════════════════════════"
}

# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

main() {
    destroy_created_resources
    check_prerequisites
    deploy_log_analytics
    deploy_app_insights
    deploy_storage
    deploy_acr
    build_image_acr
    deploy_function_app
    deploy_container_app
    verify_deployment
}

main "$@"