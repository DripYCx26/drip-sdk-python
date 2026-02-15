# Releasing the Drip Python SDK

This guide covers how to release the Python SDK to PyPI.

## Architecture

The SDK lives in two places:
1. **Monorepo** (`sdk-python/`) - Development happens here
2. **Public repo** (`https://github.com/MichaelLevin5908/drip-sdk-python`) - Published to PyPI from here

## SDK Structure: Core vs Full

The SDK has two import paths for different use cases:

| Import | Use Case |
|--------|----------|
| `from drip.core import Drip` | Lightweight: `track_usage()`, `record_run()` only |
| `from drip import Drip` | Everything: billing, webhooks, cost estimation |

### Core SDK (`src/drip/core.py`)

Minimal API for pilots and new integrations:

```python
from drip.core import Drip, AsyncDrip

client = Drip(api_key="sk_test_...")

# Track usage (no billing)
client.track_usage(
    customer_id="cust_123",
    meter="api_calls",
    quantity=1
)

# Record execution with events
result = client.record_run(
    customer_id="cust_123",
    workflow="rpc-request",
    events=[{"eventType": "eth_call", "quantity": 1}],
    status="COMPLETED"
)
print(result.summary)
```

Async version:

```python
from drip.core import AsyncDrip

async with AsyncDrip(api_key="sk_test_...") as client:
    await client.track_usage(
        customer_id="cust_123",
        meter="api_calls",
        quantity=1
    )
```

### Full SDK (`src/drip/client.py`)

Complete feature set:

```python
from drip import Drip

client = Drip(api_key="sk_test_...")

# Billing
result = client.charge(customer_id=customer_id, meter=meter, quantity=quantity)

# Webhooks
webhook = client.create_webhook(url=url, events=events)

# Cost estimation
estimate = client.estimate_cost(items=items)
```

### Framework Integrations

| Integration | Import | Purpose |
|-------------|--------|---------|
| FastAPI | `from drip.middleware.fastapi import DripMiddleware` | FastAPI middleware |
| Flask | `from drip.middleware.flask import drip_middleware` | Flask decorator |
| LangChain | `from drip.integrations.langchain import DripCallbackHandler` | LangChain callbacks |

## Quick Release

```bash
# 1. Make changes in sdk-python/
# 2. Test locally
cd sdk-python
pytest
mypy src
ruff check src

# 3. Bump version in pyproject.toml
# Edit pyproject.toml: version = "1.0.2"

# 4. Commit changes to monorepo
git add sdk-python
git commit -m "feat(sdk-python): add new feature"
git push

# 5. Sync and release to public repo
./scripts/sync-to-public-repo.sh --create-release 1.0.2
```

## Sync Script Details

The sync script (`scripts/sync-to-public-repo.sh`) automates the release process:

### What It Does

1. **Runs tests** in monorepo to verify code works
2. **Clones** the public repo (shallow clone)
3. **Removes** old files (keeps `.git` directory)
4. **Copies** SDK files:
   - `src/` - Source files (excluding `__tests__/`, `test_*.py`, `*_test.py`, `__pycache__/`)
   - `pyproject.toml` - Package metadata
   - `README.md`, `LICENSE`, `CONTRIBUTING.md`
   - `.github/` - CI workflows
5. **Excludes** test files (kept in monorepo only):
   - `__tests__/` directories
   - `test_*.py` and `*_test.py` files
   - `__pycache__/` directories
6. **Creates** `.gitignore`
7. **Commits and pushes** changes
8. **Creates GitHub release** (triggers PyPI publish via trusted publishing)

### Usage

```bash
cd sdk-python

# Dry run - preview changes without pushing
./scripts/sync-to-public-repo.sh

# Sync and push (no release)
./scripts/sync-to-public-repo.sh --push

# Sync, push, and create release (triggers PyPI publish)
./scripts/sync-to-public-repo.sh --create-release 1.0.2
```

### Files Synced

