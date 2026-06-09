import csv
import json
import re
import subprocess
from collections import Counter

from .. import config


def _collect_target_processes(process_name, include_exitlag=True):
    names = []
    primary = _normalize_process_name(process_name)
    if primary:
        names.append(primary)

    if include_exitlag:
        exitlag_name = "ExitLag.exe"
        if not any(name.lower() == exitlag_name.lower() for name in names):
            names.append(exitlag_name)

    return names


def _normalize_process_name(process_name):
    value = str(process_name or "").strip()
    if not value:
        return "BlackDesert64.exe"
    return value


def _run_command_safe(command):
    startupinfo = None
    creationflags = 0
    if hasattr(subprocess, "STARTUPINFO") and hasattr(subprocess, "STARTF_USESHOWWINDOW"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except OSError as error:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr=str(error),
        )


def _get_process_rows(process_name):
    command = [
        "tasklist",
        "/FI",
        f"IMAGENAME eq {process_name}",
        "/FO",
        "CSV",
        "/NH",
    ]
    result = _run_command_safe(command)

    rows = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("INFO:"):
            continue
        try:
            parsed = next(csv.reader([line]))
        except Exception:
            continue
        if len(parsed) < 2:
            continue
        rows.append(parsed)

    return rows


def _extract_process_pids(process_name):
    rows = _get_process_rows(process_name)
    pids = []
    for row in rows:
        image_name = str(row[0]).strip().strip('"')
        pid_text = str(row[1]).strip().strip('"')
        if image_name.lower() != process_name.lower():
            continue
        if not pid_text.isdigit():
            continue
        pids.append(int(pid_text))
    return sorted(set(pids))


def _parse_endpoint(endpoint_text):
    endpoint = str(endpoint_text or "").strip()
    if not endpoint:
        return "", 0

    if endpoint.startswith("[") and "]" in endpoint:
        host = endpoint[1:endpoint.index("]")]
        remainder = endpoint[endpoint.index("]") + 1:]
        port = 0
        if remainder.startswith(":") and remainder[1:].isdigit():
            port = int(remainder[1:])
        return host, port

    if ":" not in endpoint:
        return endpoint, 0

    host, port_text = endpoint.rsplit(":", 1)
    port = int(port_text) if port_text.isdigit() else 0
    return host, port


def _is_valid_public_ipv4(ip_value):
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip_value):
        return False

    octets = [int(part) for part in ip_value.split(".")]
    if any(part < 0 or part > 255 for part in octets):
        return False

    if ip_value.startswith("127."):
        return False
    if ip_value.startswith("10."):
        return False
    if ip_value.startswith("192.168."):
        return False
    if ip_value.startswith("169.254."):
        return False
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return False

    return True


def _extract_prefix(ip_value):
    if not _is_valid_public_ipv4(ip_value):
        return ""

    octets = ip_value.split(".")
    return ".".join(octets[:3])


def _collect_unique_remote_ips(connections):
    unique = []
    seen = set()
    for connection in connections or []:
        remote_ip = str(connection.get("remote_ip") or "").strip()
        if not _is_valid_public_ipv4(remote_ip):
            continue
        if remote_ip in seen:
            continue
        seen.add(remote_ip)
        unique.append(remote_ip)
    return unique


def _list_pid_connections(pid_to_process):
    if not pid_to_process:
        return []

    result = _run_command_safe(["netstat", "-ano", "-p", "tcp"])

    pid_set = set(pid_to_process.keys())
    connections = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("TCP"):
            continue

        parts = stripped.split()
        if len(parts) < 5:
            continue

        local_endpoint = parts[1]
        remote_endpoint = parts[2]
        state = parts[3]
        pid_text = parts[4]
        if not pid_text.isdigit():
            continue
        if state.upper() != "ESTABLISHED":
            continue

        pid = int(pid_text)
        if pid not in pid_set:
            continue

        remote_ip, remote_port = _parse_endpoint(remote_endpoint)
        local_ip, local_port = _parse_endpoint(local_endpoint)
        prefix = _extract_prefix(remote_ip)
        if not prefix:
            continue

        connections.append(
            {
                "pid": pid,
                "process_name": pid_to_process.get(pid, ""),
                "local_ip": local_ip,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "state": state,
                "prefix": prefix,
            }
        )

    return connections


def _build_summary(connections, min_hits=2, min_confidence=0.20):
    prefix_counts = Counter(connection["prefix"] for connection in connections)
    total = sum(prefix_counts.values())

    prefixes = []
    high_confidence_prefixes = []
    for prefix, count in prefix_counts.most_common():
        confidence = (count / total) if total > 0 else 0.0
        high_confidence = count >= min_hits and confidence >= min_confidence
        entry = {
            "prefix": prefix,
            "count": count,
            "confidence": round(confidence, 4),
            "high_confidence": high_confidence,
        }
        prefixes.append(entry)
        if high_confidence:
            high_confidence_prefixes.append(prefix)

    return {
        "total_connections": len(connections),
        "total_prefix_hits": total,
        "prefixes": prefixes,
        "high_confidence_prefixes": high_confidence_prefixes,
    }


