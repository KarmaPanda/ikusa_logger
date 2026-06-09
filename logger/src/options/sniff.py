import threading
import time as _time_module
from .. import config, parser
from scapy.all import sniff
from . import discover_game
from .interface_capture import resolve_capture_interfaces

_EXITLAG_FAST_RETRY_SECONDS = 5
_EXITLAG_FAST_RETRY_MAX_SECONDS = 90
_EXITLAG_DISCOVERY_INTERVAL_SECONDS = 30


def _run_exitlag_discovery():
    """Run discover_game for ExitLag relay IPs; return True if any were found."""
    try:
        result = discover_game.run(
            include_exitlag=True, apply=False, apply_transient=True)
        return bool(result.get("transient_prefixes"))
    except Exception as exc:
        print(f"ExitLag IP discovery error: {exc}", flush=True)
        return False


def _start_exitlag_discovery_thread():
    """Discover ExitLag relay IPs before sniff starts, then refresh in background.

    Retries every {_EXITLAG_FAST_RETRY_SECONDS}s until connections are found
    (up to {_EXITLAG_FAST_RETRY_MAX_SECONDS}s), then slows to the steady
    {_EXITLAG_DISCOVERY_INTERVAL_SECONDS}s interval.  This handles the common
    case where ExitLag has not yet established its relay connections when the
    logger first starts.
    """
    found = _run_exitlag_discovery()

    def _loop():
        nonlocal found
        elapsed = 0
        while not found and elapsed < _EXITLAG_FAST_RETRY_MAX_SECONDS:
            _time_module.sleep(_EXITLAG_FAST_RETRY_SECONDS)
            elapsed += _EXITLAG_FAST_RETRY_SECONDS
            found = _run_exitlag_discovery()

        while True:
            _time_module.sleep(_EXITLAG_DISCOVERY_INTERVAL_SECONDS)
            _run_exitlag_discovery()

    thread = threading.Thread(
        target=_loop, daemon=True, name="exitlag-ip-discovery")
    thread.start()


def start_sniff(output, all_interfaces=True, ip_filter=True, interface_name=None):
    _start_exitlag_discovery_thread()
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
