#!/usr/bin/env bash
# Clean stale Copilot sandbox runtime state.
# Run this when the terminal tool stops working (ENOPRO errors).
# After running, reload the VS Code window (Ctrl+Shift+P → Developer: Reload Window).

set -e

echo "Killing lingering sandbox processes..."
pkill -f sandbox-runtime 2>/dev/null || true

echo "Cleaning stale sandbox settings..."
rm -f /tmp/vscode-sandbox-settings-*.json

echo "Cleaning VS Code server cache..."
rm -rf /tmp/vscode-*

echo "Done. Reload the VS Code window now."
