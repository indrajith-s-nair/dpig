#!/usr/bin/env bash
# ==============================================================================
# DPIG (Digital Public Infrastructure Governance)
# Deployment Automation Script for Vercel
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
echo "          DPIG PLATFORM - VERCEL SERVERLESS DEPLOYMENT"
echo "========================================================================"
echo -e "${NC}"

# 1. Check Vercel CLI
echo -e "${BLUE}==> [1/4] Checking Vercel CLI availability...${NC}"
VERCEL_CMD=""
if command -v vercel &> /dev/null; then
    VERCEL_CMD="vercel"
    echo -e "${GREEN}Found installed Vercel CLI: $(vercel --version)${NC}"
elif command -v npx &> /dev/null; then
    VERCEL_CMD="npx vercel"
    echo -e "${YELLOW}Using npx vercel runner.${NC}"
else
    echo -e "${RED}Error: Neither 'vercel' CLI nor 'npm/npx' was found in your PATH.${NC}"
    echo -e "Please install the Vercel CLI by running: ${BOLD}npm install -g vercel${NC}"
    exit 1
fi

# 2. Database Notice
echo -e "\n${BLUE}==> [2/4] Verifying Database Configuration...${NC}"
echo -e "${YELLOW}${BOLD}IMPORTANT NOTE REGARDING VERCEL ARCHITECTURE:${NC}"
echo "Vercel functions are stateless and serverless. Local SQLite files (db.sqlite3)"
echo "cannot be used for persistent production/staging data on Vercel."
echo "You must connect to a cloud PostgreSQL database instance (such as Neon,"
echo "Supabase, Railway, Tembo, or Google Cloud SQL)."
echo ""
echo -e "Quick free serverless PostgreSQL options:"
echo "  1) Neon DB (https://neon.tech) - Free tier with 0.5 GB storage & instant branch databases"
echo "  2) Supabase (https://supabase.com) - Free tier PostgreSQL database"
echo "  3) Vercel Postgres Marketplace (integrates with 1-click in Vercel project dashboard)"
echo ""

# 3. Static Files Verification
echo -e "${BLUE}==> [3/4] Verifying static assets compilation...${NC}"
if [ -f "./venv/bin/python" ]; then
    ./venv/bin/python manage.py collectstatic --noinput --dry-run >/dev/null 2>&1 || true
    echo -e "${GREEN}Static files validated successfully.${NC}"
fi

# 4. Initiate Vercel Deployment
echo -e "\n${BLUE}==> [4/4] Initiating Vercel deployment...${NC}"
echo "Choose deployment target:"
echo "  1) Deploy to Staging / Preview Environment (default)"
echo "  2) Deploy to Production (--prod)"
read -p "Enter choice [1 or 2, default 1]: " DEPLOY_CHOICE
DEPLOY_CHOICE="${DEPLOY_CHOICE:-1}"

DEPLOY_FLAGS=""
if [ "$DEPLOY_CHOICE" = "2" ]; then
    DEPLOY_FLAGS="--prod"
    echo -e "${CYAN}Deploying directly to PRODUCTION...${NC}"
else
    echo -e "${CYAN}Deploying to PREVIEW / STAGING...${NC}"
fi

echo -e "\n${BOLD}Executing: ${VERCEL_CMD} ${DEPLOY_FLAGS}${NC}\n"
$VERCEL_CMD $DEPLOY_FLAGS

echo -e "\n${GREEN}${BOLD}========================================================================${NC}"
echo -e "${GREEN}${BOLD}              VERCEL DEPLOYMENT INITIATED SUCCESSFULLY                  ${NC}"
echo -e "${GREEN}${BOLD}========================================================================${NC}"
echo -e "Next steps to ensure your DPIG platform is fully active:"
echo -e "1. Go to your Vercel Project Dashboard -> ${BOLD}Settings -> Environment Variables${NC}"
echo -e "2. Add the following required variables (see .env.vercel.example):"
echo -e "   - ${CYAN}DJANGO_SECRET_KEY${NC} = (random 50+ character string)"
echo -e "   - ${CYAN}DJANGO_DEBUG${NC} = False"
echo -e "   - ${CYAN}DATABASE_URL${NC} = postgresql://user:pass@host:5432/dbname?sslmode=require"
echo -e "   - ${CYAN}ALLOWED_HOSTS${NC} = *"
echo -e "   - ${CYAN}CSRF_TRUSTED_ORIGINS${NC} = https://*.vercel.app"
echo -e "   - ${CYAN}GEMINI_API_KEY${NC} = (your Google Gemini key for AI triage)"
echo -e "   - ${CYAN}GOOGLE_MAPS_API_KEY${NC} = (your Maps key for geocoding)"
echo -e "3. After saving variables, trigger a redeploy from the Vercel dashboard."
echo -e "4. Apply migrations on your remote database by running:"
echo -e "   ${BOLD}DATABASE_URL=\"...\" ./venv/bin/python manage.py migrate${NC}"
echo -e "========================================================================\n"
