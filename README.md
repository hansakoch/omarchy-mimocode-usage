# MiMoCode Usage for Omarchy

MiMoCode token usage in the Omarchy agents panel. Tracks local and remote MiMoCode + Hermes sessions via SSH.

Shows up as another tab in the existing agents panel alongside Claude, Codex, and Fireworks — no extra icon.

## Install

```bash
omarchy plugin add https://github.com/hansakoch/omarchy-mimocode-usage.git --enable
```

Or manually:

```bash
git clone https://github.com/hansakoch/omarchy-mimocode-usage.git
cd omarchy-mimocode-usage
./install.sh
```

## Setup

**Monthly credit meter** — set your usage from the [token plan dashboard](https://platform.xiaomimimo.com/console/plan-manage):

```bash
mimocode-usage 64          # percentage
mimocode-usage 52426735109 # or raw credit count
```

The token plan uses credits (not raw tokens) with per-model multipliers that aren't publicly available, so the monthly % can't be auto-calculated. Update it when you check the dashboard.

**Daily chart** — fully automatic. Reads from local MiMoCode SQLite database and optionally remote machines via SSH.

## Remote machine (optional)

To combine stats from a remote server, edit `~/.config/mimocode/usage-config.json`:

```json
{
  "monthly_tokens": 82000000000,
  "current_used": 52426735109,
  "remote_host": "vultr",
  "remote_mimocode_db": "/home/user/.local/share/mimocode/mimocode.db",
  "remote_hermes_db": "/home/user/.hermes/state.db"
}
```

Requires SSH key access to the remote machine.

## How it works

The collector reads token usage from MiMoCode's SQLite database (local and optionally remote via SSH), plus Hermes session data. It writes a JSON record to `~/.local/state/omarchy/agents/usage/mimocode.json` that the Omarchy agents panel watches.

A systemd timer refreshes the data every 15 minutes.

## Commands

```bash
mimocode-usage              # show current config
mimocode-usage 64           # set 64% monthly credits used
mimocode-usage refresh      # force panel refresh
```

## Uninstall

```bash
./uninstall.sh
```

## License

MIT
