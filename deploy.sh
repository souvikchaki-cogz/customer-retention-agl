#!/bin/bash
# ==============================================================================
# AGL Customer Retention — Idempotent Azure Deployment Script
# ==============================================================================

set -euo pipefail
set +H

# ── Load .env safely ───────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "❌ .env file not found. Please create one in the repo root."
  exit 1
fi

echo "==> Loading .env..."
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" =~ ^# ]] && continue
  raw_value=$(grep -m1 "^${key}=" .env | cut -d'=' -f2-)
  raw_value="${raw_value%\"}"
  raw_value="${raw_value#\"}"
  raw_value="${raw_value%\'}"
  raw_value="${raw_value#\'}"
  export "${key}=${raw_value}"
done < .env

# ── Derived variables ─────────────────────────────────────────────────────────
export TIMESTAMP=$(date +%Y%m%d%H%M%S)
export ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
export IMAGE_TAG="${ACR_LOGIN_SERVER}/${CONTAINER_APP_NAME}:${TIMESTAMP}"
export UAMI_ID="/subscriptions/${UAMI_SUBSCRIPTION_ID}/resourceGroups/${UAMI_RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${UAMI_NAME}"
export FUNCTION_BASE_URL="https://${FUNC_APP_NAME}.azurewebsites.net"

# ── Helpers ────────────────────────────────────────────────────────────────────
log()  { echo ""; echo "──────────────────────────────────────────────"; echo "  ▶  $1"; echo "──────────────────────────────────────────────"; }
ok()   { echo "  ✅ $1"; }
info() { echo "  ℹ️  $1"; }
warn() { echo "  ⚠️  $1"; }

# ── Sanity check ───────────────────────────────────────────────────────────────
log "Variables loaded"
info "RESOURCE_GROUP:  $RESOURCE_GROUP"
info "LOCATION:        $LOCATION"
info "FUNC_APP_NAME:   $FUNC_APP_NAME"
info "ACR_NAME:        $ACR_NAME"
info "AZSQL_SERVER:    $AZSQL_SERVER"
info "UAMI_ID:         $UAMI_ID"
info "IMAGE_TAG:       $IMAGE_TAG"

