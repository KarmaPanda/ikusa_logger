import re
import unicodedata

from . import config
from .packet_decode import extract_string, looks_control_heavy_text


_THAI_NAME_REGEX = re.compile(
    r"^[\u0E01-\u0E3A\u0E40-\u0E4EA-Za-z0-9_-]{2,32}$")
_THAI_CHAR_REGEX = re.compile(r"[\u0E01-\u0E3A\u0E40-\u0E4E]")


def _is_thai_name_regex_match(name):
    """Return True when a name matches the stricter Thai-name fast path."""
    if not isinstance(name, str):
        return False
    if not _THAI_NAME_REGEX.fullmatch(name):
        return False
    if _THAI_CHAR_REGEX.search(name) is None:
        return False
    return any(unicodedata.category(ch).startswith("L") for ch in name)


def is_valid_name_char(ch):
    """Validate a single character against supported combat-name scripts."""
    if ch.isascii():
        return ch.isalnum() or ch in ("_", "-")

    codepoint = ord(ch)
    if 0x0E00 <= codepoint <= 0x0E7F:
        return True
    if 0xAC00 <= codepoint <= 0xD7A3:
        return True
    if unicodedata.category(ch).startswith("M"):
        return True
    return False


def is_valid_name(name):
    """General name validator used for normal emit-stage acceptance."""
    if not isinstance(name, str):
        return False
    if not (2 <= len(name) <= 32):
        return False
    if " " in name or "," in name:
        return False
    if _is_thai_name_regex_match(name):
        return True
    if looks_control_heavy_text(name):
        return False
    if not all(is_valid_name_char(ch) for ch in name):
        return False
    return any(unicodedata.category(ch).startswith("L") for ch in name)


def is_valid_name_strict(name):
    """Stricter name validator used for scoring and quality gates."""
    if not isinstance(name, str):
        return False
    if not (2 <= len(name) <= 32):
        return False
    if "," in name or " " in name:
        return False
    if _is_thai_name_regex_match(name):
        return True

    first_category = unicodedata.category(name[0])
    if not (first_category.startswith("L") or first_category.startswith("N")):
        return False

    has_letter = False
    for ch in name:
        if not is_valid_name_char(ch):
            return False
        if unicodedata.category(ch).startswith("L"):
            has_letter = True

    return has_letter


def validate_name_relaxed(name):
    """Permissive check used during name candidate *collection*.

    Intentionally loose — it must not reject candidates that a shifted/recovered
    offset window might produce, because dropping them below the 3-name threshold
    silently suppresses the whole log entry.  Blank-name filtering is handled at
    the emit stage (is_valid_name / is_valid_combat_name).
    """
    if not isinstance(name, str):
        return False
    if not (2 <= len(name) <= 32):
        return False
    if "," in name or " " in name:
        return False
    if _is_thai_name_regex_match(name):
        return True
    return all(is_valid_name_char(ch) for ch in name)


def validate_name_for_mode(name, validate_names=True):
    """Choose strict vs relaxed name validation based on runtime mode."""
    if validate_names:
        return is_valid_name(name)
    return validate_name_relaxed(name)


def _candidate_name_score(name, offset, center_offset):
    """Score a name candidate by strictness, length, and offset distance."""
    strict_bonus = 1000 if is_valid_name_strict(name) else 0
    return strict_bonus + (len(name) * 10) - abs(offset - center_offset)


def _extract_best_name_near(payload, center_offset, length, search_radius=28, decoding_strategy=None, region=None, validate_names=True):
    """Find the highest-scoring decodable name near an expected offset."""
    best_name = None
    best_offset = center_offset
    best_score = -10**9
    start = max(0, center_offset - search_radius)
    end = max(start, center_offset + search_radius)

    effective_strategy = decoding_strategy if decoding_strategy is not None else region

    for offset in range(start, end + 1, 2):
        name = extract_string(payload, offset, length,
                              decoding_strategy=effective_strategy, print_errors=True)
        if name == -1 or not validate_name_for_mode(name, validate_names):
            continue

        score = _candidate_name_score(name, offset, center_offset)
        if score > best_score:
            best_score = score
            best_name = name
            best_offset = offset

    return best_name, best_offset


