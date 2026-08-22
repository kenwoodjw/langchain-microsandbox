.PHONY: benchmark build check dist-check format help integration_smoke integration_test integration_tests lint test tests test_watch type typecheck

.DEFAULT_GOAL := help

.EXPORT_ALL_VARIABLES:
UV_FROZEN = true

######################
# TESTING
######################

TEST_FILE ?= tests/unit_tests/
PYTEST_EXTRA ?=

integration_test integration_tests: TEST_FILE=tests/integration_tests/

test: ## Run unit tests
test tests:
	uv run --group test pytest -vvv $(PYTEST_EXTRA) --disable-socket --allow-unix-socket $(TEST_FILE)

integration_test: ## Run integration tests
integration_test integration_tests:
	uv run --group test pytest -vvv --timeout 30 $(PYTEST_EXTRA) $(TEST_FILE)

integration_smoke: ## Run real microVM command and file-transfer smoke tests
	uv run --group test pytest -vv --timeout 60 \
		tests/integration_tests/test_integration.py::TestMicrosandboxSandboxStandard::test_execute_large_stdout_payload \
		tests/integration_tests/test_integration.py::TestMicrosandboxSandboxStandard::test_aexecute_large_stdout_payload \
		tests/integration_tests/test_integration.py::TestMicrosandboxSandboxStandard::test_aexecute_timeout_maps_to_exit_124 \
		tests/integration_tests/test_integration.py::TestMicrosandboxSandboxStandard::test_upload_download_roundtrip

test_watch: ## Run tests in watch mode
	uv run --group test ptw --now . -- -vv $(TEST_FILE)

benchmark: ## Run benchmark tests
	uv run --group test pytest ./tests -m benchmark

build: ## Build source and wheel distributions
	uv build

dist-check: build ## Validate built distribution metadata
	uvx twine check dist/*

check: lint test dist-check ## Run local lint, unit, and distribution checks

######################
# LINTING AND FORMATTING
######################

lint: ## Run linters and type checker
	uv run --all-groups ruff check .
	uv run --all-groups ruff format . --diff
	$(MAKE) type

type: ## Run type checker
type typecheck:
	uv run --all-groups ty check langchain_microsandbox

format: ## Run code formatters
	uv run --all-groups ruff format .
	uv run --all-groups ruff check --fix .

######################
# HELP
######################

help: ## Show this help message
	@echo "Usage: make [target] [TEST_FILE=path/to/tests/]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