# ── Prerequisites ──────────────────────────────────────────────────────────────
check_prerequisites() {
    log "Checking prerequisites"

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

# ── Destroy existing resources ─────────────────────────────────────────────────
destroy_existing_resources() {
    log "Destroying existing resources (clean slate before deploy)"

    if az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Container App: $CONTAINER_APP_NAME"
        az containerapp delete \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "Container App delete issued."
        info "Waiting for Container App to be fully deprovisioned..."
        for i in {1..20}; do
            if ! az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
                ok "Container App fully deprovisioned."
                break
            fi
            info "Attempt ${i}/20 — still deprovisioning, waiting 15s..."
            sleep 15
        done
    else
        info "Container App $CONTAINER_APP_NAME not found — skipping."
    fi

    if az containerapp env show --name "$CONTAINER_APP_ENV" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Container App Environment: $CONTAINER_APP_ENV"
        az containerapp env delete \
            --name "$CONTAINER_APP_ENV" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "Container App Environment delete issued."
        info "Waiting for Container App Environment to be fully deprovisioned..."
        for i in {1..20}; do
            if ! az containerapp env show --name "$CONTAINER_APP_ENV" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
                ok "Container App Environment fully deprovisioned."
                break
            fi
            info "Attempt ${i}/20 — still deprovisioning, waiting 15s..."
            sleep 15
        done
    else
        info "Container App Environment $CONTAINER_APP_ENV not found — skipping."
    fi

    if az functionapp show --name "$FUNC_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Function App: $FUNC_APP_NAME"
        az functionapp delete \
            --name "$FUNC_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --output none
        ok "Function App deleted."
    else
        info "Function App $FUNC_APP_NAME not found — skipping."
    fi

    if az functionapp plan show --name "${FUNC_APP_NAME}-plan" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Function App Plan: ${FUNC_APP_NAME}-plan"
        az functionapp plan delete \
            --name "${FUNC_APP_NAME}-plan" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "Function App Plan deleted."
    else
        info "Function App Plan ${FUNC_APP_NAME}-plan not found — skipping."
    fi

    if az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting ACR: $ACR_NAME"
        az acr delete \
            --name "$ACR_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "ACR deleted."
    else
        info "ACR $ACR_NAME not found — skipping."
    fi

    if az storage account show --name "$STORAGE_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Storage Account: $STORAGE_NAME"
        az storage account delete \
            --name "$STORAGE_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "Storage Account deleted."
    else
        info "Storage Account $STORAGE_NAME not found — skipping."
    fi

    if az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Application Insights: $APP_INSIGHTS_NAME"
        az monitor app-insights component delete \
            --app "$APP_INSIGHTS_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --output none
        ok "Application Insights deleted."
    else
        info "Application Insights $APP_INSIGHTS_NAME not found — skipping."
    fi

    if az monitor log-analytics workspace show --workspace-name "$LOG_ANALYTICS_WORKSPACE" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        info "Deleting Log Analytics Workspace: $LOG_ANALYTICS_WORKSPACE"
        az monitor log-analytics workspace delete \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
            --resource-group "$RESOURCE_GROUP" \
            --yes --output none
        ok "Log Analytics Workspace deleted."
    else
        info "Log Analytics Workspace $LOG_ANALYTICS_WORKSPACE not found — skipping."
    fi

    ok "All existing resources cleaned up."
    info "Waiting 30s for deletions to propagate..."
    sleep 30
}

# ── Step 1: Log Analytics Workspace ───────────────────────────────────────────
deploy_log_analytics() {
    log "Step 1: Log Analytics Workspace"
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
    info "LAW_ID: $LAW_ID"
}

# ── Step 2: Application Insights ──────────────────────────────────────────────
deploy_app_insights() {
    log "Step 2: Application Insights"
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

# ── Step 3: Storage Account ────────────────────────────────────────────────────
deploy_storage() {
    log "Step 3: Storage Account"
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
    info "STORAGE_CONNECTION_STRING captured ✅"
}

# ── Step 4: Function App ───────────────────────────────────────────────────────
deploy_function_app() {
    log "Step 4: Function App Plan (EP1)"
    az functionapp plan create \
        --name "${FUNC_APP_NAME}-plan" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku EP1 \
        --is-linux \
        --output none
    ok "Function App Plan '${FUNC_APP_NAME}-plan' created."

    log "Step 4: Function App — Create (with UAMI)"
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
    ok "Function App '$FUNC_APP_NAME' created with UAMI."

    info "Waiting for Function App to reach Running state..."
    for i in {1..10}; do
        STATE=$(az functionapp show \
            --name "$FUNC_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --query "state" -o tsv)
        info "Attempt ${i}/10 — state: ${STATE}"
        if [ "$STATE" = "Running" ]; then
            ok "Function App is Running."
            break
        fi
        if [ "$i" = "10" ]; then
            echo "❌ Function App did not reach Running state. Exiting."
            exit 1
        fi
        sleep 15
    done

    log "Step 4: Function App — Configure settings"
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
            "AZSQL_USE_ENTRA=${AZSQL_USE_ENTRA}" \
            "AZURE_OPENAI_API_ENDPOINT=${AZURE_OPENAI_API_ENDPOINT}" \
            "AZURE_OPENAI_DEPLOYMENTNAME=${AZURE_OPENAI_DEPLOYMENTNAME}" \
            "AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}" \
            "AZURE_OPENAI_API_VERSION=2025-01-01-preview" \
            "AzureWebJobsStorage=${STORAGE_CONNECTION_STRING}" \
            "APPLICATIONINSIGHTS_CONNECTION_STRING=${APPINSIGHTS_CONNECTION_STRING}" \
            "FUNCTIONS_EXTENSION_VERSION=~4" \
            "FUNCTIONS_WORKER_RUNTIME=python" \
            "MANAGED_IDENTITY_CLIENT_ID=${UAMI_CLIENT_ID}" \
            "LOG_LEVEL=INFO" \
            "REPLAY_QUEUE_NAME=event-replay" \
            "USE_SQL_RULES=1" \
            "PYTHON_ENABLE_WORKER_EXTENSIONS=1"
    ok "Function App settings configured."

    info "Waiting 60s for app settings to propagate..."
    sleep 60

    log "Step 4: Function App — Publish (force clean redeploy)"
    PUBLISH_OUTPUT=$(func azure functionapp publish "$FUNC_APP_NAME" \
        --python \
        --force 2>&1) || { echo "❌ func publish failed"; echo "$PUBLISH_OUTPUT"; exit 1; }
    echo "$PUBLISH_OUTPUT" | grep -E "(Deployment|successfully|Error|Failed|WARNING|warning|Uploading|Remote build|No functions found|Could not find|Exception)" || true
    ok "Function App published."

    info "Waiting 60s for functions to register..."
    sleep 60

    info "Registered functions:"
    az functionapp function list \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[].{Function:name}" \
        -o table

    log "Step 4: Function App — Retrieve host key"
    export FUNCTION_CODE=$(az functionapp keys list \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "functionKeys.default" \
        -o tsv)

    export FUNCTION_BASE_URL="https://${FUNC_APP_NAME}.azurewebsites.net"
    export FUNCTION_START_URL="${FUNCTION_BASE_URL}/api/http_start_single_analysis?code=${FUNCTION_CODE}"

    info "FUNCTION_BASE_URL:  $FUNCTION_BASE_URL"
    info "FUNCTION_START_URL: $FUNCTION_START_URL"

    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"customer_id":"SMOKE","text":"smoke test"}' \
        "${FUNCTION_START_URL}")

    if [ "$HTTP_STATUS" = "202" ]; then
        ok "Function smoke test passed (HTTP 202)."
    else
        warn "Function smoke test returned HTTP $HTTP_STATUS (expected 202)."
    fi
}

# ── Step 5: ACR — Create & Remote Build ───────────────────────────────────────
deploy_acr() {
    log "Step 5: Azure Container Registry — Create"
    az acr create \
        --name "$ACR_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Basic \
        --admin-enabled true \
        --output none
    ok "ACR '$ACR_NAME' created."

    log "Step 5: ACR — Remote Build (no local Docker needed)"
    info "Image: ${IMAGE_TAG}"
    az acr build \
        --registry "$ACR_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "${CONTAINER_APP_NAME}:${TIMESTAMP}" \
        --file Dockerfile \
        .
    ok "Image built and pushed: ${IMAGE_TAG}"

    log "Step 5: ACR — Retrieve credentials"
    export ACR_USERNAME=$(az acr credential show \
        --name "$ACR_NAME" \
        --query "username" -o tsv)

    export ACR_PASSWORD=$(az acr credential show \
        --name "$ACR_NAME" \
        --query "passwords[0].value" -o tsv)

    ok "ACR credentials retrieved."
    info "ACR_USERNAME:  $ACR_USERNAME"
    info "ACR_PASSWORD:  ${ACR_PASSWORD:0:5}*****"
    info "IMAGE_TAG:     $IMAGE_TAG"
}

# ── Step 6: Container App Environment + Container App ─────────────────────────
deploy_container_app() {
    log "Step 6: Container App Environment"
    az containerapp env create \
        --name "$CONTAINER_APP_ENV" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --logs-workspace-id "$LAW_ID" \
        --logs-workspace-key "$LAW_KEY" \
        --output none
    ok "Container App Environment '$CONTAINER_APP_ENV' ready."

    log "Step 6: Container App — Deploy (with UAMI)"
    info "Image: $IMAGE_TAG"
    az containerapp create \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$CONTAINER_APP_ENV" \
        --image "$IMAGE_TAG" \
        --registry-server "$ACR_LOGIN_SERVER" \
        --registry-username "$ACR_USERNAME" \
        --registry-password "$ACR_PASSWORD" \
        --target-port 8000 \
        --ingress external \
        --cpu 1.0 \
        --memory 2.0Gi \
        --min-replicas 0 \
        --max-replicas 10 \
        --user-assigned "$UAMI_ID" \
        --output none

    log "Step 6: Container App — Set secrets"
    az containerapp secret set \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --secrets \
            azure-openai-api-key="${AZURE_OPENAI_API_KEY}" \
            azure-sql-password="${AZSQL_PWD}" \
            appinsights-connection-string="${APPINSIGHTS_CONNECTION_STRING}"
    ok "Secrets set."

    log "Step 6: Container App — Set environment variables"
    az containerapp update \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --set-env-vars \
            "FUNCTION_START_URL=${FUNCTION_START_URL}" \
            "FUNCTION_BASE_URL=${FUNCTION_BASE_URL}" \
            "FUNCTION_CODE=${FUNCTION_CODE}" \
            "AZSQL_SERVER=${AZSQL_SERVER}" \
            "AZSQL_DB=${AZSQL_DB}" \
            "AZSQL_UID=${AZSQL_UID}" \
            "AZSQL_DRIVER=${AZSQL_DRIVER}" \
            "AZSQL_USE_ENTRA=${AZSQL_USE_ENTRA}" \
            "MANAGED_IDENTITY_CLIENT_ID=${UAMI_CLIENT_ID}" \
            "AZURE_OPENAI_API_ENDPOINT=${AZURE_OPENAI_API_ENDPOINT}" \
            "AZURE_OPENAI_DEPLOYMENTNAME=${AZURE_OPENAI_DEPLOYMENTNAME}" \
            "AZURE_OPENAI_API_VERSION=2025-01-01-preview" \
            "LOG_LEVEL=INFO" \
            "AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key" \
            "AZSQL_PWD=secretref:azure-sql-password" \
            "APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection-string"
    ok "Container App '$CONTAINER_APP_NAME' deployed with UAMI, env vars and secrets."
}

# ── Step 7: Verify ─────────────────────────────────────────────────────────────
verify_deployment() {
    log "Step 7: Verify deployment"

    export CONTAINER_APP_URL=$(az containerapp show \
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

    TRIGGERS=$(curl -sf "https://${CONTAINER_APP_URL}/api/triggers" 2>/dev/null || echo "FAILED")
    if echo "$TRIGGERS" | grep -q '"triggers"'; then
        ok "Triggers endpoint responding."
    else
        warn "Triggers endpoint response: $TRIGGERS"
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

    FUNC_STATE=$(az functionapp show \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "state" -o tsv)
    if [ "$FUNC_STATE" = "Running" ]; then
        ok "Function App state: Running."
    else
        warn "Function App state: $FUNC_STATE (expected Running)"
    fi

    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "  ✅ Deployment complete!"
    echo ""
    echo "  Web App  →  https://${CONTAINER_APP_URL}/"
    echo "  FinOps   →  https://${CONTAINER_APP_URL}/finops"
    echo "  Health   →  https://${CONTAINER_APP_URL}/api/health"
    echo "  Triggers →  https://${CONTAINER_APP_URL}/api/triggers"
    echo ""
    echo "  Function →  ${FUNCTION_BASE_URL}"
    echo "  Image    →  ${IMAGE_TAG}"
    echo "════════════════════════════════════════════════════════"
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    check_prerequisites
    destroy_existing_resources
    deploy_log_analytics
    deploy_app_insights
    deploy_storage
    deploy_function_app
    deploy_acr
    deploy_container_app
    verify_deployment
}

main "$@"