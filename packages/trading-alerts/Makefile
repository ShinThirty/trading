# Option Monitor — deployment automation
#
# Prerequisites:
#   - AWS CLI authenticated (aws login)
#   - Discord app created, bot_token/channel_id in ~/.tradingrc [discord]
#
# Quick start:
#   make deploy        # build + terraform apply + populate credentials
#   make test          # invoke Lambda manually
#   make destroy       # tear down all AWS resources

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

.PHONY: build deploy destroy credentials credentials-delete register-commands test test-local init clean

## Build Lambda deployment ZIP
build:
	@bash $(PKG_DIR)/scripts/build_lambda.sh

## Initialize Terraform (first time only)
init:
	@cd $(TF_DIR) && terraform init

## Build + deploy all AWS resources
deploy: build init
	@cd $(TF_DIR) && terraform apply -var="discord_public_key=$(DISCORD_PUBLIC_KEY)"

## Populate SSM credentials from ~/.tradingrc
credentials:
	@python3 -c "\
	import configparser, json; \
	c = configparser.ConfigParser(); c.read('$(HOME)/.tradingrc'); \
	print(json.dumps({ \
	  'webull_app_key': c['webull']['app_key'], \
	  'webull_app_secret': c['webull']['app_secret'], \
	  'webull_token': c['webull']['token'], \
	  'tradier_api_token': c['tradier']['api_token'], \
	  'tradier_sandbox': c['tradier'].get('sandbox', 'false'), \
	  'discord_bot_token': c['discord']['bot_token'], \
	  'discord_channel_id': c['discord']['channel_id'], \
	}))" | \
	aws ssm put-parameter \
	  --name /option-monitor/credentials \
	  --type SecureString \
	  --overwrite \
	  --value file:///dev/stdin
	@echo "==> SSM credentials updated"

## Register Discord slash commands (/unmute, /muted)
register-commands:
	@DISCORD_APP_ID=$(DISCORD_APP_ID) DISCORD_BOT_TOKEN=$(DISCORD_BOT_TOKEN) \
	  uv run python $(PKG_DIR)/scripts/register_commands.py

## Invoke monitor Lambda manually (test in AWS)
test:
	@aws lambda invoke \
	  --function-name option-monitor \
	  --payload '{}' \
	  --cli-binary-format raw-in-base64-out \
	  /tmp/option-monitor-out.json > /dev/null 2>&1
	@cat /tmp/option-monitor-out.json | python3 -m json.tool

## Test locally without AWS
test-local:
	@uv run python $(PKG_DIR)/scripts/invoke_local.py --skip-clock

## Destroy all AWS resources
destroy:
	@cd $(TF_DIR) && terraform destroy -var="discord_public_key=$(DISCORD_PUBLIC_KEY)"

## Delete SSM credentials
credentials-delete:
	@aws ssm delete-parameter --name /option-monitor/credentials
	@echo "==> SSM credentials deleted"

## Remove build artifacts
clean:
	@rm -rf $(PKG_DIR)/.build $(DIST_DIR)
	@echo "==> Cleaned build artifacts"
