#!/bin/bash
# Test runner for AI DevOps
# Usage: ./scripts/test.sh [--coverage] [--watch] [--specific-test]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$BASE_DIR/.venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    cd "$BASE_DIR"
    python3 -m venv .venv
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -e .
    pip install pytest pytest-cov python-dotenv
else
    source "$VENV_DIR/bin/activate"
fi

cd "$BASE_DIR"

# Parse arguments
COVERAGE=false
WATCH=false
SPECIFIC_TEST=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --watch|-w)
            WATCH=true
            shift
            ;;
        --test|-t)
            SPECIFIC_TEST="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --coverage, -c    Run with coverage report"
            echo "  --watch, -w       Watch mode (re-run on changes)"
            echo "  --test, -t        Run specific test (e.g., tests/test_db.py::TestClass)"
            echo "  --help, -h        Show this help"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="python -m pytest tests/ -v"

if [ -n "$SPECIFIC_TEST" ]; then
    PYTEST_CMD="python -m pytest $SPECIFIC_TEST -v"
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=orchestrator/bin --cov-report=term-missing --cov-report=html:cov_html"
fi

if [ "$WATCH" = true ]; then
    pip install pytest-watch -q
    PYTEST_CMD="ptw -- $PYTEST_CMD"
fi

echo -e "${GREEN}Running tests...${NC}"
echo ""

eval $PYTEST_CMD

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo ""
    echo -e "${RED}✗ Some tests failed${NC}"
fi

if [ "$COVERAGE" = true ]; then
    echo ""
    echo -e "${YELLOW}Coverage report generated: cov_html/index.html${NC}"
    echo "Open in browser: open cov_html/index.html"
fi

exit $EXIT_CODE
