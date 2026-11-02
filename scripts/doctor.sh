#!/usr/bin/env bash
# PSX Research Lab — Environment & Prerequisite Doctor
# Verifies developer toolchain, zero-dollar posture, and cloud repository status.

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}      PSX Research Lab — Prerequisite Doctor          ${NC}"
echo -e "${BLUE}======================================================${NC}"

FAILURES=0

check_cmd() {
    local cmd=$1
    local name=$2
    if command -v "$cmd" >/dev/null 2>&1; then
        local version=$($cmd --version 2>&1 | head -n 1)
        echo -e "  [${GREEN}✓${NC}] $name installed: ${YELLOW}$version${NC}"
    else
        echo -e "  [${RED}✗${NC}] $name ($cmd) is NOT installed."
        FAILURES=$((FAILURES + 1))
    fi
}

echo -e "\n${BLUE}1. Checking Toolchain Requirements:${NC}"
check_cmd "node" "Node.js"
check_cmd "pnpm" "pnpm package manager"
check_cmd "python3" "Python 3"
check_cmd "git" "Git VCS"
check_cmd "gh" "GitHub CLI"

# Python version check
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        echo -e "  [${GREEN}✓${NC}] Python version $PY_VER >= 3.11"
    else
        echo -e "  [${RED}✗${NC}] Python version $PY_VER is below required 3.11+"
        FAILURES=$((FAILURES + 1))
    fi
fi

echo -e "\n${BLUE}2. Checking GitHub Authentication & Private Repositories:${NC}"
if command -v gh >/dev/null 2>&1; then
    if gh auth status >/dev/null 2>&1; then
        GH_USER=$(gh api user --jq .login 2>/dev/null || echo "authenticated")
        echo -e "  [${GREEN}✓${NC}] GitHub CLI authenticated as: ${YELLOW}$GH_USER${NC}"
        
        # Check app repo
        if gh repo view MahadImran/psx-research-lab --json isPrivate --jq .isPrivate 2>/dev/null | grep -q "true"; then
            echo -e "  [${GREEN}✓${NC}] Repository MahadImran/psx-research-lab exists and is PRIVATE"
        else
            echo -e "  [${YELLOW}!${NC}] Repository MahadImran/psx-research-lab not verified as private yet"
        fi

        # Check data archive repo
        if gh repo view MahadImran/psx-research-data --json isPrivate --jq .isPrivate 2>/dev/null | grep -q "true"; then
            echo -e "  [${GREEN}✓${NC}] Repository MahadImran/psx-research-data exists and is PRIVATE"
        else
            echo -e "  [${YELLOW}!${NC}] Repository MahadImran/psx-research-data not verified as private yet"
        fi
    else
        echo -e "  [${RED}✗${NC}] GitHub CLI is not authenticated. Run 'gh auth login'."
        FAILURES=$((FAILURES + 1))
    fi
fi

echo -e "\n${BLUE}3. Checking Zero-Dollar Cost Guard & Secrets Posture:${NC}"
# Check that no secrets exist in tracking
if git ls-files | grep -E "(\.dev\.vars|\.env|.*\.pem|.*\.key)$" >/dev/null 2>&1; then
    echo -e "  [${RED}✗${NC}] Sensitive credential files detected in git index! Remove immediately."
    FAILURES=$((FAILURES + 1))
else
    echo -e "  [${GREEN}✓${NC}] No credentials or .dev.vars tracked in git"
fi

# Check that R2 or paid Cloudflare services are not configured in wrangler.toml
if grep -Ei "r2_buckets|analytics_engine|vectorize" apps/api/wrangler.toml 2>/dev/null | grep -v "#" >/dev/null 2>&1; then
    echo -e "  [${RED}✗${NC}] Paid or potentially non-free Cloudflare features detected in wrangler.toml!"
    FAILURES=$((FAILURES + 1))
else
    echo -e "  [${GREEN}✓${NC}] Cloudflare configuration strictly restricted to Free tier (Workers Free, D1, KV)"
fi

echo -e "\n${BLUE}======================================================${NC}"
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: All doctor checks passed! Ready for milestone execution.${NC}"
    exit 0
else
    echo -e "${RED}FAILED: $FAILURES check(s) failed. Resolve before continuing.${NC}"
    exit 1
fi
