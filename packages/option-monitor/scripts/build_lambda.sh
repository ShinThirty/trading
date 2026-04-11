#!/bin/bash
# Build Lambda deployment package.
#
# Creates dist/lambda.zip containing option_monitor, trading_clients,
# and all dependencies (except boto3 which Lambda provides).
#
# Usage: bash packages/option-monitor/scripts/build_lambda.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$(dirname "$PKG_DIR")")"
BUILD_DIR="$PKG_DIR/.build"
OUTPUT="$PKG_DIR/dist/lambda.zip"

echo "==> Cleaning build directory"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$(dirname "$OUTPUT")"

echo "==> Installing dependencies"
uv pip install \
    --target "$BUILD_DIR" \
    --no-deps \
    "$PKG_DIR" \
    "$REPO_ROOT/packages/trading-clients"

# Install runtime deps (NOT boto3 — Lambda provides it)
# Use --python-platform linux to get Linux x86_64 binaries for Lambda
uv pip install \
    --target "$BUILD_DIR" \
    --python-platform linux \
    "httpx[http2]" \
    "pynacl>=1.5"

echo "==> Creating deployment package"
cd "$BUILD_DIR"
zip -qr "$OUTPUT" . -x "*.pyc" "*/__pycache__/*" "*.dist-info/*" "bin/*"

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "==> Built $OUTPUT ($SIZE)"
