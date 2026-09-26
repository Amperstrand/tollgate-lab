.PHONY: test test-unit test-fips test-tollgate test-cloud test-all lint install dev hooks

PYTHON ?= python3

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

hooks:
	git config core.hooksPath .githooks
	@echo "pre-commit lint gate enabled (mirror of CI lint-and-test)"

lint:
	ruff check tollgate_lab/
	ruff format --check tollgate_lab/

test: test-unit

test-unit:
	$(PYTHON) -m pytest tests/test_package.py tests/test_cloud.py tests/test_ssh.py \
		tests/test_router.py tests/test_hardware_lock.py tests/test_labgrid_drivers.py \
		tests/test_serial.py tests/test_deploy.py tests/test_strategy.py \
		tests/test_deploy_helpers.py -v

test-fips:
	ROUTER_SSH_HOST=$${ROUTER_SSH_HOST:-192.168.13.112} \
	$(PYTHON) -m pytest tests/test_fips_integration.py -v -m hardware

test-tollgate:
	ROUTER_SSH_HOST=$${ROUTER_SSH_HOST:-192.168.13.112} \
	$(PYTHON) -m pytest tests/test_tollgate_integration.py -v -m hardware

test-cloud:
	$(PYTHON) -m pytest tests/ -v -m "not hardware"

test-all: lint test-unit test-fips test-tollgate
	@echo "All tests complete"