def _extract_edge_shift_repair(payload, current_name, current_offset, length, decoding_strategy=None, search_radius=4, validate_names=True):
    """Repair one-code-unit boundary shifts that clip leading characters."""
    if not is_valid_name_strict(current_name):
        return None, current_offset

    current_folded = current_name.casefold()

    for delta in (-4, 4):
        if abs(delta) > search_radius:
            continue

        candidate_offset = current_offset + delta
        if candidate_offset < 0:
            continue

        candidate_name = extract_string(
            payload,
            candidate_offset,
            length,
            decoding_strategy=decoding_strategy,
            print_errors=True,
        )
        if candidate_name == -1 or not validate_name_for_mode(candidate_name, validate_names):
            continue
        if not is_valid_name_strict(candidate_name):
            continue

        candidate_folded = candidate_name.casefold()

        # When a nearby slice differs by exactly one leading character,
        # prefer the repaired boundary over the exact configured offset.
        if delta < 0 and len(candidate_folded) == len(current_folded) + 1:
            if candidate_folded[1:] == current_folded and (
                candidate_name[0].isupper() or current_name[0].islower()
            ):
                return candidate_name, candidate_offset
        if delta > 0 and len(candidate_folded) + 1 == len(current_folded):
            if (
                current_folded[1:] == candidate_folded
                and not current_name.isupper()
                and (
                    candidate_name[0].isupper()
                    or (len(current_name) > 1 and current_name[1].isupper())
                )
            ):
                return candidate_name, candidate_offset

    return None, current_offset


def resolve_kill_flag(payload, kill_offset):
    """Backward-compatible helper returning only the parsed kill boolean."""
    _is_valid, is_kill = parse_kill_flag(payload, kill_offset)
    return is_kill


def parse_kill_flag(payload, kill_offset):
    """Parse kill flag marker and return (is_valid, is_kill)."""
    if isinstance(kill_offset, int):
        flag = payload[kill_offset:kill_offset + 1]
        if flag in ("0", "1"):
            return True, flag == "1"
    return False, False


