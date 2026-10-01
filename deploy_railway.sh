#!/usr/bin/env bash
# ==============================================================================
# DPIG (Digital Public Infrastructure Governance)
# Deployment Automation Script for Railway (railway.com)
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
echo "          DPIG PLATFORM - RAILWAY (railway.com) DEPLOYMENT"
echo "========================================================================"
echo -e "${NC}"

# 1. Check Railway CLI
echo -e "${BLUE}==> [1/5] Checking Railway CLI availability...${NC}"
RAILWAY_CMD=""
if command -v railway &> /dev/null; then
    RAILWAY_CMD="railway"
    echo -e "${GREEN}Found installed Railway CLI: $(railway --version)${NC}"
elif command -v npx &> /dev/null; then
    RAILWAY_CMD="npx @railway/cli"
    echo -e "${YELLOW}Using npx @railway/cli runner.${NC}"
else
    echo -e "${RED}Error: Neither 'railway' CLI nor 'npm/npx' was found in your PATH.${NC}"
    echo -e "Please install the Railway CLI by running: ${BOLD}npm install -g @railway/cli${NC} or ${BOLD}brew install railway${NC}"
    exit 1
fi

# 2. Authentication check
echo -e "\n${BLUE}==> [2/5] Checking Railway authentication status...${NC}"
if ! $RAILWAY_CMD whoami &> /dev/null; then
    echo -e "${YELLOW}You are not currently logged in to Railway.${NC}"
    echo -e "Launching Railway authentication in your browser..."
    $RAILWAY_CMD login
fi

echo -e "${GREEN}Authenticated with Railway as: $($RAILWAY_CMD whoami)${NC}"

# 3. Project Link / Init
echo -e "\n${BLUE}==> [3/5] Linking or Initializing Railway Project...${NC}"
if ! $RAILWAY_CMD status &> /dev/null; then
    echo -e "${CYAN}No linked project found for this directory. Initializing a new project...${NC}"
    $RAILWAY_CMD init
else
    echo -e "${GREEN}Linked to existing Railway project.${NC}"
fi

# 4. Deployment confirmation
echo -e "\n${BLUE}==> [4/5] Preparing deployment...${NC}"
echo "Configuration files detected:"
echo "  - Dockerfile: /app container with Python 3.12, Gunicorn, and WhiteNoise"
echo "  - railway.json: Custom Dockerfile build and healthcheck specifications"
echo "  - Procfile: Process specifications for web and optional worker"
echo ""
echo -e "${YELLOW}Ensure your Railway project has the following plugins added in the dashboard:${NC}"
echo "  1) PostgreSQL database plugin (automatically provides DATABASE_URL)"
echo "  2) Redis database plugin (automatically provides REDIS_URL)"
echo ""
read -p "Deploy and upload local build to Railway now? (y/n, default y): " PROCEED_DEPLOY
PROCEED_DEPLOY="${PROCEED_DEPLOY:-y}"

if [[ "$PROCEED_DEPLOY" =~ ^[Yy]$ ]]; then
    echo -e "\n${BLUE}==> [5/5] Deploying to Railway...${NC}"
    $RAILWAY_CMD up --detach
    echo -e "\n${GREEN}${BOLD}========================================================================${NC}"
    echo -e "${GREEN}${BOLD}              RAILWAY DEPLOYMENT INITIATED SUCCESSFULLY                 ${NC}"
    echo -e "${GREEN}${BOLD}========================================================================${NC}"
    echo -e "To view live build and runtime logs:"
    echo -e "  ${BOLD}${RAILWAY_CMD} logs${NC}"
    echo -e "To open your project dashboard in the browser:"
    echo -e "  ${BOLD}${RAILWAY_CMD} open${NC}"
    echo -e "========================================================================\n"
else
    echo -e "${YELLOW}Deployment paused. You can deploy anytime with:${NC} ${BOLD}${RAILWAY_CMD} up${NC}"
fi
