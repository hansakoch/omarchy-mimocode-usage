# MiMoCode Usage for Omarchy

MiMoCode token usage in the Omarchy agents panel. Tracks local and remote MiMoCode + Hermes sessions.

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

Set your monthly usage (from the [token plan dashboard](https://platform.xiaomimimo.com/console/plan-manage)):

```bash
mimocode-usage 64          # percentage
mimocode-usage 52426735109 # or raw token count
```

## Remote machine (optional)

To combine stats from a remote server (e.g. Vultr), edit `~/.config/mimocode/usage-config.json`:

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

The monthly meter reads from `~/.config/mimocode/usage-config.json` — update it with `mimocode-usage` when you check the dashboard.

## Uninstall

```bash
./uninstall.sh
```

## License

MIT
