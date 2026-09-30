#!/usr/bin/env bash
# ==============================================================================
# DPIG (Digital Public Infrastructure Governance)
# Automated Staging / Development Deployment Script (<5k MAU Tier)
# Google Cloud Run + Firebase Hosting + Cloud SQL / Persistent SQLite
# ==============================================================================
set -euo pipefail

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}"
echo "========================================================================"
echo "    DPIG STAGING DEPLOYMENT (<5k MAU) - GOOGLE CLOUD & FIREBASE"
echo "========================================================================"
echo -e "${NC}"

# 1. Dependency Checks
echo -e "${BLUE}==> [1/7] Checking deployment prerequisites...${NC}"

HAS_GCLOUD=true
HAS_FIREBASE=true

if ! command -v gcloud &> /dev/null; then
    HAS_GCLOUD=false
fi

if ! command -v firebase &> /dev/null; then
    HAS_FIREBASE=false
fi

if [ "$HAS_GCLOUD" = false ] || [ "$HAS_FIREBASE" = false ]; then
    echo -e "${YELLOW}Warning: One or more CLI tools are not installed in your PATH:${NC}"
    if [ "$HAS_GCLOUD" = false ]; then
        echo -e "  - ${RED}gcloud CLI missing${NC}. Install via: ${BOLD}brew install --cask google-cloud-sdk${NC} or https://cloud.google.com/sdk/docs/install"
    fi
    if [ "$HAS_FIREBASE" = false ]; then
        echo -e "  - ${RED}firebase CLI missing${NC}. Install via: ${BOLD}npm install -g firebase-tools${NC} or ${BOLD}curl -sL https://firebase.tools | bash${NC}"
    fi
    echo ""
    echo -e "${YELLOW}You can still run this script once you install the CLIs, or you can deploy via GitHub Actions / Cloud Build.${NC}"
    read -p "Do you want to proceed and verify environment configuration anyway? (y/n): " proceed_anyway
    if [[ ! "$proceed_anyway" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 2. Configuration Setup
echo -e "\n${BLUE}==> [2/7] Configuring project variables...${NC}"

# Detect default project from gcloud if available
CURRENT_GCP_PROJECT=""
if [ "$HAS_GCLOUD" = true ]; then
    CURRENT_GCP_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi

read -p "Enter your Google Cloud / Firebase Project ID [${CURRENT_GCP_PROJECT:-dpig-staging}]: " PROJECT_ID
PROJECT_ID="${PROJECT_ID:-${CURRENT_GCP_PROJECT:-dpig-staging}}"

read -p "Enter deployment region (e.g. asia-south1 for Mumbai, us-central1) [asia-south1]: " REGION
REGION="${REGION:-asia-south1}"

SERVICE_NAME="dpig-staging"
REPO_NAME="dpig-repo"
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/app:staging"

echo -e "Target Project:  ${BOLD}${PROJECT_ID}${NC}"
echo -e "Target Region:   ${BOLD}${REGION}${NC}"
echo -e "Cloud Run Svc:   ${BOLD}${SERVICE_NAME}${NC}"
echo -e "Container Image: ${BOLD}${IMAGE_TAG}${NC}"

# Database Selection
echo -e "\n${CYAN}Select Database Strategy for Staging (<5k MAU):${NC}"
echo "  1) Cloud SQL PostgreSQL 16 (Recommended for High Fidelity, ~\$18/mo)"
echo "  2) Persistent SQLite (Zero Additional Cost for Dev Staging, \$0/mo)"
read -p "Enter choice [1 or 2, default 1]: " DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

CLOUD_SQL_INSTANCE=""
CLOUD_SQL_CONN=""
POSTGRES_PASS=""
USE_SQLITE="False"

if [ "$DB_CHOICE" = "1" ]; then
    USE_SQLITE="False"
    read -p "Enter Cloud SQL Instance Name [dpig-sql-staging]: " CLOUD_SQL_INSTANCE
    CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-dpig-sql-staging}"
    CLOUD_SQL_CONN="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"
    read -s -p "Enter PostgreSQL password for user 'dpig_user' [auto-generate]: " POSTGRES_PASS
    echo ""
    if [ -z "$POSTGRES_PASS" ]; then
        POSTGRES_PASS="DpigSecurePass_$(openssl rand -hex 6 2>/dev/null || echo '2026_Staging')"
        echo -e "Auto-generated DB password: ${BOLD}${POSTGRES_PASS}${NC}"
    fi
else
    USE_SQLITE="True"
    echo -e "${GREEN}Using persistent SQLite database mode.${NC}"
fi

# API Keys
GEMINI_KEY="${GEMINI_API_KEY:-}"
if [ -z "$GEMINI_KEY" ]; then
    read -p "Enter Google Gemini API Key (press Enter to skip): " GEMINI_KEY
fi

MAPS_KEY="${GOOGLE_MAPS_API_KEY:-}"
if [ -z "$MAPS_KEY" ]; then
    read -p "Enter Google Maps API Key (press Enter to skip): " MAPS_KEY
fi

DJANGO_SECRET="dpig-staging-secret-$(openssl rand -hex 16 2>/dev/null || echo 'staging-key-2026')"
INTERNAL_KEY="dpig-cron-$(openssl rand -hex 12 2>/dev/null || echo 'internal-cron-2026')"

if [ "$HAS_GCLOUD" = false ] || [ "$HAS_FIREBASE" = false ]; then
    echo -e "\n${YELLOW}Prerequisite CLI tools missing. Saving staging configuration to .env.staging...${NC}"
    cat <<EOF > .env.staging
DJANGO_SECRET_KEY=${DJANGO_SECRET}
DJANGO_DEBUG=False
ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=https://*.web.app,https://*.firebaseapp.com,https://*.run.app
USE_SQLITE=${USE_SQLITE}
DB_ENGINE=django.db.backends.postgresql
CLOUD_SQL_CONNECTION_NAME=${CLOUD_SQL_CONN}
POSTGRES_DB=dpig_db
POSTGRES_USER=dpig_user
POSTGRES_PASSWORD=${POSTGRES_PASS}
RUN_MIGRATIONS=true
GEMINI_API_KEY=${GEMINI_KEY}
GEMINI_MODEL=gemini-3.8-flash
GOOGLE_MAPS_API_KEY=${MAPS_KEY}
INTERNAL_API_KEY=${INTERNAL_KEY}
WEB_CONCURRENCY=2
EOF
    echo -e "${GREEN}Wrote .env.staging successfully.${NC}"
    echo "Install gcloud and firebase CLIs, then re-run ./deploy_staging.sh to finish deployment."
    exit 0
fi

# 3. Enable Required Google Cloud APIs
echo -e "\n${BLUE}==> [3/7] Enabling required Google Cloud APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    firebase.googleapis.com \
    --project="${PROJECT_ID}"

# 4. Provision Cloud SQL (if selected)
if [ "$DB_CHOICE" = "1" ]; then
    echo -e "\n${BLUE}==> [4/7] Checking Cloud SQL PostgreSQL instance...${NC}"
    if ! gcloud sql instances describe "${CLOUD_SQL_INSTANCE}" --project="${PROJECT_ID}" &>/dev/null; then
        echo -e "${YELLOW}Creating lightweight Cloud SQL instance '${CLOUD_SQL_INSTANCE}' (db-f1-micro)...${NC}"
        gcloud sql instances create "${CLOUD_SQL_INSTANCE}" \
            --project="${PROJECT_ID}" \
            --database-version=POSTGRES_16 \
            --tier=db-f1-micro \
            --region="${REGION}" \
            --storage-type=SSD \
            --storage-size=10GB \
            --storage-auto-increase \
            --backup \
            --quiet

        echo "Creating database 'dpig_db'..."
        gcloud sql databases create dpig_db --instance="${CLOUD_SQL_INSTANCE}" --project="${PROJECT_ID}" || true

        echo "Creating database user 'dpig_user'..."
        gcloud sql users create dpig_user \
            --instance="${CLOUD_SQL_INSTANCE}" \
            --project="${PROJECT_ID}" \
            --password="${POSTGRES_PASS}" || true
    else
        echo -e "${GREEN}Cloud SQL instance '${CLOUD_SQL_INSTANCE}' already exists.${NC}"
    fi
else
    echo -e "\n${BLUE}==> [4/7] Skipping Cloud SQL (SQLite selected)...${NC}"
fi

# 5. Build and Push Container Image
echo -e "\n${BLUE}==> [5/7] Building container image via Google Cloud Build...${NC}"
# Ensure Artifact Registry repository exists
if ! gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud artifacts repositories create "${REPO_NAME}" \
        --repository-format=docker \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --description="DPIG Docker Container Repository"
fi

gcloud builds submit \
    --project="${PROJECT_ID}" \
    --tag="${IMAGE_TAG}" \
    .

# 6. Deploy to Google Cloud Run
echo -e "\n${BLUE}==> [6/7] Deploying Cloud Run service '${SERVICE_NAME}'...${NC}"

ENV_VARS="DJANGO_SECRET_KEY=${DJANGO_SECRET},DJANGO_DEBUG=False,ALLOWED_HOSTS=*,CSRF_TRUSTED_ORIGINS=https://*.web.app;https://*.firebaseapp.com;https://*.run.app,RUN_MIGRATIONS=true,USE_SQLITE=${USE_SQLITE},GEMINI_API_KEY=${GEMINI_KEY},GEMINI_MODEL=gemini-3.8-flash,GOOGLE_MAPS_API_KEY=${MAPS_KEY},INTERNAL_API_KEY=${INTERNAL_KEY},WEB_CONCURRENCY=2"

if [ "$DB_CHOICE" = "1" ]; then
    ENV_VARS="${ENV_VARS},CLOUD_SQL_CONNECTION_NAME=${CLOUD_SQL_CONN},POSTGRES_DB=dpig_db,POSTGRES_USER=dpig_user,POSTGRES_PASSWORD=${POSTGRES_PASS}"
    
    gcloud run deploy "${SERVICE_NAME}" \
        --project="${PROJECT_ID}" \
        --image="${IMAGE_TAG}" \
        --region="${REGION}" \
        --platform=managed \
        --allow-unauthenticated \
        --port=8080 \
        --memory=1Gi \
        --cpu=1 \
        --min-instances=0 \
        --max-instances=2 \
        --concurrency=80 \
        --timeout=300 \
        --add-cloudsql-instances="${CLOUD_SQL_CONN}" \
        --set-env-vars="${ENV_VARS}"
else
    gcloud run deploy "${SERVICE_NAME}" \
        --project="${PROJECT_ID}" \
        --image="${IMAGE_TAG}" \
        --region="${REGION}" \
        --platform=managed \
        --allow-unauthenticated \
        --port=8080 \
        --memory=1Gi \
        --cpu=1 \
        --min-instances=0 \
        --max-instances=2 \
        --concurrency=80 \
        --timeout=300 \
        --set-env-vars="${ENV_VARS}"
fi

# Fetch Cloud Run URL
CLOUD_RUN_URL=$(gcloud run services describe "${SERVICE_NAME}" --platform=managed --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')
echo -e "${GREEN}Cloud Run Service deployed at: ${BOLD}${CLOUD_RUN_URL}${NC}"

# 7. Configure and Deploy Firebase Hosting
echo -e "\n${BLUE}==> [7/7] Configuring Firebase Hosting rewrites to Cloud Run...${NC}"

# Update firebase.json with the chosen region and service name
cat <<EOF > firebase.json
{
  "hosting": {
    "public": "firebase_public",
    "ignore": [
      "firebase.json",
      "**/.*",
      "**/node_modules/**"
    ],
    "rewrites": [
      {
        "source": "**",
        "run": {
          "serviceId": "${SERVICE_NAME}",
          "region": "${REGION}"
        }
      }
    ],
    "headers": [
      {
        "source": "**/*.@(jpg|jpeg|gif|png|svg|webp|js|css|woff|woff2|ttf)",
        "headers": [
          {
            "key": "Cache-Control",
            "value": "public, max-age=31536000, immutable"
          }
        ]
      }
    ]
  }
}
EOF

# Update .firebaserc
cat <<EOF > .firebaserc
{
  "projects": {
    "default": "${PROJECT_ID}"
  }
}
EOF

# Deploy Firebase Hosting
echo "Deploying Firebase CDN Edge..."
firebase deploy --only hosting --project="${PROJECT_ID}"

FIREBASE_URL="https://${PROJECT_ID}.web.app"

# Smoke Test
echo -e "\n${BLUE}==> Running post-deployment health check...${NC}"
HEALTH_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${CLOUD_RUN_URL}/healthz/" || echo "000")

echo -e "\n${GREEN}${BOLD}========================================================================${NC}"
echo -e "${GREEN}${BOLD}             DPIG STAGING DEPLOYMENT COMPLETED SUCCESSFULLY             ${NC}"
echo -e "${GREEN}${BOLD}========================================================================${NC}"
echo -e "Primary Portal URL (Firebase CDN): ${CYAN}${BOLD}${FIREBASE_URL}${NC}"
echo -e "Secondary Portal URL:              ${CYAN}https://${PROJECT_ID}.firebaseapp.com${NC}"
echo -e "Cloud Run Direct Endpoint:         ${CYAN}${CLOUD_RUN_URL}${NC}"
echo -e "Health Probe (/healthz/):          Status HTTP ${HEALTH_HTTP_CODE}"
echo -e "SuperAdmin Credentials:            Username: ${BOLD}superadmin${NC} | Password: ${BOLD}Admin@Dpig2026${NC}"
echo -e "Internal Cron Secret:              ${BOLD}${INTERNAL_KEY}${NC}"
echo -e "Cost Tier:                         Staging / Development (<5k MAU) ~\$0 - \$20/month"
echo -e "========================================================================\n"
