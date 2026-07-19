# trading-alerts — deployment automation
#
# Prerequisites:
#   - AWS CLI authenticated (aws login)
#   - Discord app created, bot_token / channel_id / public_key /
#     application_id in ~/.tradingrc [discord]
#
# Quick start:
#   make deploy             # build + terraform apply
#   make credentials        # populate SSM with Discord bot creds
#   make register-commands  # register /unmute and /muted with Discord
#   make test TRIGGER=naaim # invoke dispatcher Lambda with a specific watcher
#   make test-local         # run a watcher locally (no AWS); --list by default
#   make destroy            # tear down all AWS resources

SHELL := /bin/bash
.ONESHELL:

PKG_DIR   := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)
REPO_ROOT := $(shell cd "$(PKG_DIR)/../.." && pwd)
TF_DIR    := $(PKG_DIR)/terraform
DIST_DIR  := $(PKG_DIR)/dist

# Read Discord config from ~/.tradingrc
READ_RC           = import configparser; c=configparser.ConfigParser(); c.read('$(HOME)/.tradingrc')
DISCORD_PUBLIC_KEY := $(shell python3 -c "$(READ_RC); print(c['discord']['public_key'])" 2>/dev/null)
DISCORD_APP_ID     := $(shell python3 -c "$(READ_RC); print(c['discord']['application_id'])" 2>/dev/null)
DISCORD_BOT_TOKEN  := $(shell python3 -c "$(READ_RC); print(c['discord']['bot_token'])" 2>/dev/null)

# AWS credentials: uses "personal" profile with credential_process bridge to aws login
export AWS_PROFILE := personal

# Dispatcher Lambda + smoke-test artifacts
DISPATCHER := trading-alerts-dispatcher
SMOKE_OUT  := /tmp/trading-alerts-smoke.json

.PHONY: build deploy destroy credentials credentials-delete register-commands test test-local smoke init clean

## Build Lambda deployment ZIP
build:
	@bash $(PKG_DIR)/scripts/build_lambda.sh

## Initialize Terraform (first time only)
init:
	@cd $(TF_DIR) && terraform init

## Build + deploy all AWS resources, then smoke-test the dispatcher
deploy: build init
	@set -e
	cd $(TF_DIR) && terraform apply -var="discord_public_key=$(DISCORD_PUBLIC_KEY)"
	$(MAKE) -C $(PKG_DIR) smoke

## Populate SSM credentials from ~/.tradingrc
credentials:
	@python3 $(PKG_DIR)/scripts/build_credentials.py | \
	aws ssm put-parameter \
	  --name /trading-alerts/credentials \
	  --type SecureString \
	  --overwrite \
	  --value file:///dev/stdin
	@echo "==> SSM credentials updated"

## Register Discord slash commands (/unmute, /muted)
register-commands:
	@DISCORD_APP_ID=$(DISCORD_APP_ID) DISCORD_BOT_TOKEN=$(DISCORD_BOT_TOKEN) \
	  uv run python $(PKG_DIR)/scripts/register_commands.py

## Invoke dispatcher Lambda with a specific watcher trigger (TRIGGER=naaim|gex|...)
test:
	@if [ -z "$(TRIGGER)" ]; then echo "Usage: make test TRIGGER=naaim"; exit 1; fi
	@aws lambda invoke \
	  --function-name trading-alerts-dispatcher \
	  --payload "$$(printf '{"trigger":"%s"}' $(TRIGGER))" \
	  --cli-binary-format raw-in-base64-out \
	  /tmp/trading-alerts-out.json > /dev/null 2>&1
	@cat /tmp/trading-alerts-out.json | python3 -m json.tool

## Test locally without AWS — defaults to --list; pass TRIGGER=name to actually run a watcher
test-local:
	@uv run python $(PKG_DIR)/scripts/invoke_local.py $(if $(TRIGGER),--trigger $(TRIGGER),--list)

## Post-deploy smoke test — fail if the dispatcher can't import + dispatch.
## Runs automatically at the end of `deploy`; also runnable standalone.
## A bogus trigger is used on purpose: the handler returns its "unknown trigger"
## payload *before* loading config/DynamoDB, so no watcher runs and nothing posts
## to Discord — yet the whole module (all 18 watchers) must still IMPORT, which is
## exactly the Runtime.ImportModuleError failure that silently took the fleet down
## (2026-07-08). Asserts FunctionError is null and the expected payload came back.
smoke:
	@set -e
	aws lambda wait function-updated --function-name $(DISPATCHER)
	echo "==> Smoke-testing $(DISPATCHER) (import + handler dispatch)"
	FUNC_ERR=$$(aws lambda invoke \
	  --function-name $(DISPATCHER) \
	  --payload '{"trigger":"__smoke__"}' \
	  --cli-binary-format raw-in-base64-out \
	  --query 'FunctionError' --output text \
	  $(SMOKE_OUT))
	if [ "$$FUNC_ERR" != "None" ]; then
	  echo "!! SMOKE FAILED — dispatcher raised (FunctionError=$$FUNC_ERR):"
	  python3 -m json.tool $(SMOKE_OUT) 2>/dev/null || cat $(SMOKE_OUT)
	  exit 1
	fi
	if ! python3 -c "import json,sys; d=json.load(open('$(SMOKE_OUT)')); sys.exit(0 if isinstance(d,dict) and 'available' in d else 1)"; then
	  echo "!! SMOKE FAILED — unexpected dispatcher response:"
	  python3 -m json.tool $(SMOKE_OUT) 2>/dev/null || cat $(SMOKE_OUT)
	  exit 1
	fi
	echo "==> SMOKE PASSED — dispatcher imports + dispatches cleanly (no watcher ran, no Discord post)"

## Destroy all AWS resources
destroy:
	@cd $(TF_DIR) && terraform destroy -var="discord_public_key=$(DISCORD_PUBLIC_KEY)"

## Delete SSM credentials
credentials-delete:
	@aws ssm delete-parameter --name /trading-alerts/credentials
	@echo "==> SSM credentials deleted"

## Remove build artifacts
clean:
	@rm -rf $(PKG_DIR)/.build $(DIST_DIR)
	@echo "==> Cleaned build artifacts"
