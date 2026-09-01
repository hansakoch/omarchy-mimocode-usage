#!/usr/bin/env python3
"""Collect MiMoCode + Hermes usage into one display-ready JSON record.

Reads local MiMoCode SQLite database, then optionally SSHs into a remote
server to merge MiMoCode and Hermes stats. Writes the same JSON schema
the Omarchy agents panel expects.

Configuration: ~/.config/mimocode/usage-config.json
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_ID = "mimocode"
AGENT_NAME = "MiMoCode"
CONFIG_PATH = Path.home() / ".config" / "mimocode" / "usage-config.json"
USAGE_JSON = Path.home() / ".config" / "mimocode" / "usage.json"
PLAN_DATA_FILE = Path.home() / ".config" / "mimocode" / "xiaomi-plan-data.json"
CACHE_PATH = Path.home() / ".cache" / "mimocode" / "remote-usage.json"
CACHE_TTL = 3600  # Refresh remote data every hour, not every click
CDP_PORT = 9222

# Token plan credit multipliers (derived from actual usage vs dashboard)
# Only MiMo models consume token plan credits. Grok, nvidia, etc. use separate API keys.
PRO_MODELS = {"mimo-v2.5-pro", "mimo-v2-pro"}
MIMO_MODELS = {"mimo-v2.5-pro", "mimo-v2.5", "mimo-auto", "mimo-v2-pro"}
FREE_KEYWORDS = {":free", "free hermes"}


def is_free_model(name):
    lower = name.lower()
    return any(kw in lower for kw in FREE_KEYWORDS)


def model_credit_multiplier(model_id):
    name = model_id.split("/")[-1].lower().replace(":thinking", "")
    if name in PRO_MODELS:
        return 8
    if name in MIMO_MODELS:
        return 2
    # Grok, nvidia, tencent, etc. — not part of MiMo token plan
    return 0


def tokens_to_credits(model_usage):
    """Convert raw token counts to credits using per-model multipliers."""
    total = 0
    for model, bucket in model_usage.items():
        mult = model_credit_multiplier(model)
        if mult > 0:
            total += sum(bucket.values()) * mult
    return total


def load_config():
    defaults = {
        "monthly_tokens": 0,  # 0 = no token plan (hides monthly meter)
        "tier_label": "",     # e.g. "Max Monthly Plan", "Pro Monthly Plan"
        "remote_host": "",
        "remote_mimocode_db": "",
        "remote_hermes_db": "",
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults


def fetch_plan_from_browser():
    """Fetch plan data from the Xiaomi API via the running browser's CDP.

    Connects to Chromium's remote debugging port and runs fetch() in the
    browser context, using the existing session cookies. Returns the parsed
    API response or None.
    """
    import urllib.request
    try:
        pages = json.loads(urllib.request.urlopen(
            f"http://localhost:{CDP_PORT}/json", timeout=3
        ).read())
    except Exception:
        return None

    # Find a usable page
    ws_url = None
    for p in pages:
        if p.get("webSocketDebuggerUrl"):
            ws_url = p["webSocketDebuggerUrl"]
            if "xiaomimimo.com" in p.get("url", ""):
                break

    if not ws_url:
        return None

    js = """
    (async () => {
        try {
            const [d, u] = await Promise.all([
                fetch('https://platform.xiaomimimo.com/api/v1/tokenPlan/detail', {credentials:'include'}).then(r => r.json()),
                fetch('https://platform.xiaomimimo.com/api/v1/tokenPlan/usage', {credentials:'include'}).then(r => r.json())
            ]);
            return JSON.stringify({detail: d, usage: u});
        } catch(e) { return JSON.stringify({error: e.message}); }
    })()
    """
    script = f"""
    const ws = new WebSocket("{ws_url}");
    ws.onopen = () => ws.send(JSON.stringify({{id:1, method:"Runtime.evaluate", params:{json.dumps({"expression": js, "awaitPromise": True, "returnByValue": True})}}}));
    ws.onmessage = (e) => {{ console.log(e.data); ws.close(); process.exit(0); }};
    ws.onerror = () => process.exit(1);
    setTimeout(() => process.exit(1), 10000);
    """
    try:
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            result = json.loads(r.stdout.strip())
            value = result.get("result", {}).get("result", {}).get("value", "")
            if value:
                data = json.loads(value)
                if not data.get("error") and data.get("detail", {}).get("code") != 401:
                    return data
    except Exception:
        pass
    return None


def load_plan_data():
    """Load plan data: try browser first, then cached file."""
    # Try live fetch from browser
    live = fetch_plan_from_browser()
    if live:
        live["_saved_at"] = datetime.now(timezone.utc).isoformat()
        try:
            PLAN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            PLAN_DATA_FILE.write_text(json.dumps(live, indent=2))
            PLAN_DATA_FILE.chmod(0o600)
        except Exception:
            pass
        return live

    # Fall back to cached file
    if PLAN_DATA_FILE.exists():
        try:
            return json.loads(PLAN_DATA_FILE.read_text())
        except Exception:
            pass
    return None


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def recent_dates():
    now = datetime.now()
    return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]


def ts_to_date(ts):
    try:
        t = float(ts)
        if t > 10_000_000_000:
            t = t / 1000
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d")
    except Exception:
        return today_str()


def empty_bucket():
    return {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}


def merge_bucket(target, source):
    for k in source:
        target[k] = target.get(k, 0) + source[k]


def collect_local_mimocode():
    db = Path.home() / ".local" / "share" / "mimocode" / "mimocode.db"
    if not db.exists():
        return None

    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("""
        SELECT session_id, data FROM message
        WHERE json_extract(data, '$.role') = 'assistant'
    """)

    today = today_str()
    dates = recent_dates()
    recent_map = {d: 0 for d in dates}
    stats = _empty_stats()

    for session_id, raw in cur.fetchall():
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        _ingest_message(stats, msg, session_id, msg.get("time", {}).get("created"),
                        msg.get("modelID", "unknown"), today, dates, recent_map)

    conn.close()
    stats["recentMap"] = recent_map
    return stats


def ssh_query(host, db_path, query):
    try:
        result = subprocess.run(
            ["ssh", host, "sqlite3", db_path],
            input=query, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def collect_remote_mimocode(host, db_path):
    query = (
        "SELECT json_extract(data, '$.tokens.input'), "
        "json_extract(data, '$.tokens.output'), "
        "json_extract(data, '$.tokens.reasoning'), "
        "json_extract(data, '$.tokens.cache.read'), "
        "json_extract(data, '$.tokens.cache.write'), "
        "json_extract(data, '$.modelID'), "
        "json_extract(data, '$.time.created'), "
        "session_id "
        "FROM message "
        "WHERE json_extract(data, '$.role') = 'assistant' "
        "AND json_extract(data, '$.tokens.input') > 0;"
    )
    raw = ssh_query(host, db_path, query)
    if not raw:
        return None

    today = today_str()
    dates = recent_dates()
    recent_map = {d: 0 for d in dates}
    stats = _empty_stats()

    for line in raw.split("\n"):
        parts = line.split("|")
        if len(parts) < 8:
            continue
        inp, out, reasoning = int(float(parts[0] or 0)), int(float(parts[1] or 0)), int(float(parts[2] or 0))
        cache_read, cache_write = int(float(parts[3] or 0)), int(float(parts[4] or 0))
        model, ts, session_id = parts[5] or "unknown", parts[6], parts[7]
        total = inp + out + reasoning + cache_read + cache_write
        if total == 0:
            continue

        date = ts_to_date(ts) if ts else today_str()
        stats["activeDates"].add(date)
        stats["totalPrompts"] += 1
        if session_id:
            stats["totalSessions"].add(session_id)
        if date in recent_map:
            recent_map[date] += total
        if date == today:
            stats["todayTokens"] += total
            stats["todayPrompts"] += 1
            if session_id:
                stats["todaySessions"].add(session_id)
            stats["todayByModel"][model] = stats["todayByModel"].get(model, 0) + total

        if model not in stats["modelUsage"]:
            stats["modelUsage"][model] = empty_bucket()
        mu = stats["modelUsage"][model]
        mu["inputTokens"] += inp
        mu["outputTokens"] += out + reasoning
        mu["cacheReadInputTokens"] += cache_read
        mu["cacheCreationInputTokens"] += cache_write

    stats["recentMap"] = recent_map
    return stats


def collect_remote_hermes(host, db_path):
    query = (
        "SELECT COALESCE(input_tokens, 0), COALESCE(output_tokens, 0), "
        "COALESCE(cache_read_tokens, 0), COALESCE(reasoning_tokens, 0), "
        "COALESCE(model, 'unknown'), started_at, id "
        "FROM sessions WHERE COALESCE(input_tokens, 0) > 0;"
    )
    raw = ssh_query(host, db_path, query)
    if not raw:
        return None

    today = today_str()
    dates = recent_dates()
    recent_map = {d: 0 for d in dates}
    stats = _empty_stats()

    for line in raw.split("\n"):
        parts = line.split("|")
        if len(parts) < 7:
            continue
        inp, out = int(float(parts[0] or 0)), int(float(parts[1] or 0))
        cache_read, reasoning = int(float(parts[2] or 0)), int(float(parts[3] or 0))
        model, ts, session_id = parts[4] or "unknown", parts[5], parts[6]
        total = inp + out + cache_read + reasoning
        if total == 0:
            continue

        date = ts_to_date(ts) if ts else today_str()
        stats["activeDates"].add(date)
        stats["totalPrompts"] += 1
        if session_id:
            stats["totalSessions"].add(session_id)
        if date in recent_map:
            recent_map[date] += total
        if date == today:
            stats["todayTokens"] += total
            stats["todayPrompts"] += 1
            if session_id:
                stats["todaySessions"].add(session_id)
            stats["todayByModel"][model] = stats["todayByModel"].get(model, 0) + total

        if model not in stats["modelUsage"]:
            stats["modelUsage"][model] = empty_bucket()
        mu = stats["modelUsage"][model]
        mu["inputTokens"] += inp
        mu["outputTokens"] += out + reasoning
        mu["cacheReadInputTokens"] += cache_read

    stats["recentMap"] = recent_map
    return stats


def _empty_stats():
    return {
        "todayTokens": 0, "todayPrompts": 0, "todaySessions": set(),
        "todayByModel": {}, "totalPrompts": 0, "totalSessions": set(),
        "activeDates": set(), "modelUsage": {},
    }


def _ingest_message(stats, msg, session_id, ts, model, today, dates, recent_map):
    tokens = msg.get("tokens", {})
    inp = int(tokens.get("input", 0) or 0)
    out = int(tokens.get("output", 0) or 0)
    reasoning = int(tokens.get("reasoning", 0) or 0)
    cache = tokens.get("cache", {})
    cache_read = int(cache.get("read", 0) or 0)
    cache_write = int(cache.get("write", 0) or 0)
    total = inp + out + reasoning + cache_read + cache_write
    if total == 0:
        return

    date = ts_to_date(ts) if ts else today_str()
    stats["activeDates"].add(date)
    stats["totalPrompts"] += 1
    if session_id:
        stats["totalSessions"].add(session_id)
    if date in recent_map:
        recent_map[date] += total
    if date == today:
        stats["todayTokens"] += total
        stats["todayPrompts"] += 1
        if session_id:
            stats["todaySessions"].add(session_id)
        stats["todayByModel"][model] = stats["todayByModel"].get(model, 0) + total

    if model not in stats["modelUsage"]:
        stats["modelUsage"][model] = empty_bucket()
    mu = stats["modelUsage"][model]
    mu["inputTokens"] += inp
    mu["outputTokens"] += out + reasoning
    mu["cacheReadInputTokens"] += cache_read
    mu["cacheCreationInputTokens"] += cache_write


def merge_stats(base, addition):
    if not addition:
        return
    base["todayTokens"] += addition["todayTokens"]
    base["todayPrompts"] += addition["todayPrompts"]
    base["todaySessions"] |= addition["todaySessions"]
    base["totalPrompts"] += addition["totalPrompts"]
    base["totalSessions"] |= addition["totalSessions"]
    base["activeDates"] |= addition["activeDates"]
    for d in addition.get("recentMap", {}):
        base.setdefault("recentMap", {})[d] = base.get("recentMap", {}).get(d, 0) + addition["recentMap"][d]
    for m, v in addition["todayByModel"].items():
        base["todayByModel"][m] = base["todayByModel"].get(m, 0) + v
    for model, bucket in addition["modelUsage"].items():
        if model not in base["modelUsage"]:
            base["modelUsage"][model] = empty_bucket()
        merge_bucket(base["modelUsage"][model], bucket)


def month_end_iso():
    now = datetime.now()
    if now.month == 12:
        end = now.replace(year=now.year + 1, month=1, day=1)
    else:
        end = now.replace(month=now.month + 1, day=1)
    return end.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc).isoformat()


def estimate_run_rate(stats, plan_data, total_limit):
    """Estimate daily budget and burn rate.

    Tokens expire at month end, so what matters is:
    - How many tokens remain
    - How many days are left in the billing cycle
    - What daily budget that gives you
    - Whether your current pace will run out or leave tokens wasted
    """
    now = datetime.now()
    today = now.date()

    plan_usage = plan_data.get("usage", {}).get("data", {}) if plan_data else {}
    plan_detail = plan_data.get("detail", {}).get("data", {}) if plan_data else {}
    month_items = plan_usage.get("monthUsage", {}).get("items", [])

    # Get current month usage (API preferred, local fallback)
    if month_items:
        used = month_items[0].get("used", 0)
        pct = month_items[0].get("percent", 0)
    else:
        used = tokens_to_credits(stats.get("modelUsage", {}))
        pct = used / total_limit if total_limit > 0 else 0

    remaining = total_limit - used

    # Days left in billing cycle
    expires = plan_detail.get("currentPeriodEnd", "")
    end_date = None
    if expires:
        try:
            end_date = datetime.fromisoformat(expires.replace(" ", "T")).date()
        except Exception:
            pass
    if not end_date:
        # Default to end of month
        if now.month == 12:
            end_date = now.replace(year=now.year + 1, month=1, day=1).date()
        else:
            end_date = now.replace(month=now.month + 1, day=1).date()

    days_left = max((end_date - today).days, 1)

    # Daily budget to use all tokens by expiry
    daily_budget = remaining / days_left if days_left > 0 else 0

    # Current month daily rate
    month_start = today.replace(day=1)
    days_elapsed = max((today - month_start).days + 1, 1)
    current_daily = used / days_elapsed

    # Historical rate from recent days
    recent_map = stats.get("recentMap", {})
    all_daily = [t for t in recent_map.values() if t > 0]
    historical_daily = 0
    if len(all_daily) >= 3:
        sorted_daily = sorted(all_daily)
        historical_daily = sorted_daily[len(sorted_daily) // 2]
    elif all_daily:
        historical_daily = sum(all_daily) / len(all_daily)

    # Convert historical tokens to credits
    total_recent_tokens = sum(recent_map.values())
    credit_per_token = used / total_recent_tokens if total_recent_tokens > 0 and used > 0 else 1
    historical_daily_credits = historical_daily * credit_per_token

    # Projected end dates
    projected_end_current = None
    projected_end_historical = None
    if current_daily > 0:
        days_to_100_current = remaining / current_daily
        projected_end_current = (today + timedelta(days=int(days_to_100_current))).isoformat()
    if historical_daily_credits > 0:
        days_to_100_historical = remaining / historical_daily_credits
        projected_end_historical = (today + timedelta(days=int(days_to_100_historical))).isoformat()

    # Verdict
    verdict = "on-track"
    if current_daily > daily_budget * 1.5:
        verdict = "over-pace"
    elif current_daily < daily_budget * 0.5 and days_left < 15:
        verdict = "under-pace"

    return {
        "used": int(used),
        "limit": int(total_limit),
        "percent": round(pct * 100, 1),
        "remaining": int(remaining),
        "daysLeft": days_left,
        "dailyBudget": int(daily_budget),
        "currentDaily": int(current_daily),
        "historicalDaily": int(historical_daily_credits),
        "projectedEndCurrent": projected_end_current,
        "projectedEndHistorical": projected_end_historical,
        "verdict": verdict,
    }


def load_remote_cache():
    """Load cached remote stats if fresh enough."""
    if not CACHE_PATH.exists():
        return None, None
    try:
        mtime = CACHE_PATH.stat().st_mtime
        if time.time() - mtime > CACHE_TTL:
            return None, None  # Stale
        with open(CACHE_PATH) as f:
            data = json.load(f)

        def deserialize_stats(raw):
            if not raw:
                return None
            return {
                "todayTokens": raw["todayTokens"],
                "todayPrompts": raw["todayPrompts"],
                "todaySessions": set(raw["todaySessions"]),
                "todayByModel": raw["todayByModel"],
                "totalPrompts": raw["totalPrompts"],
                "totalSessions": set(raw["totalSessions"]),
                "activeDates": set(raw["activeDates"]),
                "recentMap": raw.get("recentMap", {}),
                "modelUsage": raw["modelUsage"],
            }

        return deserialize_stats(data.get("mimocode")), deserialize_stats(data.get("hermes"))
    except Exception:
        return None, None


def save_remote_cache(mc_stats, hermes_stats):
    """Cache remote stats to disk."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

        def serialize_stats(stats):
            if not stats:
                return None
            return {
                "todayTokens": stats["todayTokens"],
                "todayPrompts": stats["todayPrompts"],
                "todaySessions": list(stats["todaySessions"]),
                "todayByModel": stats["todayByModel"],
                "totalPrompts": stats["totalPrompts"],
                "totalSessions": list(stats["totalSessions"]),
                "activeDates": list(stats["activeDates"]),
                "recentMap": stats.get("recentMap", {}),
                "modelUsage": stats["modelUsage"],
            }

        with open(CACHE_PATH, "w") as f:
            json.dump({
                "mimocode": serialize_stats(mc_stats),
                "hermes": serialize_stats(hermes_stats),
            }, f)
    except Exception:
        pass