def resolve_offsets(payload, cfg=None, decoding_strategy=None, region=None, validate_names=True):
    """Resolve guild/player offsets with delta and nearby-repair fallback."""
    cfg = cfg or config.config
    effective_strategy = decoding_strategy if decoding_strategy is not None else region

    base = {
        "guild": extract_string(payload, cfg.guild_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True),
        "player_one": extract_string(payload, cfg.player_one_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True),
        "player_two": extract_string(payload, cfg.player_two_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True),
        "guild_offset": cfg.guild_offset,
        "player_one_offset": cfg.player_one_offset,
        "player_two_offset": cfg.player_two_offset,
        "kill_offset": getattr(cfg, "kill_offset", None),
        "delta": 0,
        "recovered": False,
    }

    def validator(value):
        return validate_name_for_mode(value, validate_names)

    candidates = []
    if validator(base["guild"]) and validator(base["player_one"]) and validator(base["player_two"]):
        candidates.append(base)

    for delta in range(-64, 66, 2):
        guild_offset = cfg.guild_offset + delta
        player_one_offset = cfg.player_one_offset + delta
        player_two_offset = cfg.player_two_offset + delta

        guild = extract_string(
            payload, guild_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True)
        player_one = extract_string(
            payload, player_one_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True)
        player_two = extract_string(
            payload, player_two_offset, cfg.name_length, decoding_strategy=effective_strategy, print_errors=True)
        kill_offset = cfg.kill_offset + delta if cfg.kill_offset is not None else None

        if not (validator(guild) and validator(player_one) and validator(player_two)):
            continue

        candidates.append({
            "guild": guild,
            "player_one": player_one,
            "player_two": player_two,
            "guild_offset": guild_offset,
            "player_one_offset": player_one_offset,
            "player_two_offset": player_two_offset,
            "kill_offset": kill_offset,
            "delta": delta,
            "recovered": False,
        })

    if not candidates:
        best = base.copy()
    else:
        def candidate_score(candidate):
            strict_count = sum(
                1
                for value in (candidate["guild"], candidate["player_one"], candidate["player_two"])
                if is_valid_name_strict(value)
            )
            length_score = sum(
                len(value)
                for value in (candidate["guild"], candidate["player_one"], candidate["player_two"])
                if isinstance(value, str)
            )
            return (strict_count, length_score, -abs(candidate["delta"]))

        best = max(candidates, key=candidate_score).copy()

    recovered = False

    for role in ("guild", "player_one", "player_two"):
        if is_valid_name_strict(best[role]):
            continue

        role_offset_key = f"{role}_offset"
        better_name, better_offset = _extract_best_name_near(
            payload,
            best[role_offset_key],
            cfg.name_length,
            search_radius=28,
            decoding_strategy=effective_strategy,
            validate_names=validate_names,
        )
        if better_name and is_valid_name_strict(better_name):
            best[role] = better_name
            best[role_offset_key] = better_offset
            recovered = True

    for role in ("guild", "player_one", "player_two"):
        role_offset_key = f"{role}_offset"
        center_offset = best[role_offset_key]
        current_name = best[role]
        if not is_valid_name_strict(current_name):
            continue

        repaired_name, repaired_offset = _extract_edge_shift_repair(
            payload,
            current_name,
            center_offset,
            cfg.name_length,
            decoding_strategy=effective_strategy,
            validate_names=validate_names,
        )
        if repaired_name and repaired_offset != center_offset:
            best[role] = repaired_name
            best[role_offset_key] = repaired_offset
            center_offset = repaired_offset
            current_name = repaired_name
            recovered = True

        better_name, better_offset = _extract_best_name_near(
            payload,
            center_offset,
            cfg.name_length,
            search_radius=28,
            decoding_strategy=effective_strategy,
            validate_names=validate_names,
        )
        if not (better_name and is_valid_name_strict(better_name)):
            continue

        current_score = _candidate_name_score(
            current_name, center_offset, center_offset)
        better_score = _candidate_name_score(
            better_name, better_offset, center_offset)

        is_shifted_duplicate = _looks_like_shifted_duplicate(
            current_name,
            better_name,
        )
        should_promote_shifted_repair = (
            is_shifted_duplicate
            and better_offset < center_offset
            and better_score >= current_score + 6
        )

        if better_score >= current_score + 40 or should_promote_shifted_repair:
            best[role] = better_name
            best[role_offset_key] = better_offset
            recovered = True

    best["recovered"] = recovered
    return best


def extract_core_candidates(payload, cfg=None, decoding_strategy=None, region=None, validate_names=True):
    """Extract validated core (player_one, player_two, guild) candidates."""
    resolved = resolve_offsets(
        payload,
        cfg=cfg,
        decoding_strategy=decoding_strategy,
        region=region,
        validate_names=validate_names,
    )
    core_candidates = [
        (resolved["player_one"], resolved["player_one_offset"]),
        (resolved["player_two"], resolved["player_two_offset"]),
        (resolved["guild"], resolved["guild_offset"]),
    ]

    is_valid = all(
        validate_name_for_mode(name, validate_names)
        for name, _ in core_candidates
    )
    if not is_valid:
        return [], resolved

    return core_candidates, resolved


def collect_names(possible_log, name_length=64, decoding_strategy=None):
    """Scan a payload window and collect relaxed-valid name candidates."""
    names = []
    i = 0
    max_len = len(possible_log)
    step = max(int(name_length), 2)

    while i <= max_len - 2:
        name = extract_string(
            possible_log,
            i,
            name_length,
            decoding_strategy=decoding_strategy,
        )
        if name == -1:
            i += 2
            continue

        if validate_name_relaxed(name):
            names.append((name, i))
            i += step
        else:
            i += 2

    return names


