"""Analyzer mode for live calibration and offline replay diagnostics.

This module emits structured analyzer rows used by the UI create-config flow,
tracks duplicate suppression, and supports pcap replay with progress reporting.
"""

import json
import os
import re
import threading
from .live_ip_discovery import start_live_ip_discovery_thread
from collections import deque
from scapy.all import sniff, get_if_list
from scapy.arch.windows import get_windows_if_list
from scapy.utils import RawPcapReader
from time import localtime, strftime, time

from .. import config, diagnostics, core_heuristics


last_payload = ""
_last_config_refresh_at = 0.0
CONFIG_REFRESH_INTERVAL_SECONDS = 20.0

identifier_regex = r"[56][0-9a-f]0100[0-9a-f]{4}"
_IDENTIFIER_HEX_PATTERN = re.compile(r"^[0-9a-f]{10}$")
_IDENTIFIER_FALLBACK_PATTERN = re.compile(identifier_regex)
_cached_identifier_value = None
_cached_identifier_pattern = None
_last_emitted_signature = None
_recent_emitted_signatures = deque(maxlen=256)
_last_emitted_second_by_combat = {}
_last_emitted_second_by_text = {}
_last_emitted_payload_by_combat = {}
_last_emitted_payload_by_text = {}
DUPLICATE_SUPPRESSION_SECONDS = 2

_KNOWN_SERVER_IP_PREFIXES = [
    "20.76.13",
    "20.76.14",
    "211.188.27",
    "20.25.194",
    "172.183.60",
]


def validate_name(name):
    return core_heuristics.is_valid_name(name)


def _timestamp_to_seconds(timestamp_text):
    try:
        hh, mm, ss = [int(value)
                      for value in str(timestamp_text).split(":", 2)]
    except ValueError:
        return None

    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None

    return (hh * 3600) + (mm * 60) + ss


def _get_server_ip_prefixes():
    configured = []
    for ip in config.get_effective_ips():
        normalized = str(ip).strip()
        if normalized:
            configured.append(normalized)

    if configured:
        return configured

    return list(_KNOWN_SERVER_IP_PREFIXES)


def _is_server_ip_match(ip_value, prefixes):
    ip_text = str(ip_value or "").strip()
    if not ip_text:
        return False

    for prefix in prefixes:
        candidate = prefix if isinstance(prefix, str) else str(prefix or "")
        candidate = candidate.strip()
        if not candidate:
            continue
        if ip_text == candidate or ip_text.startswith(candidate + "."):
            return True
    return False


def _refresh_config_if_stale():
    global _last_config_refresh_at

    now = time()
    if now - _last_config_refresh_at < CONFIG_REFRESH_INTERVAL_SECONDS:
        return

    cfg = getattr(config, "config", None)
    filename = getattr(cfg, "filename", None)
    if not filename:
        _last_config_refresh_at = now
        return

    try:
        config.init(filename)
    except Exception:
        pass
    finally:
        _last_config_refresh_at = now


def _find_identifier_matches(payload):
    global _cached_identifier_value, _cached_identifier_pattern

    configured_identifier = str(
        getattr(getattr(config, "config", None), "identifier", "")
    ).strip().lower()
    if configured_identifier != _cached_identifier_value:
        _cached_identifier_value = configured_identifier
        if _IDENTIFIER_HEX_PATTERN.fullmatch(configured_identifier):
            _cached_identifier_pattern = re.compile(
                re.escape(configured_identifier))
        else:
            _cached_identifier_pattern = None

    if _cached_identifier_pattern is not None:
        configured_matches = [
            match for match in _cached_identifier_pattern.finditer(payload)
            if match.start() % 2 == 0
        ]
        if configured_matches:
            return configured_matches

    return [
        match for match in _IDENTIFIER_FALLBACK_PATTERN.finditer(payload)
        if match.start() % 2 == 0
    ]


def _select_identifier_match(matches, payload_length, log_length):
    if not matches:
        return None

    valid_matches = [
        m for m in matches
        if (m.start() + log_length) <= payload_length
    ]
    if not valid_matches:
        return matches[0]

    if len(valid_matches) == 1:
        return valid_matches[0]

    selected = valid_matches[0]
    for index in range(len(valid_matches) - 1):
        current = valid_matches[index]
        next_match = valid_matches[index + 1]
        if current.start() + log_length <= next_match.start():
            selected = current
            break
    else:
        selected = valid_matches[1]

    return selected


