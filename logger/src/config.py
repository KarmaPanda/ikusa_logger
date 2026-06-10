from configparser import ConfigParser
from datetime import datetime
import re

# In-memory transient IP prefixes (e.g. ExitLag relay nodes).
# Never written to config.ini; replaced on each discovery refresh.
_transient_ips: list = []
_transient_endpoints: list = []
_active_exitlag_endpoint: str = ""


class Config (object):
    def __init__(self, filename="config.ini"):
        self.filename = filename
        self.config_parser = ConfigParser()
        self.config_parser.read(filename)
        self.config = dict(self.config_parser)

        if self.config.get("PACKAGE") == None:
            self.invalid = True
            return
        else:
            self.invalid = False

        # get ip addresses
        self.ips = list((self.config["IP"]).values())

        # get patch date (supports legacy key name)
        general = self.config.get("GENERAL", {})
        patch_raw = general.get("patch") or general.get("ppatch", "01.01.1970")
        self.patch = self._normalize_patch_date(patch_raw)

        # Legacy region key is retained for backward compatibility only.
        self.region = str(general.get("region", "ASIA")).strip().upper()
        if self.region not in ("NA", "EU", "SA", "KR", "ASIA"):
            self.region = "ASIA"

        strategy_raw = str(general.get(
            "decoding_strategy", "")).strip().lower()
        normalized_strategy = strategy_raw.replace("-", "")
        if normalized_strategy.startswith("latin1"):
            self.decoding_strategy = "latin1"
        elif strategy_raw in ("utf16le", "utf16", "utf-16le", "utf-16"):
            self.decoding_strategy = "utf16le"
        elif self.region in ("NA", "EU"):
            self.decoding_strategy = "latin1"
        else:
            self.decoding_strategy = "utf16le"
        self.diagnostics_enabled = self._parse_bool(
            general.get("diagnostics"),
            default=False,
        )
        self.ip_filter_enabled = self._parse_bool(
            general.get("ip_filter"),
            default=True,
        )

        discovery_section = self.config.get("DISCOVERY", {})
        self.discovery_processes = self._parse_discovery_processes(
            discovery_section)

        # get package informations
        self.package_config = self.config["PACKAGE"]
        self.identifier = str(self.package_config.get(
            "identifier", "")).strip().lower()
        self.guild_offset = int(self.package_config["guild"])
        self.player_one_offset = int(self.package_config["player_one"])
        self.player_two_offset = int(self.package_config["player_two"])
        self.kill_offset = self._parse_optional_int(
            self.package_config.get("kill"))
        self.log_length = int(self.package_config.get(
            "log_length", self.package_config.get("length", 600)))
        self.name_length = int(self.package_config.get("name_length", 64))

    @staticmethod
    def _parse_optional_int(value):
        if value is None:
            return None

        normalized = str(value).strip().lower()
        if normalized in ("", "undefined", "none", "null"):
            return None

        try:
            return int(normalized)
        except ValueError:
            return None

    @staticmethod
    def _parse_bool(value, default=False):
        if value is None:
            return default

        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    @staticmethod
    def _normalize_patch_date(value, fallback="01.01.1970"):
        text = str(value or "").strip()
        if not text:
            return fallback

        for pattern in ("%m.%d.%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                return parsed.strftime("%m.%d.%Y")
            except ValueError:
                continue

        return fallback

    @staticmethod
    def _parse_discovery_processes(discovery_section):
        parsed = []
        for key, value in (discovery_section or {}).items():
            normalized_key = str(key or "").strip().lower()
            if not (normalized_key.startswith("process") or normalized_key == "extra_processes"):
                continue

            for token in re.split(r"[,;\n\r]+", str(value or "")):
                name = str(token or "").strip()
                if not name:
                    continue
                if any(existing.lower() == name.lower() for existing in parsed):
                    continue
                parsed.append(name)

        return parsed

    def get_ips(self):
        return self.ips

    def get_guild_offset(self):
        return self.guild_offset

    def get_identifier(self):
        return self.identifier

    def get_player_one_offset(self):
        return self.player_one_offset

    def get_player_two_offset(self):
        return self.player_two_offset

    def get_kill_offset(self):
        return self.kill_offset

    def get_log_length(self):
        return self.log_length

    def get_name_length(self):
        return self.name_length

    def get_diagnostics_enabled(self):
        return self.diagnostics_enabled

    def get_ip_filter_enabled(self):
        return self.ip_filter_enabled

    def get_discovery_processes(self):
        return self.discovery_processes


def init(filename="config.ini"):
    global config
    config = Config(filename)
    return config


def _normalize_ip_prefix(prefix):
    value = str(prefix or "").strip()
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", value):
        return ""

    octets = value.split(".")
    for octet in octets:
        number = int(octet)
        if number < 0 or number > 255:
            return ""

    return value


def _normalize_ipv4_endpoint(ip_value):
    value = str(ip_value or "").strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
        return ""

    octets = value.split(".")
    for octet in octets:
        number = int(octet)
        if number < 0 or number > 255:
            return ""

    return value


def persist_discovered_ips(prefixes):
    global config

    if not config or getattr(config, "invalid", True):
        return []

    normalized_new = []
    for prefix in prefixes or []:
        normalized = _normalize_ip_prefix(prefix)
        if normalized and normalized not in normalized_new:
            normalized_new.append(normalized)

    if not normalized_new:
        return list(getattr(config, "ips", []) or [])

    existing = []
    for prefix in getattr(config, "ips", []) or []:
        normalized = _normalize_ip_prefix(prefix)
        if normalized and normalized not in existing:
            existing.append(normalized)

    merged = existing[:]
    for prefix in normalized_new:
        if prefix not in merged:
            merged.append(prefix)

    if not config.config_parser.has_section("IP"):
        config.config_parser.add_section("IP")

    # Replace section entries with deterministic server_N ordering.
    for option_name in list(config.config_parser.options("IP")):
        config.config_parser.remove_option("IP", option_name)

    for index, prefix in enumerate(merged, start=1):
        config.config_parser.set("IP", f"server_{index}", prefix)

    with open(config.filename, "w", encoding="utf-8") as handle:
        config.config_parser.write(handle)

    config.ips = merged
    return merged


def add_transient_ips(prefixes):
    """Replace in-memory transient IP prefixes (e.g. ExitLag relay nodes).

    Does NOT write to config.ini. Calling this on each discovery cycle ensures
    stale ExitLag relay IPs are dropped and replaced with the current ones.
    """
    global _transient_ips

    normalized = []
    for prefix in prefixes or []:
        norm = _normalize_ip_prefix(prefix)
        if norm and norm not in normalized:
            normalized.append(norm)

    _transient_ips = normalized


def get_transient_ips():
    return list(_transient_ips)


def add_transient_endpoints(endpoints):
    """Replace in-memory transient ExitLag remote endpoints (exact IPs)."""
    global _transient_endpoints

    normalized = []
    for endpoint in endpoints or []:
        norm = _normalize_ipv4_endpoint(endpoint)
        if norm and norm not in normalized:
            normalized.append(norm)

    _transient_endpoints = normalized


def get_transient_endpoints():
    return list(_transient_endpoints)


def refresh_active_exitlag_endpoint(candidates=None):
    """Select a single active ExitLag endpoint, preserving the current one when possible."""
    global _active_exitlag_endpoint

    normalized = []
    source = _transient_endpoints if candidates is None else candidates
    for value in source or []:
        endpoint = _normalize_ipv4_endpoint(value)
        if endpoint and endpoint not in normalized:
            normalized.append(endpoint)

    if _active_exitlag_endpoint in normalized:
        return _active_exitlag_endpoint

    _active_exitlag_endpoint = normalized[0] if normalized else ""
    return _active_exitlag_endpoint


def get_active_exitlag_endpoint():
    return _active_exitlag_endpoint


def get_effective_ips():
    """Return the union of config.ini IPs and in-memory transient IPs.

    Use this instead of config.ips wherever the IP filter is applied so that
    ExitLag relay prefixes (stored transiently) are respected without polluting
    the persistent config.
    """
    static = list(getattr(config, "ips", []) or [])
    return static + [ip for ip in _transient_ips if ip not in static]