def pick_name_near_offset(collected, target_offset, used_indices):
    """Pick the best unused candidate nearest to a target offset."""
    candidates = []
    for idx, (name, offset) in enumerate(collected):
        # used_indices now stores selected offsets, not tuple indices.
        if any(abs(offset - used_offset) <= 16 for used_offset in used_indices):
            continue
        distance = abs(offset - target_offset)
        candidates.append((idx, name, offset, distance))

    if not candidates:
        return None, None

    def candidate_rank(item):
        _idx, name, _offset, distance = item
        strict = is_valid_name_strict(name)
        length = len(name) if isinstance(name, str) else 0
        return (
            (1000 if strict else 0) + (length * 20) - (distance * 2),
            length,
            -distance,
        )

    best_idx, _best_name, best_offset, _best_distance = max(
        candidates,
        key=candidate_rank,
    )

    used_indices.add(best_offset)
    return collected[best_idx]


def resolve_roles_from_collected(collected, cfg=None):
    """Map collected names to guild/player roles by configured offsets."""
    cfg = cfg or config.config
    used_indices = set()

    guild, guild_offset = pick_name_near_offset(
        collected, cfg.guild_offset, used_indices)
    player_one, player_one_offset = pick_name_near_offset(
        collected, cfg.player_one_offset, used_indices)
    player_two, player_two_offset = pick_name_near_offset(
        collected, cfg.player_two_offset, used_indices)

    if not (guild and player_one and player_two):
        return None

    return {
        "guild": guild,
        "player_one": player_one,
        "player_two": player_two,
        "guild_offset": guild_offset,
        "player_one_offset": player_one_offset,
        "player_two_offset": player_two_offset,
    }


def extract_roles_with_strategy(possible_log, cfg=None, decoding_strategy=None):
    """Extract role triplet using decoding-strategy-specific heuristics."""
    cfg = cfg or config.config

    if str(decoding_strategy or getattr(cfg, "decoding_strategy", "")).lower() != "latin1":
        core_candidates, resolved = extract_core_candidates(
            possible_log,
            cfg=cfg,
            decoding_strategy=decoding_strategy,
            validate_names=False,
        )
        if len(core_candidates) == 3 and all(
            isinstance(resolved.get(role), str) and validate_name_relaxed(
                resolved.get(role))
            for role in ("guild", "player_one", "player_two")
        ):
            return {
                "guild": resolved.get("guild"),
                "player_one": resolved.get("player_one"),
                "player_two": resolved.get("player_two"),
                "guild_offset": resolved.get("guild_offset"),
                "player_one_offset": resolved.get("player_one_offset"),
                "player_two_offset": resolved.get("player_two_offset"),
            }

        return None

    core_candidates, resolved = extract_core_candidates(
        possible_log,
        cfg=cfg,
        decoding_strategy=decoding_strategy,
        validate_names=True,
    )
    if len(core_candidates) == 3:
        return {
            "guild": resolved.get("guild"),
            "player_one": resolved.get("player_one"),
            "player_two": resolved.get("player_two"),
            "guild_offset": resolved.get("guild_offset"),
            "player_one_offset": resolved.get("player_one_offset"),
            "player_two_offset": resolved.get("player_two_offset"),
        }

    collected = collect_names(
        possible_log,
        name_length=cfg.name_length,
        decoding_strategy=decoding_strategy,
    )

    if len(collected) < 3:
        return None

    return resolve_roles_from_collected(collected, cfg=cfg)


def _extract_direct_name(possible_log, offset, name_length, decoding_strategy):
    """Decode a name at an exact offset without fallback search."""
    return extract_string(
        possible_log,
        offset,
        name_length,
        decoding_strategy=decoding_strategy,
    )


def _extract_direct_name_near(possible_log, offset, name_length, decoding_strategy):
    """Decode a name at offset with tiny +/-2 boundary tolerance."""
    for delta in (0, -2, 2):
        candidate_offset = offset + delta
        if candidate_offset < 0:
            continue

        name = _extract_direct_name(
            possible_log,
            candidate_offset,
            name_length,
            decoding_strategy,
        )
        if name == -1 or not isinstance(name, str) or not name:
            continue
        if not validate_name_relaxed(name):
            continue
        return name, candidate_offset

    return None, offset