def package_handler(package, output, ip_filter=True):
    global last_payload
    global _last_emitted_signature
    global _recent_emitted_signatures
    global _last_emitted_second_by_combat
    global _last_emitted_second_by_text
    global _last_emitted_payload_by_combat
    global _last_emitted_payload_by_text

    if "IP" not in package:
        return

    _refresh_config_if_stale()

    package_src = package["IP"].src
    package_dst = package["IP"].dst
    cfg = getattr(config, "config", None)
    decoding_strategy = getattr(
        cfg,
        "decoding_strategy",
        "latin1" if getattr(cfg, "region", "ASIA") in (
            "NA", "EU") else "utf16le",
    )
    server_ip_prefixes = _get_server_ip_prefixes()

    uses_tcp = "TCP" in package and hasattr(package["TCP"].payload, "load")
    if uses_tcp:
        diagnostics.increment("analyze.filter.tcp_seen")

    is_bdo_ip = (not ip_filter) or _is_server_ip_match(
        package_src, server_ip_prefixes
    ) or _is_server_ip_match(package_dst, server_ip_prefixes)

    if uses_tcp and not is_bdo_ip:
        diagnostics.increment("analyze.filter.rejected_non_bdo")
        return

    if is_bdo_ip and uses_tcp:
        diagnostics.increment("analyze.filter.accepted_bdo")

        log_length = getattr(
            getattr(config, "config", None), "log_length", 600)
        payload = bytes(package["TCP"].payload).hex()
        payload = last_payload + payload
        position = 0

        while len(payload[position:]) >= log_length:
            payload = payload[position:]
            position = 0

            matches = _find_identifier_matches(payload)
            if len(matches) == 0:
                last_payload = payload[-log_length:]
                diagnostics.increment("analyze.buffers.no_identifier")
                return

            selected_match = _select_identifier_match(
                matches, len(payload), log_length)
            if selected_match is None:
                last_payload = payload[-log_length:]
                return

            identifier_advance = len(selected_match.group(0))

            payload = payload[selected_match.start():]
            if len(payload) < log_length:
                diagnostics.increment("analyze.buffers.incomplete_log")
                break

            possible_log = payload[0:log_length]
            kill_flag_valid, is_kill = core_heuristics.parse_kill_flag(
                possible_log,
                getattr(cfg, "kill_offset", None),
            )
            if getattr(cfg, "kill_offset", None) is not None and not kill_flag_valid:
                diagnostics.increment(
                    "analyze.records_rejected_invalid_kill_flag")
                position = 2
                continue

            roles = core_heuristics.select_best_roles(
                possible_log,
                cfg=getattr(config, "config", None),
                decoding_strategy=decoding_strategy,
            )

            if roles:
                if core_heuristics.looks_low_quality_roles(
                    roles,
                    decoding_strategy=decoding_strategy,
                ):
                    diagnostics.increment(
                        "analyze.records_rejected_low_quality")
                    position = identifier_advance
                    continue

                time_value = strftime("%I:%M:%S", localtime(int(package.time)))
                candidates = core_heuristics.roles_to_emitted_candidates(
                    possible_log,
                    roles,
                    cfg=getattr(config, "config", None),
                    decoding_strategy=decoding_strategy,
                    max_candidates=5,
                )
                names = [f"{name} {offset}" for name, offset in candidates if isinstance(
                    name, str) and isinstance(offset, int)]
                if str(decoding_strategy or "").lower() != "latin1" and len(names) < 5:
                    diagnostics.increment(
                        "analyze.records_rejected_low_quality")
                    position = identifier_advance
                    continue
                log_body = (
                    f"{roles.get('player_one', '')} "
                    f"{'has killed' if is_kill else 'died to'} "
                    f"{roles.get('player_two', '')} from {roles.get('guild', '')}"
                )
                payload_fingerprint = possible_log
                combat_signature = (
                    bool(is_kill),
                    roles.get("player_one", ""),
                    roles.get("player_two", ""),
                    roles.get("guild", ""),
                )
                current_signature = combat_signature + (time_value,)
                event_second = _timestamp_to_seconds(time_value)
                previous_second = _last_emitted_second_by_combat.get(
                    combat_signature)
                previous_text_second = _last_emitted_second_by_text.get(
                    log_body)
                duplicate_within_one_second = (
                    previous_second is not None
                    and event_second is not None
                    and abs(event_second - previous_second) <= DUPLICATE_SUPPRESSION_SECONDS
                    and _last_emitted_payload_by_combat.get(combat_signature) == payload_fingerprint
                )
                duplicate_text_within_one_second = (
                    previous_text_second is not None
                    and event_second is not None
                    and abs(event_second - previous_text_second) <= DUPLICATE_SUPPRESSION_SECONDS
                    and _last_emitted_payload_by_text.get(log_body) == payload_fingerprint
                )
                if (
                    current_signature == _last_emitted_signature
                    or current_signature in _recent_emitted_signatures
                    or duplicate_within_one_second
                    or duplicate_text_within_one_second
                ):
                    diagnostics.increment(
                        "analyze.records_suppressed_duplicate")
                    position = identifier_advance
                    continue

                if not ip_filter:
                    print(f"LOG_SRC_IP {package_src}", flush=True)
                print(
                    payload[0:10]
                    + ","
                    + time_value
                    + ","
                    + ",".join(names)
                    + ","
                    + possible_log,
                    flush=True,
                )
                _last_emitted_signature = current_signature
                _recent_emitted_signatures.append(current_signature)
                if event_second is not None:
                    _last_emitted_second_by_combat[combat_signature] = event_second
                    _last_emitted_second_by_text[log_body] = event_second
                    _last_emitted_payload_by_combat[combat_signature] = payload_fingerprint
                    _last_emitted_payload_by_text[log_body] = payload_fingerprint
                    if len(_last_emitted_second_by_combat) > 2048:
                        _last_emitted_second_by_combat.pop(
                            next(iter(_last_emitted_second_by_combat)))
                    if len(_last_emitted_payload_by_combat) > 2048:
                        _last_emitted_payload_by_combat.pop(
                            next(iter(_last_emitted_payload_by_combat)))
                    if len(_last_emitted_second_by_text) > 2048:
                        _last_emitted_second_by_text.pop(
                            next(iter(_last_emitted_second_by_text)))
                    if len(_last_emitted_payload_by_text) > 2048:
                        _last_emitted_payload_by_text.pop(
                            next(iter(_last_emitted_payload_by_text)))
                diagnostics.increment("analyze.records_emitted")
                position = identifier_advance
            else:
                position = 2

        last_payload = payload[position:]


