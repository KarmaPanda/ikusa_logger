from time import localtime, strftime
from . import config
from scapy.all import wrpcap
import os
import re
from collections import deque

from . import diagnostics
from . import core_heuristics
from .packet_decode import extract_string


last_payload = ""
last_emitted_log = ""
last_emitted_signature = None
_recent_emitted_signatures = deque(maxlen=256)
_last_emitted_second_by_combat = {}
_last_emitted_second_by_text = {}
_last_emitted_payload_by_combat = {}
_last_emitted_payload_by_text = {}
DUPLICATE_SUPPRESSION_SECONDS = 2
identifier_regex = r"[56][0-9a-f]0100[0-9a-f]{4}"
_IDENTIFIER_HEX_PATTERN = re.compile(r"^[0-9a-f]{10}$")
_IDENTIFIER_FALLBACK_PATTERN = re.compile(identifier_regex)
_cached_identifier_value = None
_cached_identifier_pattern = None


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
    return [str(ip).strip() for ip in config.get_effective_ips() if str(ip).strip()]


def _is_server_ip_match(ip_value, prefixes):
    ip_text = str(ip_value or "").strip()
    if not ip_text:
        return False

    for prefix in prefixes:
        candidate = str(prefix or "").strip()
        if not candidate:
            continue
        if ip_text == candidate or ip_text.startswith(candidate + "."):
            return True
    return False


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


def _emit_legacy_fork_logs(payload, output, package_time, cfg, emitted_logs):
    global last_payload
    global last_emitted_log
    global last_emitted_signature
    global _recent_emitted_signatures
    global _last_emitted_second_by_combat
    global _last_emitted_second_by_text
    global _last_emitted_payload_by_combat
    global _last_emitted_payload_by_text

    current_payload = payload

    while last_payload != "" or cfg.identifier in current_payload:
        current_payload = last_payload + current_payload

        if cfg.identifier not in current_payload:
            last_payload = current_payload[-cfg.log_length:]
            diagnostics.increment("parser.buffers.no_identifier")
            return True

        start_index = current_payload.index(cfg.identifier)

        current_payload = current_payload[start_index:]
        if cfg.log_length > len(current_payload):
            last_payload = current_payload
            diagnostics.increment("parser.buffers.incomplete_log")
            return True

        timestamp = strftime("%I:%M:%S", localtime(int(package_time)))
        guild = extract_string(
            current_payload,
            cfg.guild_offset,
            cfg.name_length,
            decoding_strategy="latin1",
        )
        player_one = extract_string(
            current_payload,
            cfg.player_one_offset,
            cfg.name_length,
            decoding_strategy="latin1",
        )
        player_two = extract_string(
            current_payload,
            cfg.player_two_offset,
            cfg.name_length,
            decoding_strategy="latin1",
        )
        kill_flag_valid, is_kill = core_heuristics.parse_kill_flag(
            current_payload, cfg.kill_offset)
        if cfg.kill_offset is not None and not kill_flag_valid:
            diagnostics.increment("parser.records_rejected_invalid_kill_flag")
            current_payload = current_payload[len(cfg.identifier):]
            last_payload = ""
            continue

        if is_kill:
            log = f"[{timestamp}] {player_one} has killed {player_two} from {guild}"
        else:
            log = f"[{timestamp}] {player_one} died to {player_two} from {guild}"

        log_body = log.split("] ", 1)[1] if "] " in log else log
        payload_fingerprint = current_payload[:cfg.log_length]
        combat_signature = (
            bool(is_kill),
            player_one,
            player_two,
            guild,
        )
        current_signature = combat_signature + (timestamp,)
        event_second = _timestamp_to_seconds(timestamp)
        previous_second = _last_emitted_second_by_combat.get(combat_signature)
        previous_text_second = _last_emitted_second_by_text.get(log_body)
        duplicate_within_window = (
            previous_second is not None
            and event_second is not None
            and abs(event_second - previous_second) <= DUPLICATE_SUPPRESSION_SECONDS
            and _last_emitted_payload_by_combat.get(combat_signature) == payload_fingerprint
        )
        duplicate_text_within_window = (
            previous_text_second is not None
            and event_second is not None
            and abs(event_second - previous_text_second) <= DUPLICATE_SUPPRESSION_SECONDS
            and _last_emitted_payload_by_text.get(log_body) == payload_fingerprint
        )

        if (
            log == last_emitted_log
            or current_signature == last_emitted_signature
            or current_signature in _recent_emitted_signatures
            or duplicate_within_window
            or duplicate_text_within_window
        ):
            diagnostics.increment("parser.records_suppressed_duplicate")
            current_payload = current_payload[len(cfg.identifier):]
            last_payload = ""
            continue

        print(log, flush=True)
        emitted_logs.append(log)
        diagnostics.increment("parser.records_written")
        last_emitted_log = log
        last_emitted_signature = current_signature
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

        current_payload = current_payload[len(cfg.identifier):]
        last_payload = ""

    last_payload = current_payload
    return True