def extract_roles_legacy_minimal(possible_log, cfg=None, decoding_strategy=None):
    """Legacy fast-path role extraction using direct configured offsets."""
    cfg = cfg or config.config

    guild, guild_offset = _extract_direct_name_near(
        possible_log, cfg.guild_offset, cfg.name_length, decoding_strategy)
    player_one, player_one_offset = _extract_direct_name_near(
        possible_log, cfg.player_one_offset, cfg.name_length, decoding_strategy)
    player_two, player_two_offset = _extract_direct_name_near(
        possible_log, cfg.player_two_offset, cfg.name_length, decoding_strategy)

    if not (guild and player_one and player_two):
        return None

    return {
        "guild": guild,
        "player_one": player_one,
        "player_two": player_two,
        "guild_offset": guild_offset,
        "player_one_offset": player_one_offset,
        "player_two_offset": player_two_offset,
    }


def _is_latin1_name(name):
    """Validate a latin1-style combat name with conservative rules."""
    if not isinstance(name, str):
        return False
    if len(name) < 3 or len(name) > 32:
        return False

    has_letter = False
    for ch in name:
        if ch.isascii():
            if ch.isalnum() or ch in ("_", "-", "'"):
                if ch.isalpha():
                    has_letter = True
                continue
            return False

        if ord(ch) > 255:
            return False
        category = unicodedata.category(ch)
        if not (category.startswith("L") or category.startswith("N")):
            return False
        if category.startswith("L"):
            has_letter = True

    return has_letter


def _looks_suspicious_latin1_name(name):
    """Detect latin1 token-like noise that should not pass combat-role gating."""
    if not isinstance(name, str):
        return True

    value = name.strip()
    if not value:
        return True

    # Reject long repeated-character runs (for example: ccccccncccc...).
    max_run = 1
    current_run = 1
    previous = ""
    for ch in value:
        if ch == previous:
            current_run += 1
            if current_run > max_run:
                max_run = current_run
        else:
            current_run = 1
            previous = ch

    if max_run >= 6:
        return True

    # Reject URL/token-like identifiers frequently seen in non-combat payloads.
    if len(value) >= 20:
        separator_count = value.count("_") + value.count("-")
        if separator_count >= 2:
            return True

    # Long latin1 names without vowels are usually decode garbage.
    if len(value) >= 12:
        lowered = value.lower()
        vowel_count = sum(1 for ch in lowered if ch in "aeiou")
        if vowel_count == 0:
            return True

    return False


def _looks_like_shifted_duplicate(name_a, name_b):
    """Detect one-character shift variants from boundary misalignment."""
    if not isinstance(name_a, str) or not isinstance(name_b, str):
        return False

    left = name_a.casefold()
    right = name_b.casefold()
    if left == right:
        return False

    if abs(len(left) - len(right)) != 1:
        return False

    shorter, longer = (left, right) if len(
        left) < len(right) else (right, left)
    if longer.startswith(shorter) or longer.endswith(shorter):
        return True

    return (
        longer[1:] == shorter
        or longer[:-1] == shorter
        or shorter[1:] == longer
        or shorter[:-1] == longer
    )


