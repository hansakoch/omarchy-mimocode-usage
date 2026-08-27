# MiMoCode Usage for Omarchy

MiMoCode token usage in the Omarchy agents panel. Fully automatic — no manual commands needed.

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

## Configure

Edit `~/.config/mimocode/usage-config.json`:

```json
{
  "monthly_tokens": 82000000000,
  "remote_host": "vultr",
  "remote_mimocode_db": "/home/user/.local/share/mimocode/mimocode.db",
  "remote_hermes_db": "/home/user/.hermes/state.db"
}
```

- `monthly_tokens` — your token plan credit allocation
- `remote_host` — SSH host for a remote machine (optional)
- `remote_mimocode_db` / `remote_hermes_db` — paths on the remote machine (optional)

Requires SSH key access to the remote machine.

## How it works

The collector reads token usage from MiMoCode's SQLite database (local and optionally remote via SSH), plus Hermes session data. It converts raw tokens to credits using per-model multipliers derived from actual usage:

| Model | Credits per token |
|-------|------------------|
| mimo-v2.5-pro | 8x |
| mimo-v2.5, mimo-auto, grok, etc. | 2x |
| Free models | 0x |

A systemd timer refreshes every 15 minutes.

## Commands

```bash
mimocode-usage              # show current config and usage
mimocode-usage refresh      # force panel refresh
```

## Uninstall

```bash
./uninstall.sh
```

## License

MIT
