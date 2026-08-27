#!/bin/bash
# Uninstall MiMoCode usage tracking.
set -euo pipefail

echo "Uninstalling MiMoCode Usage..."

# Remove wrapper
rm -f "$HOME/.mimocode/bin/omarchy-agent-usage-update"

# Remove collector and helper
rm -f "$HOME/.local/bin/collect-mimocode-usage"
rm -f "$HOME/.local/bin/mimocode-usage"

# Remove panel data
rm -f "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage/mimocode.json"

# Remove systemd timer if it exists
systemctl --user disable --now mimocode-usage.timer 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/mimocode-usage.service"
rm -f "$HOME/.config/systemd/user/mimocode-usage.timer"
systemctl --user daemon-reload 2>/dev/null || true

echo "Removed. Config left at ~/.config/mimocode/ (delete manually if desired)."
