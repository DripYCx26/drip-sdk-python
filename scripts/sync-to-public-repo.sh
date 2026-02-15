#!/bin/bash
# =============================================================================
# Sync Drip Python SDK to Public GitHub Repository
# =============================================================================
#
# This script syncs the SDK from the monorepo to the standalone public repo.
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated
#   - Git installed
#   - Write access to the public repo
#
# Usage:
#   ./scripts/sync-to-public-repo.sh [--push] [--create-release VERSION]
#
# Examples:
#   ./scripts/sync-to-public-repo.sh                    # Dry run - shows what would be synced
#   ./scripts/sync-to-public-repo.sh --push             # Sync and push to public repo
#   ./scripts/sync-to-public-repo.sh --create-release 1.1.0   # Sync, push, and create release
#
# =============================================================================

set -e

# Configuration
PUBLIC_REPO="MichaelLevin5908/drip-sdk-python"
PUBLIC_REPO_URL="https://github.com/$PUBLIC_REPO.git"
BRANCH="main"

# Files to sync (directories and files)
SYNC_DIRS=(
    "src"
    ".github"
)

SYNC_FILES=(
    "pyproject.toml"
    "README.md"
    "FULL_SDK.md"
    "LICENSE"
    "CONTRIBUTING.md"
)

# Parse arguments
PUSH=false
CREATE_RELEASE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        --create-release)
            CREATE_RELEASE="$2"
            PUSH=true
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--push] [--create-release VERSION]"
            echo ""
            echo "Options:"
            echo "  --push              Push changes to public repo"
            echo "  --create-release    Create a GitHub release (implies --push)"
            echo "  -h, --help          Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(dirname "$SCRIPT_DIR")"
TEMP_DIR=$(mktemp -d)

echo "========================================"
echo "Drip Python SDK - Sync to Public Repo"
echo "========================================"
echo ""
echo "Source:      $SDK_DIR"
echo "Target repo: $PUBLIC_REPO"
echo "Push:        $PUSH"
if [[ -n "$CREATE_RELEASE" ]]; then
    echo "Release:     v$CREATE_RELEASE"
fi
echo ""

# Check prerequisites
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed."
    echo "Install from: https://cli.github.com/"
    exit 1
fi

if ! gh auth status &> /dev/null; then
    echo "Error: GitHub CLI is not authenticated."
    echo "Run: gh auth login"
    exit 1
fi

# Run tests before syncing
echo "Step 1: Running tests..."
cd "$SDK_DIR"
if command -v pytest &> /dev/null; then
    if ! pytest -x -q 2>/dev/null; then
        echo "Warning: Tests failed"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    echo "Warning: pytest not available, skipping tests"
fi

# Clone the public repo
echo ""
echo "Step 2: Cloning public repo..."
git clone "$PUBLIC_REPO_URL" "$TEMP_DIR" --depth 1
cd "$TEMP_DIR"

# Remove old files (except .git and .github)
echo ""
echo "Step 3: Removing old files..."
find . -maxdepth 1 ! -name '.git' ! -name '.github' ! -name '.' -exec rm -rf {} +

# Copy SDK files
echo ""
echo "Step 4: Copying SDK files..."

# Copy directories (excluding __tests__ directories and test files)
for dir in "${SYNC_DIRS[@]}"; do
    if [[ -d "$SDK_DIR/$dir" ]]; then
        echo "  Copying directory: $dir/"
        # Use rsync to exclude test directories and files
        if command -v rsync &> /dev/null; then
            rsync -a --exclude='__tests__' --exclude='test_*.py' --exclude='*_test.py' --exclude='__pycache__' "$SDK_DIR/$dir/" "$TEMP_DIR/$dir/"
        else
            # Fallback: copy then remove test files
            cp -r "$SDK_DIR/$dir" "$TEMP_DIR/"
            find "$TEMP_DIR/$dir" -type d -name '__tests__' -exec rm -rf {} + 2>/dev/null || true
            find "$TEMP_DIR/$dir" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
            find "$TEMP_DIR/$dir" -type f -name 'test_*.py' -delete 2>/dev/null || true
            find "$TEMP_DIR/$dir" -type f -name '*_test.py' -delete 2>/dev/null || true
        fi
    else
        echo "  Skipping missing directory: $dir/"
    fi
done

# Copy files
for file in "${SYNC_FILES[@]}"; do
    if [[ -f "$SDK_DIR/$file" ]]; then
        echo "  Copying file: $file"
        cp "$SDK_DIR/$file" "$TEMP_DIR/"
    else
        echo "  Skipping missing file: $file"
    fi
done

# Create .gitignore
cat > "$TEMP_DIR/.gitignore" << 'EOF'
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
.env
.venv
env/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.DS_Store
EOF

# Show what changed
echo ""
echo "Step 5: Changes to be synced..."
git add -A
git status

if [[ "$PUSH" == "false" ]]; then
    echo ""
    echo "========================================"
    echo "DRY RUN COMPLETE"
    echo "========================================"
    echo ""
    echo "To push changes, run:"
    echo "  $0 --push"
    echo ""
    echo "To create a release, run:"
    echo "  $0 --create-release 1.1.0"
    echo ""
    echo "Temp directory: $TEMP_DIR"
    exit 0
fi

# Check if there are changes
if git diff --cached --quiet; then
    echo ""
    echo "No changes to sync."
    rm -rf "$TEMP_DIR"
    exit 0
fi

# Commit and push
echo ""
echo "Step 6: Committing changes..."
VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])" 2>/dev/null || echo "unknown")
git commit -m "chore: sync from monorepo (v$VERSION)

Synced from drip monorepo sdk-python"

echo ""
echo "Step 7: Pushing to $PUBLIC_REPO..."
git push origin "$BRANCH"

echo ""
echo "========================================"
echo "SYNC COMPLETE"
echo "========================================"
echo ""
echo "Changes pushed to: https://github.com/$PUBLIC_REPO"

# Create release if requested
if [[ -n "$CREATE_RELEASE" ]]; then
    echo ""
    echo "Step 8: Creating GitHub release v$CREATE_RELEASE..."
    gh release create "v$CREATE_RELEASE" \
        --repo "$PUBLIC_REPO" \
        --title "v$CREATE_RELEASE" \
        --notes "Release v$CREATE_RELEASE

## Installation
\`\`\`bash
pip install drip-sdk==$CREATE_RELEASE
\`\`\`"

    echo ""
    echo "Release created! This will trigger the PyPI publish workflow."
    echo "View at: https://github.com/$PUBLIC_REPO/releases/tag/v$CREATE_RELEASE"
fi

# Cleanup
rm -rf "$TEMP_DIR"
