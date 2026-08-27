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
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_ID = "mimocode"
AGENT_NAME = "MiMoCode"
CONFIG_PATH = Path.home() / ".config" / "mimocode" / "usage-config.json"
USAGE_JSON = Path.home() / ".config" / "mimocode" / "usage.json"


def load_config():
    defaults = {
        "monthly_tokens": 82_000_000_000,
        "current_used": 0,
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


def main():
    cfg = load_config()
    dates = recent_dates()

    local = collect_local_mimocode()

    remote_mc = None
    remote_hermes = None
    host = cfg.get("remote_host", "")
    if host:
        mc_db = cfg.get("remote_mimocode_db", "")
        hermes_db = cfg.get("remote_hermes_db", "")
        if mc_db:
            remote_mc = collect_remote_mimocode(host, mc_db)
        if hermes_db:
            remote_hermes = collect_remote_hermes(host, hermes_db)

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
    used = cfg.get("current_used", 0)
    monthly = None
    if total_limit > 0 and used > 0:
        monthly = {
            "label": "Monthly", "title": "Monthly",
            "percent": min(used / total_limit, 1.0),
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
        "tierLabel": "Token Plan",
    }

    if monthly:
        record["limits"].append(monthly)

    print(json.dumps(record))


if __name__ == "__main__":
    main()
