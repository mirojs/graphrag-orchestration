#!/bin/bash
# Sync upstream azure-search-openai-demo and report conflicts
#
# Usage: ./scripts/sync_upstream.sh [--dry-run]
#
# This script:
# 1. Fetches latest from upstream repository
# 2. Attempts to merge/pull changes
# 3. Reports conflicts with our customizations

set -e

UPSTREAM_REPO="https://github.com/Azure-Samples/azure-search-openai-demo.git"
UPSTREAM_BRANCH="main"
FRONTEND_DIR="frontend"
DRY_RUN=false

# Parse arguments
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "🔍 DRY RUN MODE - No changes will be made"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "Upstream Sync: azure-search-openai-demo"
echo "======================================"
echo ""

# Check if we're in the right directory
if [[ ! -d "$FRONTEND_DIR" ]]; then
    echo -e "${RED}Error: frontend/ directory not found${NC}"
    echo "Run this script from the repository root"
    exit 1
fi

# Files we've customized (check these for conflicts)
CUSTOMIZED_FILES=(
    "app/backend/config.py"
    "app/frontend/src/api/models.ts"
    "app/frontend/src/components/Settings/"
    "app/frontend/src/pages/chat/"
)

echo "📋 Checking for upstream updates..."
echo ""

# Fetch upstream to compare
UPSTREAM_HEAD=$(git ls-remote "$UPSTREAM_REPO" HEAD | cut -f1)
echo "Upstream HEAD: ${UPSTREAM_HEAD:0:12}"

# Read current tracked version
if [[ -f "$FRONTEND_DIR/UPSTREAM_VERSION.md" ]]; then
    CURRENT_BASE=$(grep "Current Base:" "$FRONTEND_DIR/UPSTREAM_VERSION.md" | head -1)
    echo "Current tracking: $CURRENT_BASE"
else
    echo -e "${YELLOW}Warning: UPSTREAM_VERSION.md not found${NC}"
fi

echo ""
echo "======================================"
echo "Conflict Detection"
echo "======================================"
echo ""

# Check if subtree is set up
if git remote | grep -q "upstream-frontend"; then
    echo "✓ Upstream remote configured"
else
    echo -e "${YELLOW}⚠ Upstream remote not configured${NC}"
    echo "  To set up: git remote add upstream-frontend $UPSTREAM_REPO"
    
    if [[ "$DRY_RUN" == false ]]; then
        read -p "Add upstream remote now? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            git remote add upstream-frontend "$UPSTREAM_REPO"
            echo "✓ Added upstream-frontend remote"
        fi
    fi
fi

echo ""
echo "Checking customized files for potential conflicts:"
echo ""

for file_pattern in "${CUSTOMIZED_FILES[@]}"; do
    full_path="$FRONTEND_DIR/$file_pattern"
    
    if [[ -e "$full_path" ]]; then
        # Check if file/dir exists
        if [[ -d "$full_path" ]]; then
            file_count=$(find "$full_path" -type f | wc -l)
            echo -e "  📁 ${YELLOW}$file_pattern${NC} ($file_count files) - CUSTOMIZED"
        else
            echo -e "  📄 ${YELLOW}$file_pattern${NC} - CUSTOMIZED"
        fi
    else
        echo -e "  ❓ $file_pattern - Not found (may have been removed upstream)"
    fi
done

echo ""
echo "======================================"
echo "Sync Actions"
echo "======================================"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo "DRY RUN - Would perform these actions:"
    echo "  1. git subtree pull --prefix=frontend upstream main --squash"
    echo "  2. Review and resolve conflicts in customized files"
    echo "  3. Update UPSTREAM_VERSION.md with new commit"
    echo ""
    echo "Run without --dry-run to execute"
else
    echo "To sync upstream changes:"
    echo ""
    echo "  # Using subtree (recommended):"
    echo "  git subtree pull --prefix=frontend \\"
    echo "    $UPSTREAM_REPO \\"
    echo "    $UPSTREAM_BRANCH --squash"
    echo ""
    echo "  # Or manually:"
    echo "  1. Clone upstream to temp dir"
    echo "  2. Compare changed files"
    echo "  3. Manually merge changes"
    echo "  4. Update UPSTREAM_VERSION.md"
    echo ""
    
    read -p "Attempt subtree pull now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Pulling from upstream..."
        
        if git subtree pull --prefix="$FRONTEND_DIR" "$UPSTREAM_REPO" "$UPSTREAM_BRANCH" --squash; then
            echo -e "${GREEN}✓ Subtree pull successful${NC}"
            
            # Update UPSTREAM_VERSION.md
            TODAY=$(date +%Y-%m-%d)
            sed -i "s/Last Sync:.*/Last Sync: $TODAY/" "$FRONTEND_DIR/UPSTREAM_VERSION.md"
            sed -i "s/Current Base:.*/Current Base: ${UPSTREAM_HEAD:0:12} ($TODAY)/" "$FRONTEND_DIR/UPSTREAM_VERSION.md"
            
            echo "✓ Updated UPSTREAM_VERSION.md"
        else
            echo -e "${RED}✗ Subtree pull failed - resolve conflicts manually${NC}"
            exit 1
        fi
    fi
fi

echo ""
echo "======================================"
echo "Done"
echo "======================================"
