"""Shared live IP discovery for sniff/analyze/record modes.

This module centralizes dynamic IP discovery so all runtime modes use the same
rules and update cadence. The discovery loop refreshes in-memory transient
prefixes/endpoints that are merged by config.get_effective_ips().
"""

import threading
import time as _time_module

from .. import config
from . import discover_game


DEFAULT_FAST_RETRY_SECONDS = 5
DEFAULT_FAST_RETRY_MAX_SECONDS = 90
DEFAULT_DISCOVERY_INTERVAL_SECONDS = 30

_started_threads = set()
_started_threads_lock = threading.Lock()


def _dedupe_non_empty(values):
    deduped = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _extract_runtime_prefixes(payload):
    summary = payload.get("summary") or {}
    prefixes = []

    # Runtime filtering should prioritize capture completeness. Include all
    # observed prefixes from target-process connections, not only high-confidence.
    for connection in payload.get("connections") or []:
        if isinstance(connection, dict):
            prefixes.append(connection.get("prefix"))

    for item in summary.get("prefixes") or []:
        if isinstance(item, dict):
            prefixes.append(item.get("prefix"))

    prefixes.extend(payload.get("transient_prefixes") or [])
    prefixes.extend(((payload.get("bdo_summary") or {}).get(
        "high_confidence_prefixes") or []))
    prefixes.extend(((payload.get("exitlag_summary") or {}).get(
        "high_confidence_prefixes") or []))

    return _dedupe_non_empty(prefixes)


def _extract_transient_endpoints(payload):
    endpoints = []
    endpoints.extend(payload.get("transient_endpoints") or [])
    endpoints.extend(payload.get("exitlag_endpoints") or [])
    return _dedupe_non_empty(endpoints)


def run_live_ip_discovery_update():
    """Run one discovery pass and refresh transient config state.

    Returns True if any prefixes are currently available after the update.
    """
    try:
        result = discover_game.run(
            include_exitlag=True,
            apply=False,
            apply_transient=False,
        )

        combined_prefixes = _extract_runtime_prefixes(result)
        endpoints = _extract_transient_endpoints(result)

        # Keep previously discovered session prefixes to avoid flapping when
        # point-in-time connection snapshots miss an active game relay node.
        combined_prefixes = _dedupe_non_empty(
            list(config.get_transient_ips()) + combined_prefixes
        )

        config.add_transient_ips(combined_prefixes)
        config.add_transient_endpoints(endpoints)
        config.refresh_active_exitlag_endpoint(endpoints)
        return bool(combined_prefixes)
    except Exception as exc:
        print(f"Live IP discovery error: {exc}", flush=True)
        return False


def start_live_ip_discovery_thread(
    thread_name,
    fast_retry_seconds=DEFAULT_FAST_RETRY_SECONDS,
    fast_retry_max_seconds=DEFAULT_FAST_RETRY_MAX_SECONDS,
    discovery_interval_seconds=DEFAULT_DISCOVERY_INTERVAL_SECONDS,
):
    """Start a singleton discovery thread by name.

    Multiple callers can request discovery safely; each distinct thread name is
    started at most once during process lifetime.
    """
    with _started_threads_lock:
        if thread_name in _started_threads:
            return None
        _started_threads.add(thread_name)

    found = run_live_ip_discovery_update()

    def _loop():
        nonlocal found
        elapsed = 0
        while not found and elapsed < fast_retry_max_seconds:
            _time_module.sleep(fast_retry_seconds)
            elapsed += fast_retry_seconds
            found = run_live_ip_discovery_update()

        while True:
            _time_module.sleep(discovery_interval_seconds)
            run_live_ip_discovery_update()

    thread = threading.Thread(target=_loop, daemon=True, name=thread_name)
    thread.start()
    return thread