def open_pcap(file, output, ip_filter=True):
    if file is not None and not os.path.isfile(file):
        print("Invalid file", flush=True)
        return

    print("Reading " + file, flush=True)
    packets_analyzed = 0
    packets_total_state = {"value": 0}
    packets_total_lock = threading.Lock()

    def count_packets_read_ahead():
        counted = 0
        reader = None

        try:
            reader = RawPcapReader(file)
            for _packet_data, _packet_metadata in reader:
                counted += 1
                if counted == 1 or counted % 2000 == 0:
                    with packets_total_lock:
                        if counted > packets_total_state["value"]:
                            packets_total_state["value"] = counted
                    print(f"PCAP_TOTAL {counted}", flush=True)
        finally:
            if reader is not None:
                reader.close()
            with packets_total_lock:
                if counted > packets_total_state["value"]:
                    packets_total_state["value"] = counted
            print(f"PCAP_TOTAL {counted}", flush=True)

    counter_thread = threading.Thread(
        target=count_packets_read_ahead, daemon=True)
    counter_thread.start()

    def handle_packet(package):
        nonlocal packets_analyzed
        package_handler(package, output, ip_filter)
        packets_analyzed += 1
        with packets_total_lock:
            known_total = packets_total_state["value"]
        if (
            packets_analyzed == 1
            or packets_analyzed % 2000 == 0
        ):
            print(
                f"PCAP_PROGRESS {packets_analyzed} {known_total}", flush=True)
        if packets_analyzed % 10000 == 0:
            print(f"{packets_analyzed} packages analyzed.", flush=True)

    sniff(offline=file, prn=handle_packet, store=0)

    # Give the read-ahead thread a moment to publish the final total.
    counter_thread.join(timeout=2.0)
    with packets_total_lock:
        known_total = packets_total_state["value"]
    if known_total <= 0:
        known_total = packets_analyzed

    if packets_analyzed > 0:
        print(
            f"PCAP_PROGRESS {packets_analyzed} {known_total}", flush=True)

    print(
        f"Logs saved under: {output}\nYou can close this window now.", flush=True)


