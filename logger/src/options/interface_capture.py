from scapy.all import get_if_list
from scapy.arch.windows import get_windows_if_list


def resolve_capture_interfaces(all_interfaces=True, interface_name=None):
    if interface_name:
        return interface_name

    if not all_interfaces:
        return None

    try:
        win_list = get_windows_if_list()
        intf_list = get_if_list()
    except Exception:
        return None

    available_tokens = {str(entry or "").strip().lower()
                        for entry in intf_list if str(entry or "").strip()}
    names_allowed = []

    for entry in win_list:
        guid = str(entry.get("guid") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not name:
            continue

        guid_token = guid.lower()
        name_token = name.lower()
        if guid_token in available_tokens or name_token in available_tokens:
            names_allowed.append(name)

    unique_names = []
    seen = set()
    for name in names_allowed:
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_names.append(name)

    return unique_names or None
