# MiMoCode Usage for Omarchy

MiMoCode token plan credits in the Omarchy agents panel. Fully automatic — no commands, no background processes.

Appears as another tab alongside Claude, Codex, and Fireworks. No extra icon.

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

## How it works

Hooks into the existing agents panel refresh — when you open the panel or press `r`, MiMoCode updates alongside Claude/Codex/Fireworks. No background timer.

Reads token usage from MiMoCode's SQLite database (local + remote via SSH) and converts to credits using per-model multipliers:

| Model | Credits per token |
|-------|------------------|
| mimo-v2.5-pro | 8x |
| mimo-v2.5, mimo-auto | 2x |
| Grok, nvidia, etc. | Not counted (separate API) |

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

## Uninstall

```bash
./uninstall.sh
```

## License

MIT
