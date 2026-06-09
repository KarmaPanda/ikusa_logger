import unicodedata

_ALLOWED_CONTROL_CHARS = {"\t", "\n", "\r"}
_LATIN1_STRATEGIES = {"LATIN1", "LATIN-1", "NA", "EU"}


def _is_likely_name_char(ch):
    if ch.isascii():
        return ch.isalnum() or ch in ("_", "-")

    codepoint = ord(ch)
    if 0x0E00 <= codepoint <= 0x0E7F:
        return True
    if 0xAC00 <= codepoint <= 0xD7A3:
        return True
    if unicodedata.category(ch).startswith("M"):
        return True
    return unicodedata.category(ch).startswith(("L", "N"))


def _looks_like_name_text(message):
    if not message:
        return False
    if " " in message or "," in message:
        return False
    if len(message) < 2:
        return False

    valid_chars = 0
    for ch in message:
        if _is_likely_name_char(ch):
            valid_chars += 1

    return valid_chars >= max(2, int(len(message) * 0.8))


def _decode_utf16_candidate(raw_bytes):
    utf16_end = len(raw_bytes)
    for index in range(0, max(len(raw_bytes) - 1, 0), 2):
        if raw_bytes[index:index + 2] == b"\x00\x00":
            utf16_end = index
            break

    utf16_bytes = raw_bytes[:utf16_end]
    if not utf16_bytes or len(utf16_bytes) % 2 != 0:
        return ""

    try:
        message = utf16_bytes.decode(
            "utf-16le", errors="ignore").rstrip("\x00")
    except UnicodeDecodeError:
        return ""

    if not message or looks_control_heavy_text(message):
        return ""
    if not _looks_like_name_text(message):
        return ""
    return message


def looks_control_heavy_text(message):
    if not message:
        return False

    message_length = len(message)
    # Any string with fewer than 5 chars cannot satisfy the >=20% threshold
    # with at least one control character.
    if message_length < 5:
        return False

    threshold = message_length * 0.2
    controls = 0
    category = unicodedata.category
    for ch in message:
        if category(ch).startswith("C") and ch not in _ALLOWED_CONTROL_CHARS:
            controls += 1
            if controls >= threshold:
                return True

    return False


def dec(raw_bytes, decoding_strategy=None, region=None):
    """
    Decode raw bytes to string using a merged cross-region strategy.
    """
    if not raw_bytes:
        return ""

    effective_strategy = decoding_strategy if decoding_strategy is not None else region
    normalized_strategy = str(effective_strategy or "").upper()

    # Mirror fork's NA/EU behavior: decode latin-1 and strip nulls.
    if normalized_strategy in _LATIN1_STRATEGIES or normalized_strategy.startswith("LATIN1"):
        try:
            message = raw_bytes.decode("latin-1").replace("\x00", "")
            if message and not looks_control_heavy_text(message):
                return message
            return message
        except UnicodeDecodeError:
            return raw_bytes.decode("utf-8", errors="ignore")

    # First, try UTF-16LE with 2-byte null termination for multi-language names.
    utf16_message = _decode_utf16_candidate(raw_bytes)
    if utf16_message:
        return utf16_message

    # Then parse as single-byte/null-terminated data.
    single_bytes = raw_bytes.split(b"\x00", 1)[0]
    if single_bytes:
        for encoding in ("utf-8", "cp874", "tis-620"):
            try:
                message = single_bytes.decode(encoding)
                if message and not looks_control_heavy_text(message):
                    return message
            except UnicodeDecodeError:
                pass

        try:
            message = single_bytes.decode("latin-1")
            if message and len(message) >= 2 and not looks_control_heavy_text(message):
                return message
        except UnicodeDecodeError:
            pass

        return single_bytes.decode("utf-8", errors="ignore")

    return ""


def _resolve_utf16_terminated_length(hex_payload, offset, length):
    max_end = min(len(hex_payload), offset + max(0, int(length)))
    # Keep byte alignment for hex slicing.
    if (max_end - offset) % 2 != 0:
        max_end -= 1

    if max_end <= offset:
        return -1

    # UTF-16LE null terminator is 0x0000 (4 hex chars) on code-unit boundaries.
    for pos in range(offset, max_end - 3, 4):
        if hex_payload[pos: pos + 4] == "0000":
            return pos - offset

    return max_end - offset


def extract_string(hex_payload, offset, length, decoding_strategy=None, region=None, print_errors=False):
    if offset % 2 != 0:
        return -1
    if hex_payload[offset: offset + 2] == "00":
        return -1

    try:
        effective_strategy = decoding_strategy if decoding_strategy is not None else region
        normalized_strategy = str(effective_strategy or "").upper()

        if normalized_strategy in _LATIN1_STRATEGIES or normalized_strategy.startswith("LATIN1"):
            actual_length = min(len(hex_payload) - offset, max(0, int(length)))
            if actual_length % 2 != 0:
                actual_length -= 1
        else:
            actual_length = _resolve_utf16_terminated_length(
                hex_payload, offset, length)

        if actual_length < 0:
            raise ValueError("Package too short")

        return dec(bytes.fromhex(hex_payload[offset: offset + actual_length]), decoding_strategy=effective_strategy)
    except ValueError as error:
        if print_errors:
            print(error, flush=True)
        return -1