def looks_low_quality_roles(roles, decoding_strategy=None):
    """Return True when a role triplet looks too noisy to emit."""
    if not roles:
        return True

    names = [roles.get("player_one", ""), roles.get(
        "player_two", ""), roles.get("guild", "")]
    role_names = {
        "player_one": roles.get("player_one", ""),
        "player_two": roles.get("player_two", ""),
        "guild": roles.get("guild", ""),
    }
    lengths = [len(name) if isinstance(name, str) else 0 for name in names]
    short_count = sum(1 for length in lengths if length <= 2)
    strict_count = sum(
        1 for name in names
        if isinstance(name, str) and is_valid_name_strict(name)
    )
    valid_count = sum(
        1 for name in names
        if isinstance(name, str) and is_valid_name(name)
    )

    if short_count >= 2:
        return True
    if lengths[2] <= 2:
        return True

    # UTF-16LE/non-legacy decode can surface control-mark fragments that pass
    # relaxed collection but are not reliable combat names. Keep at least a
    # minimal strict/valid core threshold before emitting.
    if str(decoding_strategy or "").lower() != "latin1":
        if not all(is_valid_name(name) for name in names):
            return True

        # Non-legacy false positives frequently surface as 2-3 char fragments
        # or self-referential guild/name collisions in non-combat packets.
        if len(role_names["player_one"]) < 4 or len(role_names["player_two"]) < 4:
            return True

        guild_norm = str(role_names["guild"] or "").casefold()
        player_one_norm = str(role_names["player_one"] or "").casefold()
        player_two_norm = str(role_names["player_two"] or "").casefold()
        if guild_norm in {
            player_one_norm,
            player_two_norm,
        }:
            return True

        # Reject likely non-combat false positives where guild token embeds a
        # player token (e.g. ilvinzAnya vs zAnya) in the same packet.
        if len(player_one_norm) >= 4 and player_one_norm in guild_norm:
            return True
        if len(player_two_norm) >= 4 and player_two_norm in guild_norm:
            return True

        if _looks_like_shifted_duplicate(role_names["player_one"], role_names["player_two"]):
            return True
        if _looks_like_shifted_duplicate(role_names["guild"], role_names["player_one"]):
            return True
        if _looks_like_shifted_duplicate(role_names["guild"], role_names["player_two"]):
            return True

        if not is_valid_name_strict(role_names["guild"]):
            return True
        if strict_count < 2 and valid_count < 3:
            return True

    if str(decoding_strategy or "").lower() == "latin1":
        valid_count = 0
        for role in ("player_one", "player_two", "guild"):
            if _is_latin1_name(roles.get(role, "")):
                valid_count += 1

        # Keep records when at least 2 core slots look like plausible latin1
        # names; this avoids over-dropping valid packets with one noisy slot.
        if valid_count < 2:
            return True

        # Drop tokenized/non-combat noise when both player slots look suspicious
        # even if they technically satisfy latin1 character rules.
        if _looks_suspicious_latin1_name(role_names["player_one"]) and _looks_suspicious_latin1_name(role_names["player_two"]):
            return True

    return False


def name_quality_score(name):
    """Score a single name candidate for merge and fallback decisions."""
    if not isinstance(name, str):
        return -10**9

    score = len(name) * 4

    if is_valid_name_strict(name):
        score += 120
    elif is_valid_name(name):
        score += 60
    elif validate_name_relaxed(name):
        score += 20
    else:
        score -= 120

    if len(name) <= 2:
        score -= 100
    elif len(name) == 3:
        score -= 20

    has_thai = any(0x0E00 <= ord(ch) <= 0x0E7F for ch in name)
    has_hangul = any(0xAC00 <= ord(ch) <= 0xD7A3 for ch in name)
    if has_thai and has_hangul:
        score -= 120

    if len(name) <= 3 and len(set(name)) == 1:
        score -= 80

    return score


def roles_quality_score(roles):
    """Aggregate quality score for a role triplet candidate."""
    if not roles:
        return -10**9

    names = [roles.get("player_one", ""), roles.get(
        "player_two", ""), roles.get("guild", "")]
    strict_count = sum(
        1
        for name in names
        if isinstance(name, str) and is_valid_name_strict(name)
    )
    total_length = sum(len(name) for name in names if isinstance(name, str))
    short_count = sum(1 for name in names if not isinstance(
        name, str) or len(name) <= 2)
    name_quality_total = sum(name_quality_score(name) for name in names)
    return (strict_count * 100) + total_length - (short_count * 40) + name_quality_total


def _choose_better_role(role, primary, alternate):
    """Choose the better role field/value between two role candidates."""
    role_offset = f"{role}_offset"

    p_name = primary.get(role) if primary else None
    a_name = alternate.get(role) if alternate else None

    p_score = name_quality_score(p_name)
    a_score = name_quality_score(a_name)

    if a_score > p_score + 5:
        return a_name, alternate.get(role_offset)

    return p_name, primary.get(role_offset) if primary else None


