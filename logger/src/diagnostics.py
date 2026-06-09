import atexit
import json
import os
from collections import Counter
from datetime import datetime


_initialized = False
_output_path = None
_session_started_at = None
_counters = Counter()


def init(output_path):
    global _initialized, _output_path, _session_started_at, _counters

    _output_path = output_path
    _session_started_at = datetime.now().isoformat(timespec="seconds")
    _counters = Counter()

    if not _initialized:
        atexit.register(finalize)
        _initialized = True


def _ensure_ready():
    return bool(_output_path)


def _get_event_log_path():
    return _output_path + ".diagnostics.jsonl"


def _get_summary_path():
    return _output_path + ".diagnostics.summary.json"


def _ensure_directory(file_path):
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)


def increment(counter_name, amount=1):
    if not counter_name:
        return
    _counters[counter_name] += amount


def log_event(event_type, **details):
    if not _ensure_ready():
        return

    increment(f"events.{event_type}")
    event_log_path = _get_event_log_path()
    _ensure_directory(event_log_path)

    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "type": event_type,
    }
    record.update(details)

    with open(event_log_path, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def finalize():
    if not _ensure_ready() or not _session_started_at:
        return

    summary_path = _get_summary_path()
    _ensure_directory(summary_path)

    summary = {
        "session_started_at": _session_started_at,
        "session_ended_at": datetime.now().isoformat(timespec="seconds"),
        "output_path": _output_path,
        "counters": dict(sorted(_counters.items())),
    }

    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, sort_keys=False)
        file.write("\n")

    interesting_keys = [
        "analyze.filter.tcp_seen",
        "analyze.filter.accepted_bdo",
        "analyze.filter.rejected_non_bdo",
        "parser.records_written",
        "parser.drops.invalid_name",
        "parser.buffers.no_identifier",
        "parser.buffers.incomplete_log",
        "analyze.records_emitted",
        "analyze.drops.duplicate_suppressed",
        "analyze.buffers.no_identifier",
        "analyze.buffers.incomplete_log",
        "analyze.corrections.relaxed_fallback",
        "analyze.corrections.character_map",
        "analyze.corrections.family_character_map",
        "analyze.corrections.manual_override",
    ]
    summary_parts = []
    for key in interesting_keys:
        if key in _counters:
            summary_parts.append(f"{key}={_counters[key]}")

    if summary_parts:
        print("Diagnostics summary: " + ", ".join(summary_parts), flush=True)