def main():
    cfg = load_config()
    dates = recent_dates()

    local = collect_local_mimocode()

    remote_mc = None
    remote_hermes = None
    host = cfg.get("remote_host", "")
    if host:
        # Try cache first (avoids SSH on every click)
        remote_mc, remote_hermes = load_remote_cache()
        if remote_mc is None and remote_hermes is None:
            # Cache miss or stale — fetch via SSH
            mc_db = cfg.get("remote_mimocode_db", "")
            hermes_db = cfg.get("remote_hermes_db", "")
            if mc_db:
                remote_mc = collect_remote_mimocode(host, mc_db)
            if hermes_db:
                remote_hermes = collect_remote_hermes(host, hermes_db)
            save_remote_cache(remote_mc, remote_hermes)

    stats = local or remote_mc or remote_hermes
    if not stats:
        record = {
            "schemaVersion": 1, "id": AGENT_ID, "name": AGENT_NAME,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "ready": False, "hasLocalStats": True,
            "usageStatusText": "No session data found",
            "authHelpText": "Start a mimo session to begin tracking usage.",
            "todayPrompts": 0, "todaySessions": 0, "todayTotalTokens": 0,
            "todayTokensByModel": {},
            "recentDays": [{"date": d, "messageCount": 0} for d in dates],
            "totalPrompts": 0, "totalSessions": 0, "activeDays": 0,
            "activeDates": [], "modelUsage": {}, "limits": [], "tierLabel": "",
        }
        print(json.dumps(record))
        return

    if stats is local:
        merge_stats(stats, remote_mc)
        merge_stats(stats, remote_hermes)
    elif stats is remote_mc:
        merge_stats(stats, local)
        merge_stats(stats, remote_hermes)
    else:
        merge_stats(stats, local)
        merge_stats(stats, remote_mc)

    recent_days = [{"date": d, "messageCount": stats.get("recentMap", {}).get(d, 0)} for d in dates]

    total_limit = cfg.get("monthly_tokens", 82_000_000_000)

    # Try to get real plan usage from the Xiaomi API
    plan_data = load_plan_data()
    plan_detail = plan_data.get("detail", {}).get("data", {}) if plan_data else {}
    plan_usage = plan_data.get("usage", {}).get("data", {}) if plan_data else {}

    # Use API tier label if available, fall back to config
    tier_label = cfg.get("tier_label", "")
    if plan_detail.get("planName"):
        auto = plan_detail.get("enableAutoRenew", False)
        tier_label = f"{plan_detail['planName']} {'Auto-Renewal' if auto else ''} Monthly".strip()

    # Use API usage percentage if available, fall back to local calculation
    monthly = None
    month_items = plan_usage.get("monthUsage", {}).get("items", [])
    if month_items:
        item = month_items[0]
        expires = plan_detail.get("currentPeriodEnd", "")
        resets_at = ""
        if expires:
            try:
                resets_at = expires.replace(" ", "T") + "+00:00"
            except Exception:
                resets_at = month_end_iso()
        else:
            resets_at = month_end_iso()
        monthly = {
            "label": "Monthly", "title": "Monthly",
            "percent": item.get("percent", 0),
            "resetsAt": resets_at,
        }
    elif total_limit > 0:
        # Fall back to local calculation
        used_credits = tokens_to_credits(stats["modelUsage"])
        if used_credits > 0:
            monthly = {
                "label": "Monthly", "title": "Monthly",
                "percent": min(used_credits / total_limit, 1.0),
                "resetsAt": month_end_iso(),
            }

    record = {
        "schemaVersion": 1, "id": AGENT_ID, "name": AGENT_NAME,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "ready": True, "hasLocalStats": True,
        "todayPrompts": stats["todayPrompts"],
        "todaySessions": len(stats["todaySessions"]),
        "todayTotalTokens": stats["todayTokens"],
        "todayTokensByModel": stats["todayByModel"],
        "recentDays": recent_days,
        "totalPrompts": stats["totalPrompts"],
        "totalSessions": len(stats["totalSessions"]),
        "activeDays": len(stats["activeDates"]),
        "activeDates": sorted(stats["activeDates"]),
        "modelUsage": stats["modelUsage"],
        "limits": [],
        "tierLabel": tier_label,
    }

    if monthly:
        record["limits"].append(monthly)

    # Run rate estimation
    run_rate = estimate_run_rate(stats, plan_data, total_limit)
    record["runRate"] = run_rate

    # Add run rate as status text the panel displays
    rr = run_rate
    days = rr.get("daysLeft", 0)
    budget = rr.get("dailyBudget", 0)
    current = rr.get("currentDaily", 0)
    verdict = rr.get("verdict", "")

    def fmt_tokens(n):
        if n >= 1_000_000_000:
            return f"{n/1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"{n/1_000_000:.0f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}K"
        return str(int(n))

    # Hero subtitle: short, fits in one line
    if verdict == "over-pace":
        end = rr.get("projectedEndCurrent", "")
        short_end = ""
        if end:
            try:
                short_end = datetime.fromisoformat(end).strftime("%b %d")
            except Exception:
                short_end = end
        record["tierLabel"] = f"Max · runs out {short_end}"
    else:
        record["tierLabel"] = f"Max · {days}d left"

    # Red status block: detailed breakdown (authHelpText)
    status_parts = []
    status_parts.append(f"Budget: {fmt_tokens(budget)}/d to last the month")
    status_parts.append(f"Using: {fmt_tokens(current)}/d now")
    if verdict == "over-pace":
        end = rr.get("projectedEndCurrent", "")
        short_end = ""
        if end:
            try:
                short_end = datetime.fromisoformat(end).strftime("%b %d")
            except Exception:
                short_end = end
        status_parts.append(f"⚠ At this pace you'll run out {short_end}")
    record["authHelpText"] = "\n".join(status_parts)

    print(json.dumps(record))


if __name__ == "__main__":
    main()
