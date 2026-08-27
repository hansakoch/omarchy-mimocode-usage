#!/bin/bash
# Uninstall MiMoCode usage tracking.
set -euo pipefail

echo "Uninstalling MiMoCode Usage..."

systemctl --user disable --now mimocode-usage.timer 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/mimocode-usage.service"
rm -f "$HOME/.config/systemd/user/mimocode-usage.timer"
systemctl --user daemon-reload 2>/dev/null || true

rm -f "$HOME/.local/bin/collect-mimocode-usage"
rm -f "$HOME/.local/bin/mimocode-usage"
rm -f "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage/mimocode.json"

echo "Removed. Config left at ~/.config/mimocode/ (delete manually if desired)."
