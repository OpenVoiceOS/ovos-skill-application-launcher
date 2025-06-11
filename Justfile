set shell := ["bash", "-c"]

# Justfile for skill-mac-application-launcher
# Run `just --list` to see all available commands

# Default recipe - show available commands
default:
    @just --list

# Install development dependencies
install:
    uv sync --group dev

# Format code with ruff
format:
    uv run ruff format .
    uv run ruff check --fix .

# Lint code with ruff
lint:
    uv run ruff check .

# Run tests with pytest
test:
    uv run pytest

# Run tests with coverage report
test-cov:
    uv run pytest --cov=skill_mac_application_launcher --cov-report=html --cov-report=term-missing

# Run tests in verbose mode
test-verbose:
    uv run pytest -v

# Run all quality checks (format, lint, test)
check: format lint test

# Build the package
build:
    uv build

# Clean build artifacts and cache files
clean:
    rm -rf build/
    rm -rf dist/
    rm -rf *.egg-info/
    rm -rf .pytest_cache/
    rm -rf __pycache__/
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    rm -rf .coverage
    rm -rf htmlcov/

# Install the package in development mode
dev-install:
    uv pip install -e .

# Run a specific test file
test-file FILE:
    uv run pytest {{FILE}}

# Run tests matching a pattern
test-match PATTERN:
    uv run pytest -k "{{PATTERN}}"

# Check for security vulnerabilities (if you want to add this later)
# security:
#     uv run safety check

# Pre-commit hook simulation - run before committing
pre-commit: format lint test

# Show project info
info:
    @echo "Project: skill-mac-application-launcher"
    @echo "Python version requirement: >=3.9"
    @echo "Main package: skill_mac_application_launcher"
    @echo ""
    @echo "Available commands:"
    @just --list 