```
src/drip/
├── __init__.py      # Full SDK exports
├── client.py        # Full Drip & AsyncDrip classes
├── core.py          # Core Drip & AsyncDrip classes (lightweight)
├── models.py        # Data models
├── errors.py        # Exception classes
├── resilience.py    # Retry, circuit breaker, rate limiter
├── stream.py        # StreamMeter for batching
├── utils.py         # Utility functions
├── middleware/      # Framework middleware
│   ├── fastapi.py
│   └── flask.py
└── integrations/    # Third-party integrations
    └── langchain.py
```

## Detailed Workflow

### Step 1: Make Changes

Develop in the monorepo `sdk-python/`:

```bash
cd sdk-python

# Make your changes...

# Test
pytest

# Type check
mypy src

# Lint
ruff check src tests
```

### Step 2: Update Version

Edit `pyproject.toml`:

```toml
[project]
version = "1.0.2"
```

Follow [Semantic Versioning](https://semver.org/):
- **MAJOR** (1.0.0 -> 2.0.0): Breaking API changes
- **MINOR** (1.0.0 -> 1.1.0): New features, backwards compatible
- **PATCH** (1.0.0 -> 1.0.1): Bug fixes, backwards compatible

### Step 3: Commit to Monorepo

```bash
git add sdk-python
git commit -m "feat(sdk-python): description of changes"
git push
```

### Step 4: Sync to Public Repo

```bash
cd sdk-python

# Dry run - see what would change
./scripts/sync-to-public-repo.sh

# Push changes only
./scripts/sync-to-public-repo.sh --push

# Push and create a release (triggers PyPI publish)
./scripts/sync-to-public-repo.sh --create-release 1.0.2
```

### Step 5: Verify Release

1. Check GitHub Actions: https://github.com/MichaelLevin5908/drip-sdk-python/actions
2. Check PyPI: https://pypi.org/project/drip-sdk/

## Manual Release (Alternative)

If the sync script doesn't work:

```bash
# Clone public repo
git clone https://github.com/MichaelLevin5908/drip-sdk-python.git
cd drip-sdk-python

# Copy files from monorepo
cp -r ../drip/sdk-python/src .
cp -r ../drip/sdk-python/tests .
cp ../drip/sdk-python/pyproject.toml .
cp ../drip/sdk-python/README.md .
cp ../drip/sdk-python/LICENSE .

# Remove internal-only test files
rm -f tests/test_integration_complex.py
rm -f tests/test_limit.py
rm -f tests/test_stress.py

# Commit and push
git add .
git commit -m "chore: sync from monorepo"
git push

# Create release (triggers PyPI publish)
gh release create v1.0.2 --title "v1.0.2" --notes "Release notes"
```

## First-Time Setup

### PyPI Trusted Publishing (Recommended)

Configure trusted publishing (no API tokens needed):

1. Go to https://pypi.org/manage/project/drip-sdk/settings/publishing/
2. Add a new publisher:
   - Owner: `MichaelLevin5908`
   - Repository: `drip-sdk-python`
   - Workflow: `publish.yml`
   - Environment: (leave blank)

### API Token (Alternative)

```bash
# Generate token at https://pypi.org/manage/account/token/
gh secret set PYPI_API_TOKEN --repo MichaelLevin5908/drip-sdk-python
```

## Pre-release Checklist

Before releasing:

- [ ] All tests pass: `pytest`
- [ ] Type checking passes: `mypy src`
- [ ] Linting passes: `ruff check src tests`
- [ ] Version updated in `pyproject.toml`
- [ ] README is current
- [ ] Breaking changes documented

## Testing the Package

```bash
# Install from TestPyPI (for testing)
pip install --index-url https://test.pypi.org/simple/ drip-sdk

# Install from PyPI
pip install drip-sdk

# Verify installation
python -c "from drip import Drip; print('Full SDK OK')"
python -c "from drip.core import Drip, AsyncDrip; print('Core SDK OK')"
```

## Troubleshooting

### PyPI publish fails

- Check trusted publishing is configured correctly
- Verify the workflow name matches exactly: `publish.yml`
- Check GitHub Actions logs for specific errors

### Sync script fails

- Ensure `gh` CLI is authenticated: `gh auth status`
- Check you have push access to public repo
- Try manual sync (see above)

### Tests fail in CI

- Run tests locally first: `pytest`
- Check Python version matches CI (3.10, 3.11, 3.12)
- Ensure all dependencies are in `pyproject.toml`
