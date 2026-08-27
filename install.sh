#!/bin/bash
# Install MiMoCode usage tracking for the Omarchy agents panel.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/mimocode"
SYSTEMD_DIR="$HOME/.config/systemd/user"
USAGE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage"

echo "Installing MiMoCode Usage for Omarchy..."

# Copy scripts
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/collect-usage.py" "$BIN_DIR/collect-mimocode-usage"
cp "$SCRIPT_DIR/mimocode-usage" "$BIN_DIR/mimocode-usage"
chmod +x "$BIN_DIR/collect-mimocode-usage" "$BIN_DIR/mimocode-usage"

# Create config if it doesn't exist
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/usage-config.json" ]]; then
    cat > "$CONFIG_DIR/usage-config.json" <<'EOF'
{
  "monthly_tokens": 82000000000,
  "current_used": 0,
  "remote_host": "",
  "remote_mimocode_db": "",
  "remote_hermes_db": ""
}
EOF
    echo "Created $CONFIG_DIR/usage-config.json — edit to configure."
fi

# Install systemd timer
mkdir -p "$SYSTEMD_DIR"
cat > "$SYSTEMD_DIR/mimocode-usage.service" <<EOF
[Unit]
Description=Collect MiMoCode usage for Omarchy agents panel

[Service]
Type=oneshot
TimeoutStartSec=30
ExecStart=/usr/bin/python3 $BIN_DIR/collect-mimocode-usage
StandardOutput=truncate:$USAGE_DIR/mimocode.json
EOF

cat > "$SYSTEMD_DIR/mimocode-usage.timer" <<'EOF'
[Unit]
Description=Periodically collect MiMoCode usage

[Timer]
OnBootSec=30s
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now mimocode-usage.timer

# Run initial collection
mkdir -p "$USAGE_DIR"
python3 "$BIN_DIR/collect-mimocode-usage" > "$USAGE_DIR/mimocode.json"

echo ""
echo "Installed! Next steps:"
echo ""
echo "  1. Set your monthly usage:"
echo "     mimocode-usage 64"
echo ""
echo "  2. (Optional) Add remote machine for combined stats:"
echo "     Edit ~/.config/mimocode/usage-config.json"
echo "     Set remote_host, remote_mimocode_db, remote_hermes_db"
echo ""
echo "  3. The agents panel will show MiMoCode automatically."
echo "     Timer refreshes every 15 minutes."
