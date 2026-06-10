"""Runtime settings helpers shared across logger modules.

This module centralizes process-name normalization and discovery target
composition so IP discovery behavior is consistent across sniff/analyze/record.
"""

from . import config


_DEFAULT_GAME_PROCESS = "BlackDesert64.exe"
_EXITLAG_PROCESS = "ExitLag.exe"


def normalize_process_name(process_name):
    """Normalize a process name for tasklist/netstat matching."""
    value = str(process_name or "").strip()
    if not value:
        return ""
    return value


def get_additional_discovery_processes():
    """Return configured user-added process names for IP discovery."""
    cfg = getattr(config, "config", None)
    values = getattr(cfg, "discovery_processes", []) if cfg else []

    deduped = []
    for entry in values or []:
        normalized = normalize_process_name(entry)
        if not normalized:
            continue
        if any(existing.lower() == normalized.lower() for existing in deduped):
            continue
        deduped.append(normalized)

    return deduped


def get_discovery_target_processes(process_name=None, include_exitlag=True):
    """Build ordered process list used to discover active remote IPs."""
    primary = normalize_process_name(process_name) or _DEFAULT_GAME_PROCESS

    target_processes = [primary]

    for candidate in get_additional_discovery_processes():
        if any(existing.lower() == candidate.lower() for existing in target_processes):
            continue
        target_processes.append(candidate)

    if include_exitlag:
        if not any(existing.lower() == _EXITLAG_PROCESS.lower() for existing in target_processes):
            target_processes.append(_EXITLAG_PROCESS)
    else:
        target_processes = [
            name for name in target_processes
            if name.lower() != _EXITLAG_PROCESS.lower()
        ]

    return target_processes
