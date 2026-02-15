#!/bin/bash
# =============================================================================
# Setup Standalone GitHub Repository for Drip Python SDK
# =============================================================================
#
# This script extracts the Python SDK into a standalone public repository.
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated
#   - Git installed
#
# Usage:
#   ./scripts/setup-standalone-repo.sh [org-name] [repo-name]
#
# Example:
#   ./scripts/setup-standalone-repo.sh drip-billing drip-sdk-python
#
# =============================================================================

set -e

# Configuration
ORG_NAME="${1:-drip-billing}"
REPO_NAME="${2:-drip-sdk-python}"
FULL_REPO="$ORG_NAME/$REPO_NAME"

echo "========================================"
echo "Drip Python SDK - Standalone Repo Setup"
echo "========================================"
echo ""
echo "Organization: $ORG_NAME"
echo "Repository:   $REPO_NAME"
echo "Full path:    $FULL_REPO"
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

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(dirname "$SCRIPT_DIR")"
TEMP_DIR=$(mktemp -d)

echo "Step 1: Creating temporary directory..."
echo "  -> $TEMP_DIR"

# Copy SDK files to temp directory
echo ""
echo "Step 2: Copying SDK files..."
cp -r "$SDK_DIR"/* "$TEMP_DIR/"
cp "$SDK_DIR/.gitignore" "$TEMP_DIR/" 2>/dev/null || true

# Remove monorepo-specific files if they exist
rm -rf "$TEMP_DIR/scripts/setup-standalone-repo.sh"

# Update workflow paths for standalone repo
echo ""
echo "Step 3: Updating workflow paths for standalone repo..."

# Create standalone CI workflow
cat > "$TEMP_DIR/.github/workflows/ci.yml" << 'EOF'
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,all]"

      - name: Run ruff linting
        run: ruff check src tests

      - name: Run ruff formatting check
        run: ruff format --check src tests

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,all]"

      - name: Run mypy
        run: mypy src

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,all]"

      - name: Run tests with coverage
        run: pytest --cov=drip --cov-report=term-missing --cov-report=xml

      - name: Upload coverage
        if: matrix.python-version == '3.12'
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
          flags: python-sdk
          fail_ci_if_error: false
EOF

# Create standalone publish workflow
cat > "$TEMP_DIR/.github/workflows/publish.yml" << 'EOF'
name: Publish to PyPI

on:
  release:
    types: [published]
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,all]"

      - name: Run linting
        run: ruff check src tests

      - name: Run type checking
        run: mypy src

      - name: Run tests
        run: pytest --cov=drip --cov-report=term-missing

  publish:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build dependencies
        run: |
          python -m pip install --upgrade pip
          pip install build twine

      - name: Build package
        run: python -m build

      - name: Check package
        run: twine check dist/*

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          verbose: true
EOF

# Initialize git repo
echo ""
echo "Step 4: Initializing git repository..."
cd "$TEMP_DIR"
git init
git add .
git commit -m "Initial commit: Drip Python SDK v1.0.0

Features:
- Core API client (Drip, AsyncDrip)
- StreamMeter for LLM token streaming
- FastAPI middleware
- Flask decorator
- LangChain integration
- Webhook verification
- Full type safety with Pydantic"

# Create GitHub repository
echo ""
echo "Step 5: Creating GitHub repository..."
echo ""
read -p "Create public repo $FULL_REPO? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    gh repo create "$FULL_REPO" --public --source=. --push --description "Official Python SDK for Drip - usage-based billing with on-chain settlement"

    echo ""
    echo "========================================"
    echo "SUCCESS!"
    echo "========================================"
    echo ""
    echo "Repository created: https://github.com/$FULL_REPO"
    echo ""
    echo "Next steps:"
    echo "  1. Configure PyPI trusted publishing:"
    echo "     https://pypi.org/manage/project/drip-sdk/settings/publishing/"
    echo ""
    echo "  2. Add repository secrets (if not using trusted publishing):"
    echo "     gh secret set PYPI_API_TOKEN --repo $FULL_REPO"
    echo ""
    echo "  3. Create a release to publish to PyPI:"
    echo "     gh release create v1.0.0 --repo $FULL_REPO --title 'v1.0.0' --notes 'Initial release'"
    echo ""
else
    echo ""
    echo "Repository not created. Files are ready at:"
    echo "  $TEMP_DIR"
    echo ""
    echo "To push manually:"
    echo "  cd $TEMP_DIR"
    echo "  gh repo create $FULL_REPO --public --source=. --push"
fi
