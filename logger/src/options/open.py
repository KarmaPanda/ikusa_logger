import os
from scapy.all import sniff
from .. import parser


def open_pcap(file, output, ip_filter=True):
    if file != None and not os.path.isfile(file):
        print("Invalid file", flush=True)
        return
    print("Reading " + file, flush=True)
    packets_analyzed = 0

    def handle_packet(package):
        nonlocal packets_analyzed
        parser.package_handler(package, output, ip_filter=ip_filter)
        packets_analyzed += 1
        if packets_analyzed % 10000 == 0:
            print(f"{packets_analyzed} packages analyzed.", flush=True)

    # Stream packets from disk instead of loading the full capture into memory.
    # This avoids long UI stalls for large separate-record captures.
    sniff(offline=file, prn=handle_packet, store=0)

    print(
        f"Logs saved under: {output}\nYou can close this window now.", flush=True)
