"""CLI entrypoint for logger backend modes.

This module wires command-line arguments to runtime modes:
- sniff: live parse/write logs from network
- analyze: live calibration stream or pcap analyzer output
- open/file: replay pcap and write normal logs
- record: write separate pcap capture (no parsing)

Behavior notes:
- record defaults to IP filter enabled unless explicitly overridden.
- pcap replay disables IP filter because relay endpoints can differ from
    the original capture session.
"""

import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src import config, diagnostics
from src.options import status_check, open, sniff, record, update_config, discover_game
from src.options import analyzer

from argparse import ArgumentParser, BooleanOptionalAction
from datetime import date
import os.path
import os
from sys import exit


def _get_runtime_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_config_path():
    runtime_root = _get_runtime_root()
    candidates = [
        os.path.join(runtime_root, "config.ini"),
        os.path.join(os.getcwd(), "config.ini"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
    ]

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return candidates[0]


parser = ArgumentParser()
parser.add_argument("-f", "--file", dest="filename",
                    help="Instead of sniffing for bdo packages, it will use the given *.pcap file", metavar="FILE")
parser.add_argument("-o", "--output",
                    default=f"logger/.tmp/{date.today()}.log",
                    help="custom output file")
parser.add_argument("-r", "--record",
                    help="Record all of BDO's traffic and save it to a pcap file", action=BooleanOptionalAction)
parser.add_argument("-s", "--status",
                    help="Check the status of all requirements", action=BooleanOptionalAction)
parser.add_argument("-u", "--update",
                    help="Update the config", action=BooleanOptionalAction)
parser.add_argument("-a", "--analyze",
                    help="Analyze network", action=BooleanOptionalAction)
parser.add_argument("-i", "--allInterfaces",
                    help="Sniff all interfaces", action=BooleanOptionalAction)
parser.add_argument("--interface", dest="interface_name",
                    help="Sniff only the given interface name")
parser.add_argument("-p", "--ipFilter",
                    help="Enable Ip Filter to improve performance", action=BooleanOptionalAction)
parser.add_argument("--list-interfaces", dest="list_interfaces",
                    help="List sniffable interfaces", action=BooleanOptionalAction)
parser.add_argument("--json", dest="json_output", action="store_true",
                    help="Emit JSON output where supported")
parser.add_argument("--discover-game-ips", dest="discover_game_ips",
                    help="Discover active TCP remote IP prefixes for the running game process", action=BooleanOptionalAction)
parser.add_argument("--list-discovery-processes", dest="list_discovery_processes",
                    help="List running process names for discovery target selection", action=BooleanOptionalAction)
parser.add_argument("--game-process", dest="game_process", default="BlackDesert64.exe",
                    help="Process name to inspect for active connections")
parser.add_argument("--include-exitlag", dest="include_exitlag",
                    help="Include ExitLag.exe process connections during discovery", action=BooleanOptionalAction)
parser.add_argument("--apply-discovered-ips", dest="apply_discovered_ips",
                    help="Merge high-confidence discovered prefixes into config.ini [IP]", action=BooleanOptionalAction)
parser.add_argument("--discover-min-hits", dest="discover_min_hits", type=int, default=2,
                    help="Minimum connection hits for a discovered prefix to be considered high-confidence")
parser.add_argument("--discover-min-confidence", dest="discover_min_confidence", type=float, default=0.20,
                    help="Minimum confidence ratio [0-1] for discovered prefixes")
parser.set_defaults(include_exitlag=True)


args = parser.parse_args()

if args.list_interfaces:
    analyzer.list_interfaces(json_output=args.json_output)
    exit()

if args.list_discovery_processes:
    discover_game.list_process_names(json_output=args.json_output)
    exit()

config.init(_get_config_path())


def _init_diagnostics_if_needed():
    if args.status or args.update:
        return

    if not getattr(config.config, "diagnostics_enabled", False):
        return

    diagnostics.init(args.output)


_init_diagnostics_if_needed()


def _resolve_ip_filter(value):
    if isinstance(value, bool):
        return value
    return getattr(config.config, "ip_filter_enabled", True)


def _resolve_record_ip_filter(value):
    if isinstance(value, bool):
        return value
    # Separate PCAP capture defaults to filtered packets only.
    return True


resolved_ip_filter = _resolve_ip_filter(args.ipFilter)

if args.status:
    status_check.check_health()
    exit()
elif args.record:
    record.record(
        args.output,
        all_interfaces=bool(args.allInterfaces),
        ip_filter=_resolve_record_ip_filter(args.ipFilter),
        interface_name=args.interface_name,
    )
    exit()

elif args.update:
    update_config.update_config()
elif args.discover_game_ips:
    discover_game.run(
        process_name=args.game_process,
        include_exitlag=args.include_exitlag,
        apply=args.apply_discovered_ips,
        min_hits=args.discover_min_hits,
        min_confidence=args.discover_min_confidence,
        json_output=args.json_output,
    )
    exit()
elif args.analyze and args.filename != None:
    # IP filter is always disabled for PCAP replay: transient ExitLag
    # relay IPs from the original capture session are unknown at replay time.
    analyzer.open_pcap(args.filename, args.output, ip_filter=False)
    exit()
elif args.analyze:
    analyzer.start_sniff(args.output, args.allInterfaces,
                         resolved_ip_filter, args.interface_name)
    exit()
elif args.filename != None:
    # IP filter is always disabled for PCAP replay: transient ExitLag
    # relay IPs from the original capture session are unknown at replay time.
    open.open_pcap(args.filename, args.output, ip_filter=False)
    exit()
else:
    sniff.start_sniff(
        args.output,
        all_interfaces=bool(args.allInterfaces),
        ip_filter=resolved_ip_filter,
        interface_name=args.interface_name,
    )
    exit()