def package_handler(package, output, record=False, record_all_tcp=False, ip_filter=True):
    global last_payload
    global last_emitted_log
    global last_emitted_signature
    global _recent_emitted_signatures
    global _last_emitted_second_by_combat
    global _last_emitted_second_by_text
    global _last_emitted_payload_by_combat
    global _last_emitted_payload_by_text

    if "IP" not in package:
        return

    package_src = package["IP"].src
    package_dst = package["IP"].dst

    uses_tcp = "TCP" in package and hasattr(package["TCP"].payload, "load")
    captured_packet = False

    if record and record_all_tcp and uses_tcp:
        wrpcap(output + ".pcap", package, append=True)
        captured_packet = True

    server_ip_prefixes = _get_server_ip_prefixes()
    is_bdo_ip = (not ip_filter) or _is_server_ip_match(
        package_src, server_ip_prefixes
    ) or _is_server_ip_match(package_dst, server_ip_prefixes)

    if not (is_bdo_ip and uses_tcp):
        return

    if record and not captured_packet:
        wrpcap(output + ".pcap", package, append=True)

    cfg = config.config
    decoding_strategy = getattr(
        cfg,
        "decoding_strategy",
        "latin1" if getattr(cfg, "region", "ASIA") in (
            "NA", "EU") else "utf16le",
    )

    if decoding_strategy == "latin1":
        payload = bytes(package["TCP"].payload).hex()
        emitted_logs = []
        handled = _emit_legacy_fork_logs(
            payload, output, package.time, cfg, emitted_logs)

        if emitted_logs:
            directory = os.path.dirname(output)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            with open(output, "a", encoding="utf-8") as file:
                file.write("\n".join(emitted_logs) + "\n")

        if handled:
            return

    payload = last_payload + bytes(package["TCP"].payload).hex()
    emitted_logs = []

    while len(payload) >= cfg.log_length:
        matches = _find_identifier_matches(payload)
        if len(matches) == 0:
            last_payload = payload[-cfg.log_length:]
            diagnostics.increment("parser.buffers.no_identifier")
            return

        selected_match = _select_identifier_match(
            matches, len(payload), cfg.log_length)
        if selected_match is None:
            last_payload = payload[-cfg.log_length:]
            return

        payload = payload[selected_match.start():]
        if len(payload) < cfg.log_length:
            diagnostics.increment("parser.buffers.incomplete_log")
            break

        possible_log = payload[0:cfg.log_length]
        kill_flag_valid, is_kill = core_heuristics.parse_kill_flag(
            possible_log,
            cfg.kill_offset,
        )
        if cfg.kill_offset is not None and not kill_flag_valid:
            payload = payload[2:]
            diagnostics.increment("parser.records_rejected_invalid_kill_flag")
            continue

        roles = core_heuristics.select_best_roles(
            possible_log,
            cfg=cfg,
            decoding_strategy=decoding_strategy,
        )

        if not roles:
            payload = payload[2:]
            diagnostics.increment("parser.records_rejected_low_quality")
            continue

        if core_heuristics.looks_low_quality_roles(
            roles,
            decoding_strategy=decoding_strategy,
        ):
            payload = payload[len(selected_match.group(0)):]
            diagnostics.increment("parser.records_rejected_low_quality")
            continue

        if str(decoding_strategy or getattr(cfg, "decoding_strategy", "")).lower() != "latin1":
            emitted_candidates = core_heuristics.roles_to_emitted_candidates(
                possible_log,
                roles,
                cfg=cfg,
                decoding_strategy=decoding_strategy,
                max_candidates=5,
            )
            if len(emitted_candidates) < 3:
                diagnostics.increment("parser.records_rejected_low_quality")
                payload = payload[len(selected_match.group(0)):]
                continue

        timestamp = strftime("%I:%M:%S", localtime(int(package.time)))

        if is_kill:
            log = f"[{timestamp}] {roles['player_one']} has killed {roles['player_two']} from {roles['guild']}"
        else:
            log = f"[{timestamp}] {roles['player_one']} died to {roles['player_two']} from {roles['guild']}"
        log_body = log.split("] ", 1)[1] if "] " in log else log
        payload_fingerprint = possible_log

        combat_signature = (
            bool(is_kill),
            roles.get("player_one", ""),
            roles.get("player_two", ""),
            roles.get("guild", ""),
        )
        current_signature = combat_signature + (timestamp,)
        event_second = _timestamp_to_seconds(timestamp)
        previous_second = _last_emitted_second_by_combat.get(combat_signature)
        previous_text_second = _last_emitted_second_by_text.get(log_body)
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

        # Retransmits can repeat the same combat record within the same second.
        # Suppress exact log-line and role-signature duplicates consistently
        # across both latin1 legacy and utf16le paths.
        if (
            log == last_emitted_log
            or current_signature == last_emitted_signature
            or current_signature in _recent_emitted_signatures
            or duplicate_within_one_second
            or duplicate_text_within_one_second
        ):
            diagnostics.increment("parser.records_suppressed_duplicate")
            payload = payload[len(selected_match.group(0)):]
            continue

        print(log, flush=True)
        emitted_logs.append(log)
        last_emitted_log = log
        last_emitted_signature = current_signature
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

        diagnostics.increment("parser.records_written")
        payload = payload[len(selected_match.group(0)):]

    if emitted_logs:
        directory = os.path.dirname(output)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        with open(output, "a", encoding="utf-8") as file:
            file.write("\n".join(emitted_logs) + "\n")

    last_payload = payload