def merge_role_candidates(primary, alternate):
    """Merge two role candidates by selecting best-per-role values."""
    if primary is None:
        return alternate
    if alternate is None:
        return primary

    merged = {}
    for role in ("guild", "player_one", "player_two"):
        name, offset = _choose_better_role(role, primary, alternate)
        merged[role] = name
        merged[f"{role}_offset"] = offset

    if all(merged.get(role) for role in ("guild", "player_one", "player_two")):
        return merged

    return primary if roles_quality_score(primary) >= roles_quality_score(alternate) else alternate


def select_best_roles(possible_log, cfg=None, decoding_strategy=None):
    """Top-level role resolver used by parser and analyzer paths."""
    cfg = cfg or config.config
    preferred_strategy = decoding_strategy
    if preferred_strategy is None:
        preferred_strategy = getattr(
            cfg,
            "decoding_strategy",
            "latin1" if getattr(cfg, "region", "ASIA") in (
                "NA", "EU") else "utf16le",
        )

    if preferred_strategy == "latin1":
        roles = extract_roles_legacy_minimal(
            possible_log,
            cfg=cfg,
            decoding_strategy=preferred_strategy,
        )
        return roles

    alternate_strategy = "latin1" if preferred_strategy == "utf16le" else "utf16le"

    roles_primary = extract_roles_with_strategy(
        possible_log,
        cfg=cfg,
        decoding_strategy=preferred_strategy,
    )

    if roles_primary is not None and not looks_low_quality_roles(
        roles_primary,
        decoding_strategy=preferred_strategy,
    ):
        return roles_primary

    if preferred_strategy != "latin1":
        return None

    roles_alternate = extract_roles_with_strategy(
        possible_log,
        cfg=cfg,
        decoding_strategy=alternate_strategy,
    )
    roles_merged = merge_role_candidates(roles_primary, roles_alternate)

    roles = roles_primary
    if roles_alternate is not None and (roles is None or roles_quality_score(roles_alternate) > roles_quality_score(roles) + 10):
        roles = roles_alternate
    if roles_merged is not None and (roles is None or roles_quality_score(roles_merged) > roles_quality_score(roles) + 5):
        roles = roles_merged

    if looks_low_quality_roles(roles, decoding_strategy=preferred_strategy):
        return None

    return roles


def roles_to_candidates(roles):
    """Convert resolved role dict into ordered (name, offset) tuples."""
    if not roles:
        return []

    return [
        (roles.get("player_one"), roles.get("player_one_offset")),
        (roles.get("player_two"), roles.get("player_two_offset")),
        (roles.get("guild"), roles.get("guild_offset")),
    ]


def roles_to_emitted_candidates(possible_log, roles, cfg=None, decoding_strategy=None, max_candidates=5):
    """Build emitted name list from core roles plus optional extras."""
    cfg = cfg or config.config
    core_candidates = roles_to_candidates(roles)
    if not core_candidates:
        return []

    emitted = [candidate for candidate in core_candidates if isinstance(
        candidate[0], str) and isinstance(candidate[1], int)]
    if len(emitted) >= max_candidates:
        return emitted[:max_candidates]

    collected = collect_names(
        possible_log,
        name_length=cfg.name_length,
        decoding_strategy=decoding_strategy,
    )

    used_offsets = {offset for _name, offset in emitted}

    for name, offset in collected:
        if not isinstance(name, str) or not isinstance(offset, int):
            continue

        nearby_names = [
            existing_name
            for existing_name, used_offset in emitted
            if isinstance(existing_name, str)
            and isinstance(used_offset, int)
            and abs(offset - used_offset) <= 4
        ]
        if any(existing_name.casefold() == name.casefold() for existing_name in nearby_names):
            continue

        emitted.append((name, offset))
        used_offsets.add(offset)

        if len(emitted) >= max_candidates:
            break

    return emitted