def list_interfaces(json_output=False):
    win_list = get_windows_if_list()
    intf_list = get_if_list()

    def _normalize_iface_token(value):
        text = str(value or "").strip()
        if not text:
            return ""

        guid_match = re.search(r"\{([0-9a-fA-F\-]+)\}", text)
        if guid_match:
            return guid_match.group(1).lower()

        return text.lower()

    available_tokens = set()
    for iface_id in intf_list:
        raw_id = str(iface_id or "").strip()
        if not raw_id:
            continue
        available_tokens.add(raw_id.lower())
        normalized = _normalize_iface_token(raw_id)
        if normalized:
            available_tokens.add(normalized)

    interfaces = []
    seen_values = set()

    for entry in win_list:
        guid = str(entry.get("guid") or "").strip()
        name = str(entry.get("name") or "").strip()
        description = str(entry.get("description") or "").strip()
        network_name = str(entry.get("network_name") or "").strip()
        mac = str(entry.get("mac") or "").strip()
        ips = [str(ip).strip()
               for ip in (entry.get("ips") or []) if str(ip).strip()]

        guid_token = _normalize_iface_token(guid)
        name_token = _normalize_iface_token(name)
        available = (
            (guid and guid.lower() in available_tokens)
            or (guid_token and guid_token in available_tokens)
            or (name and name.lower() in available_tokens)
            or (name_token and name_token in available_tokens)
        )

        if not available:
            continue

        value = guid or name
        if not value or value in seen_values:
            continue

        seen_values.add(value)

        label_parts = [name or guid]
        if description:
            label_parts.append(description)
        if network_name:
            label_parts.append(f"net={network_name}")
        if ips:
            label_parts.append(f"ips={','.join(ips[:3])}")

        interfaces.append({
            "value": value,
            "name": name,
            "guid": guid,
            "description": description,
            "network_name": network_name,
            "mac": mac,
            "ips": ips,
            "available": available,
            "label": " | ".join([part for part in label_parts if part]),
        })

    for iface_id in intf_list:
        iface_value = str(iface_id or "").strip()
        if not iface_value or iface_value in seen_values:
            continue

        seen_values.add(iface_value)
        interfaces.append({
            "value": iface_value,
            "name": iface_value,
            "guid": iface_value,
            "description": "",
            "network_name": "",
            "mac": "",
            "ips": [],
            "available": True,
            "label": iface_value,
        })

    if json_output:
        print(json.dumps(interfaces), flush=True)
    else:
        for item in interfaces:
            print(item.get("label") or item.get("value") or "", flush=True)


def start_sniff(output, all_interfaces=True, ip_filter=True, interface_name=None):
    start_live_ip_discovery_thread("analyzer-ip-discovery")
    try:
        print("Reading Network...", flush=True)
        win_list = get_windows_if_list()
        intf_list = get_if_list()
        guid_to_name = {entry["guid"]: entry["name"] for entry in win_list}
        names_allowed = [guid_to_name.get(entry) for entry in intf_list]
        names_allowed = list(filter(None, names_allowed))

        iface_value = None
        if interface_name:
            iface_value = interface_name
        elif len(names_allowed) > 0 and all_interfaces:
            iface_value = names_allowed

        sniff(
            filter="tcp",
            prn=lambda packet: package_handler(packet, output, ip_filter),
            store=0,
            iface=iface_value,
        )
    except Exception as exc:
        print("Error while reading network.", flush=True)
        print(exc, flush=True)