def run(
    process_name="BlackDesert64.exe",
    include_exitlag=True,
    apply=False,
    apply_transient=False,
    min_hits=2,
    min_confidence=0.20,
    json_output=False,
):
    target_processes = _collect_target_processes(
        process_name, include_exitlag=include_exitlag)
    pid_to_process = {}
    for target in target_processes:
        for pid in _extract_process_pids(target):
            pid_to_process[pid] = target

    normalized_process_name = _normalize_process_name(process_name)
    pids = sorted(pid_to_process.keys())
    connections = _list_pid_connections(pid_to_process)

    # Separate ExitLag relay connections from direct BDO server connections so
    # that dynamic relay IPs are never written to config.ini.
    exitlag_connections = [
        c for c in connections
        if c.get("process_name", "").lower() == "exitlag.exe"
    ]
    bdo_connections = [
        c for c in connections
        if c.get("process_name", "").lower() != "exitlag.exe"
    ]

    resolved_min_hits = max(1, int(min_hits))
    resolved_min_confidence = max(0.0, min(1.0, float(min_confidence)))

    summary = _build_summary(
        connections,
        min_hits=resolved_min_hits,
        min_confidence=resolved_min_confidence,
    )
    bdo_summary = _build_summary(
        bdo_connections,
        min_hits=resolved_min_hits,
        min_confidence=resolved_min_confidence,
    )
    exitlag_summary = _build_summary(
        exitlag_connections,
        min_hits=1,
        min_confidence=0.0,
    )
    exitlag_endpoints = _collect_unique_remote_ips(exitlag_connections)

    # Persist only BDO-direct prefixes (stable server IPs) to config.ini.
    applied_ips = []
    if apply and bdo_summary["high_confidence_prefixes"]:
        applied_ips = config.persist_discovered_ips(
            bdo_summary["high_confidence_prefixes"])

    # ExitLag relay IPs are kept in-memory only — never written to disk.
    applied_transient_ips = []
    applied_transient_endpoints = []
    active_exitlag_endpoint = ""
    if apply_transient:
        config.add_transient_ips(exitlag_summary["high_confidence_prefixes"])
        config.add_transient_endpoints(exitlag_endpoints)
        active_exitlag_endpoint = config.refresh_active_exitlag_endpoint(
            exitlag_endpoints)
        applied_transient_ips = exitlag_summary["high_confidence_prefixes"]
        applied_transient_endpoints = exitlag_endpoints

    payload = {
        "process_name": normalized_process_name,
        "target_processes": target_processes,
        "pids": pids,
        "summary": summary,
        "connections": connections,
        "applied_ips": applied_ips,
        "transient_prefixes": exitlag_summary["high_confidence_prefixes"],
        "applied_transient_ips": applied_transient_ips,
        "transient_endpoints": exitlag_endpoints,
        "applied_transient_endpoints": applied_transient_endpoints,
        "active_exitlag_endpoint": active_exitlag_endpoint,
    }

    if json_output:
        print(json.dumps(payload), flush=True)
    else:
        print(f"Process: {normalized_process_name}", flush=True)
        if include_exitlag:
            print("Including process: ExitLag.exe", flush=True)
        print(
            f"PIDs: {', '.join(str(pid) for pid in pids) if pids else 'none'}", flush=True)
        print(
            f"Active public TCP connections: {summary['total_connections']}",
            flush=True,
        )
        for item in summary["prefixes"]:
            flag = " *" if item["high_confidence"] else ""
            print(
                f"  {item['prefix']} -> {item['count']} hits (confidence={item['confidence']:.2f}){flag}",
                flush=True,
            )

        if apply:
            if applied_ips:
                print(
                    "Applied/merged IP prefixes: " + ", ".join(applied_ips),
                    flush=True,
                )
            else:
                print(
                    "No high-confidence BDO-direct IP prefixes were applied.", flush=True)

        if apply_transient:
            if applied_transient_ips:
                print(
                    "Transient ExitLag IP prefixes (in-memory): " +
                    ", ".join(applied_transient_ips),
                    flush=True,
                )
            if applied_transient_endpoints:
                print(
                    "Transient ExitLag endpoints (in-memory): " +
                    ", ".join(applied_transient_endpoints),
                    flush=True,
                )
            if active_exitlag_endpoint:
                print(
                    "Active ExitLag endpoint: " + active_exitlag_endpoint,
                    flush=True,
                )

    return payload
