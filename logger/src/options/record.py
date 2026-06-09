import os

from scapy.all import PcapWriter, sniff

from .interface_capture import resolve_capture_interfaces


def record(output, all_interfaces=True, ip_filter=False, interface_name=None):
    directory = os.path.dirname(output)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    print("Recording Network...", flush=True)

    iface_value = resolve_capture_interfaces(
        all_interfaces=all_interfaces,
        interface_name=interface_name,
    )

    writer = PcapWriter(output + ".pcap", append=True, sync=True)

    def handle_packet(packet):
        writer.write(packet)

    try:
        sniff(
            filter="tcp",
            prn=handle_packet,
            store=0,
            iface=iface_value,
        )
    finally:
        writer.close()
