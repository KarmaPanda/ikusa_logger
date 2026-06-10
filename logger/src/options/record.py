"""Separate PCAP capture mode.

Captures TCP traffic into a pcap file. When IP filtering is enabled, packets
are filtered against effective server prefixes (static config + transient
discovery updates) so captures stay compact and replay is faster.
"""

import os
import queue
import threading
import time as _time_module

from scapy.all import PcapWriter, sniff

from .. import config
from .interface_capture import resolve_capture_interfaces
from .live_ip_discovery import start_live_ip_discovery_thread


_IP_PREFIX_REFRESH_SECONDS = 3
_IP_FILTER_WARMUP_SECONDS = 20
_WRITE_QUEUE_MAX_PACKETS = 50000


def record(output, all_interfaces=True, ip_filter=True, interface_name=None):
    directory = os.path.dirname(output)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    print("Recording Network...", flush=True)

    iface_value = resolve_capture_interfaces(
        all_interfaces=all_interfaces,
        interface_name=interface_name,
    )

    if ip_filter:
        # Keep transient game/ExitLag prefixes fresh while recording.
        start_live_ip_discovery_thread("record-ip-discovery")

    writer = PcapWriter(output + ".pcap", append=True, sync=False)
    packet_queue = queue.Queue(maxsize=_WRITE_QUEUE_MAX_PACKETS)
    stop_writer = threading.Event()

    dropped_packets = 0
    accepted_packets = 0

    def writer_loop():
        while not stop_writer.is_set() or not packet_queue.empty():
            try:
                packet = packet_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                writer.write(packet)
            finally:
                packet_queue.task_done()

    writer_thread = threading.Thread(
        target=writer_loop,
        daemon=True,
        name="record-pcap-writer",
    )
    writer_thread.start()

    server_ip_prefixes = []
    last_ip_refresh = 0.0
    started_at = _time_module.time()

    def refresh_server_prefixes(force=False):
        nonlocal server_ip_prefixes
        nonlocal last_ip_refresh

        now = _time_module.time()
        if not force and (now - last_ip_refresh) < _IP_PREFIX_REFRESH_SECONDS:
            return

        server_ip_prefixes = [
            str(ip).strip()
            for ip in config.get_effective_ips()
            if str(ip).strip()
        ]
        last_ip_refresh = now

    if ip_filter:
        refresh_server_prefixes(force=True)

    def is_server_ip_match(ip_value):
        ip_text = str(ip_value or "").strip()
        if not ip_text:
            return False

        for prefix in server_ip_prefixes:
            if ip_text == prefix or ip_text.startswith(prefix + "."):
                return True
        return False

    def handle_packet(packet):
        nonlocal dropped_packets
        nonlocal accepted_packets

        if ip_filter:
            refresh_server_prefixes()

            # Fail open briefly at startup while discovery seeds prefixes,
            # preventing early valid game packets from being dropped.
            warmup_active = (
                not server_ip_prefixes and
                (_time_module.time() - started_at) < _IP_FILTER_WARMUP_SECONDS
            )
            if warmup_active:
                accepted_packets += 1
                try:
                    packet_queue.put_nowait(packet)
                except queue.Full:
                    dropped_packets += 1
                return

            if "IP" not in packet:
                return
            packet_src = packet["IP"].src
            packet_dst = packet["IP"].dst
            if not (is_server_ip_match(packet_src) or is_server_ip_match(packet_dst)):
                return

        accepted_packets += 1
        try:
            packet_queue.put_nowait(packet)
        except queue.Full:
            dropped_packets += 1

    try:
        sniff(
            filter="tcp",
            prn=handle_packet,
            store=0,
            iface=iface_value,
        )
    finally:
        stop_writer.set()
        writer_thread.join(timeout=5)
        writer.close()
        if dropped_packets > 0:
            print(
                (
                    "Warning: recorder dropped "
                    f"{dropped_packets} packets due to writer queue pressure "
                    f"(accepted={accepted_packets}, queue_max={_WRITE_QUEUE_MAX_PACKETS})."
                ),
                flush=True,
            )
