#!/bin/bash
# Build Lambda deployment package.
#
# Creates dist/lambda.zip containing trading_alerts, trading_clients,
# and all dependencies (except boto3 which Lambda provides).
#
# Usage: bash packages/trading-alerts/scripts/build_lambda.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$(dirname "$PKG_DIR")")"
BUILD_DIR="$PKG_DIR/.build"
OUTPUT="$PKG_DIR/dist/lambda.zip"
HASH_FILE="$PKG_DIR/dist/lambda.zip.hash"

# Compute a fingerprint of all source inputs that affect the zip.
compute_hash() {
    {
        find \
            "$REPO_ROOT/packages/trading-alerts/src" \
            "$REPO_ROOT/packages/trading-clients/src" \
            -type f -name '*.py' | sort | xargs sha256sum
        sha256sum \
            "$REPO_ROOT/packages/trading-alerts/pyproject.toml" \
            "$REPO_ROOT/packages/trading-clients/pyproject.toml" \
            "$REPO_ROOT/uv.lock" \
            "$SCRIPT_DIR/build_lambda.sh"
    } | sha256sum | cut -d' ' -f1
}

mkdir -p "$(dirname "$OUTPUT")"

CURRENT_HASH="$(compute_hash)"
if [ -f "$OUTPUT" ] && [ -f "$HASH_FILE" ] && [ "$(cat "$HASH_FILE")" = "$CURRENT_HASH" ]; then
    SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo "==> No changes detected — skipping rebuild ($OUTPUT $SIZE)"
    exit 0
fi

echo "==> Cleaning build directory"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

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
    "pynacl>=1.5" \
    "openpyxl"

echo "==> Creating deployment package"
cd "$BUILD_DIR"
zip -qr "$OUTPUT" . -x "*.pyc" "*/__pycache__/*" "*.dist-info/*" "bin/*"

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "$CURRENT_HASH" > "$HASH_FILE"
echo "==> Built $OUTPUT ($SIZE)"
