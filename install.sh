#!/bin/bash
# Install MiMoCode usage tracking for the Omarchy agents panel.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
MIMO_BIN="$HOME/.mimocode/bin"
CONFIG_DIR="$HOME/.config/mimocode"
USAGE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage"

echo "Installing MiMoCode Usage for Omarchy..."

# Copy collector script
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/collect-usage.py" "$BIN_DIR/collect-mimocode-usage"
chmod +x "$BIN_DIR/collect-mimocode-usage"

# Copy helper command
cp "$SCRIPT_DIR/mimocode-usage" "$BIN_DIR/mimocode-usage"
chmod +x "$BIN_DIR/mimocode-usage"

# Create wrapper that hooks into the agents panel refresh
mkdir -p "$MIMO_BIN"
cat > "$MIMO_BIN/omarchy-agent-usage-update" <<'WRAPPER'
#!/bin/bash
# Runs original update + MiMoCode collector on panel refresh.
/usr/share/omarchy/bin/omarchy-agent-usage-update "$@"
USAGE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage"
COLLECTOR="$HOME/.local/bin/collect-mimocode-usage"
if [[ -x "$COLLECTOR" ]]; then
    tmp=$(mktemp "$USAGE_DIR/.mimocode.XXXXXX")
    if python3 "$COLLECTOR" >"$tmp" 2>/dev/null; then
        mv "$tmp" "$USAGE_DIR/mimocode.json"
    else
        rm -f "$tmp"
    fi
fi
WRAPPER
chmod +x "$MIMO_BIN/omarchy-agent-usage-update"

# Create config if it doesn't exist
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/usage-config.json" ]]; then
    cat > "$CONFIG_DIR/usage-config.json" <<'EOF'
{
  "monthly_tokens": 82000000000,
  "remote_host": "",
  "remote_mimocode_db": "",
  "remote_hermes_db": ""
}
EOF
    echo "Created $CONFIG_DIR/usage-config.json — edit to configure."
fi

# Run initial collection
mkdir -p "$USAGE_DIR"
python3 "$BIN_DIR/collect-mimocode-usage" > "$USAGE_DIR/mimocode.json" 2>/dev/null || true

echo ""
echo "Installed! MiMoCode will appear in the agents panel."
echo "Refreshes automatically when you open the agents panel."
echo ""
echo "Configure remote machine in ~/.config/mimocode/usage-config.json"
