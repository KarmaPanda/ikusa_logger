"""Live sniff mode.

Streams TCP traffic from selected interfaces and forwards packets to the parser.
Starts shared live IP discovery so IP filtering can include dynamic ExitLag and
game endpoints.
"""

from .. import parser
from scapy.all import sniff
from .interface_capture import resolve_capture_interfaces
from .live_ip_discovery import start_live_ip_discovery_thread


def start_sniff(output, all_interfaces=True, ip_filter=True, interface_name=None):
    start_live_ip_discovery_thread("sniff-ip-discovery")
    print("Reading Network...", flush=True)
    iface_value = resolve_capture_interfaces(
        all_interfaces=all_interfaces,
        interface_name=interface_name,
    )
    sniff(
        filter="tcp",
        prn=lambda x: parser.package_handler(x, output, ip_filter=ip_filter),
        store=0,
        iface=iface_value,
    )
