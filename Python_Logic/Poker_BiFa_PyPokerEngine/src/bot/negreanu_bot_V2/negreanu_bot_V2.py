from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any, Set
import re
from collections import Counter

from player_stats import PlayerStatsTracker
from bot.BotAction import BotAction


RANK_ORDER = "23456789TJQKA"
RANK_MAP = {
    "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9",
    "10": "T", "T": "T",
    "J": "J", "Q": "Q", "K": "K", "A": "A",
}


# =========================================================
# CONFIG
# =========================================================

@dataclass
class negreanu_V2_BotConfig:
    name: str = "smart_aggro"

    aggression: float = 0.72
    looseness: float = 0.60

    preflop_raise_threshold: float = 0.66
    preflop_call_threshold: float = 0.42

    postflop_raise_threshold: float = 0.73
    postflop_call_threshold: float = 0.47

    cheap_call_bonus: float = 0.08
    draw_bonus: float = 0.11
    top_pair_bonus: float = 0.09
    overpair_bonus: float = 0.15
    set_bonus: float = 0.20
    combo_draw_bonus: float = 0.12
    nut_flush_draw_bonus: float = 0.06

    steal_bonus_late: float = 0.08
    isolate_bonus: float = 0.06
    short_stack_push_bonus: float = 0.08
    big_stack_bully_bonus: float = 0.07
    cbet_bonus_dry: float = 0.06
    second_barrel_scare_bonus: float = 0.05
    fold_vs_heavy_resistance_penalty: float = 0.10


def make_profile(profile_name: str) -> negreanu_V2_BotConfig:
    name = (profile_name or "").strip().lower()

    if name == "nit_killer":
        return negreanu_V2_BotConfig(
            name="nit_killer",
            aggression=0.62,
            looseness=0.49,
            preflop_raise_threshold=0.71,
            preflop_call_threshold=0.43,
            postflop_raise_threshold=0.78,
            postflop_call_threshold=0.50,
            steal_bonus_late=0.03,
            isolate_bonus=0.03,
            short_stack_push_bonus=0.04,
            big_stack_bully_bonus=0.04,
            cbet_bonus_dry=0.03,
            second_barrel_scare_bonus=0.03,
            fold_vs_heavy_resistance_penalty=0.16,
        )

    if name == "blind_stealer":
        return negreanu_V2_BotConfig(
            name="blind_stealer",
            aggression=0.80,
            looseness=0.64,
            preflop_raise_threshold=0.61,
            preflop_call_threshold=0.39,
            postflop_raise_threshold=0.71,
            postflop_call_threshold=0.45,
            steal_bonus_late=0.13,
            isolate_bonus=0.08,
            short_stack_push_bonus=0.06,
            big_stack_bully_bonus=0.09,
            cbet_bonus_dry=0.09,
            second_barrel_scare_bonus=0.06,
            fold_vs_heavy_resistance_penalty=0.11,
        )

    if name == "shortstack_reaper":
        return negreanu_V2_BotConfig(
            name="shortstack_reaper",
            aggression=0.74,
            looseness=0.58,
            preflop_raise_threshold=0.64,
            preflop_call_threshold=0.42,
            postflop_raise_threshold=0.73,
            postflop_call_threshold=0.47,
            steal_bonus_late=0.09,
            isolate_bonus=0.07,
            short_stack_push_bonus=0.10,
            big_stack_bully_bonus=0.11,
            cbet_bonus_dry=0.06,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.10,
        )

    if name == "live_default":
        return negreanu_V2_BotConfig(
            name="live_default",
            aggression=0.71,
            looseness=0.57,
            preflop_raise_threshold=0.64,
            preflop_call_threshold=0.39,
            postflop_raise_threshold=0.72,
            postflop_call_threshold=0.43,
            cheap_call_bonus=0.10,
            draw_bonus=0.13,
            top_pair_bonus=0.11,
            overpair_bonus=0.16,
            steal_bonus_late=0.09,
            isolate_bonus=0.07,
            short_stack_push_bonus=0.07,
            big_stack_bully_bonus=0.08,
            cbet_bonus_dry=0.07,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.08,
        )

    if name == "tag_grinder":
        return negreanu_V2_BotConfig(
            name="tag_grinder",
            aggression=0.66,
            looseness=0.52,
            preflop_raise_threshold=0.67,
            preflop_call_threshold=0.40,
            postflop_raise_threshold=0.74,
            postflop_call_threshold=0.45,
            cheap_call_bonus=0.08,
            draw_bonus=0.10,
            top_pair_bonus=0.10,
            overpair_bonus=0.16,
            set_bonus=0.20,
            combo_draw_bonus=0.11,
            nut_flush_draw_bonus=0.05,
            steal_bonus_late=0.06,
            isolate_bonus=0.05,
            short_stack_push_bonus=0.06,
            big_stack_bully_bonus=0.05,
            cbet_bonus_dry=0.06,
            second_barrel_scare_bonus=0.04,
            fold_vs_heavy_resistance_penalty=0.09,
        )

    if name == "balanced_reg":
        return negreanu_V2_BotConfig(
            name="balanced_reg",
            aggression=0.72,
            looseness=0.58,
            preflop_raise_threshold=0.64,
            preflop_call_threshold=0.40,
            postflop_raise_threshold=0.72,
            postflop_call_threshold=0.44,
            cheap_call_bonus=0.09,
            draw_bonus=0.12,
            top_pair_bonus=0.11,
            overpair_bonus=0.16,
            set_bonus=0.20,
            combo_draw_bonus=0.12,
            nut_flush_draw_bonus=0.06,
            steal_bonus_late=0.09,
            isolate_bonus=0.07,
            short_stack_push_bonus=0.07,
            big_stack_bully_bonus=0.08,
            cbet_bonus_dry=0.07,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.08,
        )

    if name == "live_exploiter":
        return negreanu_V2_BotConfig(
            name="live_exploiter",
            aggression=0.77,
            looseness=0.64,
            preflop_raise_threshold=0.61,
            preflop_call_threshold=0.38,
            postflop_raise_threshold=0.70,
            postflop_call_threshold=0.43,
            cheap_call_bonus=0.10,
            draw_bonus=0.14,
            top_pair_bonus=0.12,
            overpair_bonus=0.17,
            set_bonus=0.21,
            combo_draw_bonus=0.14,
            nut_flush_draw_bonus=0.07,
            steal_bonus_late=0.12,
            isolate_bonus=0.09,
            short_stack_push_bonus=0.07,
            big_stack_bully_bonus=0.10,
            cbet_bonus_dry=0.09,
            second_barrel_scare_bonus=0.06,
            fold_vs_heavy_resistance_penalty=0.07,
        )

    if name == "threebet_hunter":
        return negreanu_V2_BotConfig(
            name="threebet_hunter",
            aggression=0.82,
            looseness=0.60,
            preflop_raise_threshold=0.62,
            preflop_call_threshold=0.39,
            postflop_raise_threshold=0.71,
            postflop_call_threshold=0.44,
            cheap_call_bonus=0.08,
            draw_bonus=0.12,
            top_pair_bonus=0.10,
            overpair_bonus=0.16,
            set_bonus=0.20,
            combo_draw_bonus=0.12,
            nut_flush_draw_bonus=0.06,
            steal_bonus_late=0.11,
            isolate_bonus=0.07,
            short_stack_push_bonus=0.08,
            big_stack_bully_bonus=0.09,
            cbet_bonus_dry=0.08,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.12,
        )

    if name == "sticky_postflop":
        return negreanu_V2_BotConfig(
            name="sticky_postflop",
            aggression=0.69,
            looseness=0.59,
            preflop_raise_threshold=0.65,
            preflop_call_threshold=0.37,
            postflop_raise_threshold=0.70,
            postflop_call_threshold=0.40,
            cheap_call_bonus=0.12,
            draw_bonus=0.15,
            top_pair_bonus=0.13,
            overpair_bonus=0.17,
            set_bonus=0.21,
            combo_draw_bonus=0.15,
            nut_flush_draw_bonus=0.08,
            steal_bonus_late=0.08,
            isolate_bonus=0.06,
            short_stack_push_bonus=0.06,
            big_stack_bully_bonus=0.07,
            cbet_bonus_dry=0.06,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.06,
        )

    if name == "shortstack_bully":
        return negreanu_V2_BotConfig(
            name="shortstack_bully",
            aggression=0.78,
            looseness=0.61,
            preflop_raise_threshold=0.63,
            preflop_call_threshold=0.41,
            postflop_raise_threshold=0.72,
            postflop_call_threshold=0.45,
            cheap_call_bonus=0.09,
            draw_bonus=0.12,
            top_pair_bonus=0.10,
            overpair_bonus=0.16,
            set_bonus=0.20,
            combo_draw_bonus=0.12,
            nut_flush_draw_bonus=0.06,
            steal_bonus_late=0.10,
            isolate_bonus=0.08,
            short_stack_push_bonus=0.12,
            big_stack_bully_bonus=0.12,
            cbet_bonus_dry=0.07,
            second_barrel_scare_bonus=0.05,
            fold_vs_heavy_resistance_penalty=0.09,
        )

    if name == "calling_station_punisher":
        return negreanu_V2_BotConfig(
            name="calling_station_punisher",
            aggression=0.74,
            looseness=0.56,
            preflop_raise_threshold=0.64,
            preflop_call_threshold=0.39,
            postflop_raise_threshold=0.74,
            postflop_call_threshold=0.44,
            cheap_call_bonus=0.08,
            draw_bonus=0.11,
            top_pair_bonus=0.13,
            overpair_bonus=0.18,
            set_bonus=0.22,
            combo_draw_bonus=0.11,
            nut_flush_draw_bonus=0.05,
            steal_bonus_late=0.08,
            isolate_bonus=0.09,
            short_stack_push_bonus=0.06,
            big_stack_bully_bonus=0.07,
            cbet_bonus_dry=0.05,
            second_barrel_scare_bonus=0.04,
            fold_vs_heavy_resistance_penalty=0.07,
        )

    return negreanu_V2_BotConfig(name=name or "smart_aggro")


# =========================================================
# CARD HELPERS
# =========================================================

def parse_card(card) -> Tuple[str, str]:
    text = str(card).strip()

    patterns = [
        r"\(([2-9TJQKA]|10)([cdhs])\)",   # KING OF SPADES (Ks)
        r"\[([2-9TJQKA]|10)([cdhs])\]",   # [Qd]
        r"^([2-9TJQKA]|10)([cdhs])$",     # Qd
        r"([2-9TJQKA]|10)([cdhs])",       # fallback
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            rank = m.group(1).upper()
            suit = m.group(2).lower()
            return rank, suit

    raise ValueError(f"Formato carta non riconosciuto: {text!r}")


def rank_to_index(rank: str) -> int:
    return RANK_ORDER.index(RANK_MAP.get(str(rank).upper(), "2"))


def card_rank_index(card) -> int:
    rank, _ = parse_card(card)
    return rank_to_index(rank)


def card_suit(card) -> str:
    _, suit = parse_card(card)
    return suit


def _is_pocket_pair(cards) -> bool:
    if not isinstance(cards, (list, tuple)) or len(cards) != 2:
        return False
    try:
        return card_rank_index(cards[0]) == card_rank_index(cards[1])
    except Exception:
        return False


# =========================================================
# GENERIC HELPERS
# =========================================================

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_get(obj, name: str, default=None):
    return getattr(obj, name, default)


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_pos(value: Any) -> str:
    return str(value or "").strip().upper()


def _all_rank_indices(cards) -> List[int]:
    return [card_rank_index(c) for c in cards]


def _all_suits(cards) -> List[str]:
    return [card_suit(c) for c in cards]


def _avg_stat(opponents: List[Dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = []
    for opp in opponents:
        if opp.get(key) is not None:
            values.append(_safe_float(opp.get(key), default))
    if not values:
        return default
    return sum(values) / len(values)


def _effective_opponent_profile(opponents: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "avg_vpip": _avg_stat(opponents, "vpip", 0.28),
        "avg_pfr": _avg_stat(opponents, "pfr", 0.18),
        "avg_af": _avg_stat(opponents, "af", 1.5),
        "avg_fold_to_raise": _avg_stat(opponents, "fold_to_raise", 0.35),
        "avg_fold_to_cbet": _avg_stat(opponents, "fold_to_cbet", 0.35),
        "avg_wtsd": _avg_stat(opponents, "wtsd", 0.30),
        "avg_three_bet": _avg_stat(opponents, "3bet", 0.10),
        "avg_stack_bb": _avg_stat(opponents, "stack_bb", 30.0),
    }


def _count_unknown_opponents(opponents: List[Dict[str, Any]], min_hands: int = 8) -> int:
    count = 0
    for opp in opponents:
        hands_played = _safe_int(opp.get("hands_played", 0), 0)
        if hands_played < min_hands:
            count += 1
    return count


def _opponents_in_positions(opponents: List[Dict[str, Any]], positions: Set[str]) -> List[Dict[str, Any]]:
    pos_set = {_norm_pos(p) for p in positions}
    return [
        opp
        for opp in opponents
        if _norm_pos(opp.get("position", "")) in pos_set
    ]


def _is_weak_passive_player(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    return (
        _safe_float(snapshot.get("vpip", 0.0), 0.0) >= 0.32
        and _safe_float(snapshot.get("pfr", 0.0), 0.0) <= 0.18
        and _safe_float(snapshot.get("af", 0.0), 0.0) <= 1.8
    )


def _is_loose_aggressive_player(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    return (
        _safe_float(snapshot.get("vpip", 0.0), 0.0) >= 0.30
        and (
            _safe_float(snapshot.get("af", 0.0), 0.0) >= 2.3
            or _safe_float(snapshot.get("pfr", 0.0), 0.0) >= 0.24
            or _safe_float(snapshot.get("3bet", 0.0), 0.0) >= 0.14
        )
    )


def _count_weak_limpers(opponents: List[Dict[str, Any]]) -> int:
    return sum(
        1
        for opp in opponents
        if _norm_text(opp.get("last_action_kind")) == "call"
        and _norm_text(opp.get("last_action_street")) == "preflop"
        and _is_weak_passive_player(opp)
    )


def _count_short_stacks(opponents: List[Dict[str, Any]], threshold_bb: float = 15.0) -> int:
    count = 0
    for opp in opponents:
        stack_bb = _safe_float(opp.get("stack_bb", 0.0), 0.0)
        if 0 < stack_bb <= threshold_bb:
            count += 1
    return count


def _count_big_stacks(opponents: List[Dict[str, Any]], threshold_bb: float = 45.0) -> int:
    count = 0
    for opp in opponents:
        stack_bb = _safe_float(opp.get("stack_bb", 0.0), 0.0)
        if stack_bb >= threshold_bb:
            count += 1
    return count


def _is_late_position(position: str) -> bool:
    return _norm_pos(position) in {"HJ", "CO", "BTN"}


def _is_early_position(position: str) -> bool:
    return _norm_pos(position) in {"UTG", "UTG+1", "EP"}


def _is_blind(position: str) -> bool:
    return _norm_pos(position) in {"SB", "BB"}


def _has_heavy_preflop_resistance(stats_context: Optional[Dict[str, Any]]) -> bool:
    if not stats_context:
        return False
    return _safe_int(stats_context.get("raise_count_before_action", 0), 0) >= 2


def _has_strong_made_hand(info: Dict[str, Any]) -> bool:
    return any([
        info["straight_with_hole"],
        info["flush_with_hole"],
        info["full_house_with_hole"],
        info["quads_with_hole"],
        info["set_made"],
        info["trips_with_hole"],
        info["two_pair_with_hole"],
        info["overpair"],
    ])


def _is_open_spot(stats_context: Optional[Dict[str, Any]]) -> bool:
    if not stats_context:
        return False
    return _safe_int(stats_context.get("raise_count_before_action", 0), 0) == 0


def _is_isolation_spot(stats_context: Optional[Dict[str, Any]], call_amount: int) -> bool:
    if not stats_context:
        return False
    return _safe_int(stats_context.get("raise_count_before_action", 0), 0) == 1 and call_amount > 0


def _estimate_stack_bb(stack: int, stats_context: Optional[Dict[str, Any]]) -> float:
    if not stats_context:
        return 0.0

    bb = _safe_float(stats_context.get("big_blind", 0.0), 0.0)
    if bb > 0:
        return stack / bb

    return _safe_float(stats_context.get("hero_stack_bb", 0.0), 0.0)


def _estimate_effective_stack_bb(hero_stack_bb: float, stats_context: Optional[Dict[str, Any]]) -> float:
    if not stats_context:
        return hero_stack_bb

    eff = _safe_float(stats_context.get("effective_stack_bb", 0.0), 0.0)
    if eff > 0:
        return eff

    opponents = stats_context.get("opponents", [])
    opp_stacks = []
    for opp in opponents:
        s = _safe_float(opp.get("stack_bb", 0.0), 0.0)
        if s > 0:
            opp_stacks.append(s)

    if not opp_stacks:
        return hero_stack_bb

    return min(hero_stack_bb, min(opp_stacks))


def _estimate_pot(state, stats_context: Optional[Dict[str, Any]]) -> float:
    if stats_context is not None and stats_context.get("pot") is not None:
        return _safe_float(stats_context.get("pot"), 0.0)

    return _safe_float(_safe_get(state, "pot", 0.0), 0.0)


def _pot_odds_required(call_amount: int, pot: float) -> float:
    if call_amount <= 0:
        return 0.0
    total = pot + call_amount
    if total <= 0:
        return 1.0
    return call_amount / total


# =========================================================
# PREFLOP
# =========================================================

def _normalize_hole(cards) -> Tuple[int, int, bool]:
    r1 = card_rank_index(cards[0])
    r2 = card_rank_index(cards[1])
    suited = card_suit(cards[0]) == card_suit(cards[1])
    return max(r1, r2), min(r1, r2), suited


def preflop_strength(
    cards,
    position: str = "",
    players_in_hand: int = 6,
    stack_bb: float = 30.0,
) -> float:
    hi, lo, suited = _normalize_hole(cards)
    pair = hi == lo
    gap = hi - lo

    score = 0.0

    if pair:
        base_pair_scores = {
            0: 0.44,
            1: 0.46,
            2: 0.48,
            3: 0.50,
            4: 0.54,
            5: 0.58,
            6: 0.63,
            7: 0.69,
            8: 0.75,
            9: 0.82,
            10: 0.89,
            11: 0.95,
            12: 0.99,
        }
        score = base_pair_scores.get(hi, 0.44)
    else:
        score += hi * 0.040
        score += lo * 0.022

        broadways = sum(1 for r in (hi, lo) if r >= rank_to_index("T"))
        if broadways == 2:
            score += 0.12
        elif broadways == 1:
            score += 0.05

        if suited:
            score += 0.06

        if gap == 1:
            score += 0.08
        elif gap == 2:
            score += 0.04
        elif gap >= 4:
            score -= 0.05

        if hi == rank_to_index("A") and suited:
            score += 0.05

        if suited and hi >= rank_to_index("J") and lo >= rank_to_index("9"):
            score += 0.04

        if not suited and hi < rank_to_index("J") and gap >= 3:
            score -= 0.06

        if lo <= rank_to_index("5") and gap >= 5 and not suited:
            score -= 0.05

    if _is_late_position(position):
        score += 0.04
    elif _is_early_position(position):
        score -= 0.04
    elif _is_blind(position):
        score -= 0.02

    if players_in_hand <= 4:
        score += 0.04
    elif players_in_hand >= 7:
        score -= 0.02

    if stack_bb > 0:
        if stack_bb <= 12:
            if not pair and suited and gap <= 2 and hi <= rank_to_index("T"):
                score -= 0.06
            if hi >= rank_to_index("A"):
                score += 0.04
            if hi >= rank_to_index("K") and lo >= rank_to_index("T"):
                score += 0.03
            if pair:
                score += 0.03
        elif stack_bb >= 40:
            if suited and gap <= 2:
                score += 0.03

    return _clamp(score, 0.0, 1.0)


def _hole_features(cards) -> Tuple[int, int, bool, bool, int]:
    hi, lo, suited = _normalize_hole(cards)
    return hi, lo, suited, hi == lo, hi - lo


def _is_open_raise_candidate(
    cards,
    position: str,
    effective_stack_bb: float,
    players_in_hand: int,
    strength: float,
) -> bool:
    hi, lo, suited, pair, gap = _hole_features(cards)
    late = _is_late_position(position)
    early = _is_early_position(position)
    broadway_count = sum(1 for rank in (hi, lo) if rank >= rank_to_index("T"))
    button = _norm_pos(position) == "BTN"
    cutoff = _norm_pos(position) == "CO"

    if pair:
        return True
    if hi == rank_to_index("A"):
        if suited:
            return not early or lo >= rank_to_index("4")
        if button:
            return lo >= rank_to_index("2")
        if cutoff:
            return lo >= rank_to_index("5")
        return lo >= rank_to_index("9") or (late and lo >= rank_to_index("7"))
    if hi >= rank_to_index("K") and lo >= rank_to_index("T"):
        return True
    if hi >= rank_to_index("Q") and lo >= rank_to_index("J"):
        return True
    if button and suited and hi >= rank_to_index("J") and lo >= rank_to_index("7") and gap <= 3:
        return True
    if button and hi >= rank_to_index("J") and lo >= rank_to_index("7") and gap <= 1:
        return True
    if cutoff and suited and hi >= rank_to_index("J") and lo >= rank_to_index("7") and gap <= 2:
        return True
    if suited and gap <= 1 and hi >= rank_to_index("8") and not early and effective_stack_bb >= 18:
        return True
    if suited and hi >= rank_to_index("J") and lo >= rank_to_index("8") and not early:
        return True
    if late and suited and hi >= rank_to_index("T") and lo >= rank_to_index("7") and gap <= 2 and effective_stack_bb >= 16:
        return True
    if (
        late
        and strength >= 0.64
        and players_in_hand <= 5
        and (
            suited
            or hi == rank_to_index("A")
            or broadway_count >= 2
            or (broadway_count == 1 and lo >= rank_to_index("8") and gap <= 1)
        )
    ):
        return True
    return False


def _is_value_reraise_candidate(
    cards,
    effective_stack_bb: float,
    strength: float,
) -> bool:
    hi, lo, suited, pair, gap = _hole_features(cards)
    if pair:
        if hi >= rank_to_index("9"):
            return True
        return effective_stack_bb <= 12 and hi >= rank_to_index("6")
    if hi == rank_to_index("A") and lo >= rank_to_index("J"):
        return True
    if hi == rank_to_index("A") and suited and lo >= rank_to_index("5"):
        return True
    if suited and hi >= rank_to_index("K") and lo >= rank_to_index("Q"):
        return True
    if suited and hi >= rank_to_index("Q") and lo >= rank_to_index("J") and gap <= 1 and effective_stack_bb <= 18:
        return True
    return strength >= 0.86


def _is_flat_call_candidate(
    cards,
    position: str,
    effective_stack_bb: float,
    strength: float,
) -> bool:
    hi, lo, suited, pair, gap = _hole_features(cards)
    button = _norm_pos(position) == "BTN"
    if pair:
        if hi >= rank_to_index("2") and not _is_early_position(position):
            return True
        return hi >= rank_to_index("4")
    if hi == rank_to_index("A"):
        if suited:
            if button:
                return lo >= rank_to_index("2")
            return lo >= rank_to_index("5")
        if button:
            return lo >= rank_to_index("5")
        return lo >= rank_to_index("9")
    if hi >= rank_to_index("K") and lo >= rank_to_index("Q"):
        return True
    if hi >= rank_to_index("Q") and lo >= rank_to_index("J"):
        return True
    if button and suited and hi >= rank_to_index("J") and lo >= rank_to_index("7") and gap <= 3:
        return True
    if hi >= rank_to_index("J") and lo >= rank_to_index("T") and gap <= 1:
        return True
    if suited and gap <= 1 and hi >= rank_to_index("T") and effective_stack_bb >= 16:
        return True
    if suited and hi >= rank_to_index("9") and lo >= rank_to_index("7") and gap <= 2 and effective_stack_bb >= 18:
        return True
    if _is_blind(position) and suited and hi >= rank_to_index("9") and lo >= rank_to_index("7") and gap <= 2:
        return True
    if _is_blind(position) and hi == rank_to_index("A") and lo >= rank_to_index("7"):
        return True
    if _is_blind(position) and hi >= rank_to_index("K") and lo >= rank_to_index("T") and gap <= 2:
        return True
    if _is_blind(position) and hi >= rank_to_index("Q") and lo >= rank_to_index("9") and gap <= 2 and effective_stack_bb >= 18:
        return True
    if not suited and hi == rank_to_index("Q") and lo < rank_to_index("J"):
        return False
    if not suited and hi == rank_to_index("J") and lo < rank_to_index("T"):
        return False
    return strength >= 0.72


def _is_blind_defend_continue_candidate(
    cards,
    position: str,
    aggressor_position: str,
    effective_stack_bb: float,
    strength: float,
) -> bool:
    hi, lo, suited, pair, gap = _hole_features(cards)
    if not _is_blind(position):
        return False
    if not _is_late_position(aggressor_position):
        return False
    if pair:
        return True
    if suited and hi >= rank_to_index("J") and lo >= rank_to_index("T") and gap <= 1:
        return True
    if suited and hi >= rank_to_index("K") and lo >= rank_to_index("8") and gap <= 2:
        return True
    if suited and hi >= rank_to_index("Q") and lo >= rank_to_index("8") and gap <= 2:
        return True
    if suited and hi >= rank_to_index("T") and lo >= rank_to_index("8") and gap <= 1 and effective_stack_bb >= 18:
        return True
    if hi == rank_to_index("A") and suited and lo >= rank_to_index("2"):
        return True
    if hi == rank_to_index("A") and lo >= rank_to_index("7"):
        return True
    if hi >= rank_to_index("K") and lo >= rank_to_index("J") and gap <= 1:
        return True
    if hi >= rank_to_index("K") and lo >= rank_to_index("T") and gap <= 2:
        return True
    if hi >= rank_to_index("Q") and lo >= rank_to_index("T") and gap <= 1 and effective_stack_bb >= 16:
        return True
    if hi >= rank_to_index("Q") and lo >= rank_to_index("9") and gap <= 2 and effective_stack_bb >= 18:
        return True
    if position == "SB" and hi >= rank_to_index("T") and lo >= rank_to_index("8") and gap <= 2 and effective_stack_bb >= 18:
        return True
    if suited and hi >= rank_to_index("8") and lo >= rank_to_index("5") and gap <= 2 and effective_stack_bb >= 18:
        return True
    return strength >= 0.62 and suited and gap <= 1 and hi >= rank_to_index("T")


# =========================================================
# POSTFLOP HELPERS
# =========================================================

def has_flush_draw(all_cards) -> bool:
    suits = Counter(_all_suits(all_cards))
    return any(v == 4 for v in suits.values())


def has_flush(all_cards) -> bool:
    suits = Counter(_all_suits(all_cards))
    return any(v >= 5 for v in suits.values())


def has_straight(rank_values: List[int]) -> bool:
    vals = sorted(set(rank_values))
    if {12, 0, 1, 2, 3}.issubset(set(vals)):
        return True
    for i in range(len(vals) - 4):
        if vals[i + 4] - vals[i] == 4:
            return True
    return False


def has_straight_draw(rank_values: List[int]) -> bool:
    vals = sorted(set(rank_values))
    expanded = list(vals)

    if 12 in vals:
        expanded = sorted(set(vals + [-1]))

    for i in range(len(expanded)):
        window = expanded[i:i + 4]
        if len(window) < 4:
            break
        if max(window) - min(window) <= 4:
            return True
    return False


def _straight_draw_windows(rank_values: List[int]) -> List[set[int]]:
    vals = sorted(set(rank_values))
    if not vals:
        return []

    expanded = list(vals)
    if 12 in vals:
        expanded = sorted(set(vals + [-1]))

    windows: List[set[int]] = []
    for i in range(len(expanded)):
        window = expanded[i:i + 4]
        if len(window) < 4:
            break
        if max(window) - min(window) <= 4:
            windows.append(set(window))
    return windows


def has_flush_draw_with_hole(hole_cards, board_cards) -> bool:
    if len(board_cards) < 3 or len(board_cards) >= 5:
        return False

    all_cards = list(hole_cards) + list(board_cards)

    if has_flush(all_cards):
        return False

    all_suits = Counter(_all_suits(all_cards))
    hole_suits = Counter(_all_suits(hole_cards))
    board_suits = Counter(_all_suits(board_cards))

    for suit, total_count in all_suits.items():
        if total_count == 4:
            if hole_suits.get(suit, 0) <= 0:
                continue
            if board_suits.get(suit, 0) >= 4:
                continue
            return True

    return False


def has_straight_draw_with_hole(hole_cards, board_cards) -> bool:
    if len(board_cards) < 3 or len(board_cards) >= 5:
        return False

    all_cards = list(hole_cards) + list(board_cards)

    all_ranks = _all_rank_indices(all_cards)
    board_ranks = _all_rank_indices(board_cards)
    hole_ranks = _all_rank_indices(hole_cards)

    if has_straight(all_ranks):
        return False

    all_windows = _straight_draw_windows(all_ranks)
    if not all_windows:
        return False

    board_windows = _straight_draw_windows(board_ranks)
    board_window_sets = {frozenset(w) for w in board_windows}
    hole_rank_set = set(hole_ranks)

    for window in all_windows:
        if not (window & hole_rank_set):
            continue
        if frozenset(window) in board_window_sets:
            continue
        return True

    return False


def _board_has_straight_draw(board_ranks: List[int]) -> bool:
    vals = sorted(set(board_ranks))
    if len(vals) < 3:
        return False

    expanded = list(vals)
    if 12 in vals:
        expanded = sorted(set(vals + [-1]))

    for i in range(len(expanded)):
        window = expanded[i:i + 3]
        if len(window) < 3:
            break
        if max(window) - min(window) <= 3:
            return True
    return False


def _board_texture(board_cards) -> str:
    if len(board_cards) < 3:
        return "unknown"

    suits = Counter(_all_suits(board_cards))
    ranks = sorted(set(_all_rank_indices(board_cards)))

    monotone = max(suits.values()) >= 3
    two_tone = max(suits.values()) == 2
    paired = len(ranks) < len(board_cards)
    connected = False

    if len(ranks) >= 3 and (max(ranks) - min(ranks) <= 4 or _board_has_straight_draw(ranks)):
        connected = True

    if monotone and connected:
        return "very_wet"
    if connected and two_tone:
        return "wet"
    if paired and two_tone:
        return "paired_wet"
    if paired:
        return "paired"
    if monotone:
        return "monotone"
    return "dry"


def classify_postflop(hole_cards, board_cards):
    all_cards = list(hole_cards) + list(board_cards)

    hole_ranks = _all_rank_indices(hole_cards)
    board_ranks = _all_rank_indices(board_cards)
    all_ranks = _all_rank_indices(all_cards)

    board_counter = Counter(board_ranks)
    all_counter = Counter(all_ranks)

    counts = sorted(all_counter.values(), reverse=True)

    board_high = max(board_ranks) if board_ranks else -1
    board_sorted_desc = sorted(board_ranks, reverse=True)
    top_board = board_sorted_desc[0] if len(board_sorted_desc) >= 1 else -1
    second_board = board_sorted_desc[1] if len(board_sorted_desc) >= 2 else -1
    third_board = board_sorted_desc[2] if len(board_sorted_desc) >= 3 else -1

    pair = counts[0] >= 2 if counts else False
    two_pair = counts[:2] == [2, 2] if len(counts) >= 2 else False
    trips = counts[0] >= 3 if counts else False
    full_house = counts[:2] == [3, 2] if len(counts) >= 2 else False
    quads = counts[0] >= 4 if counts else False

    flush = has_flush(all_cards)
    straight = has_straight(all_ranks)

    flush_draw_with_hole = has_flush_draw_with_hole(hole_cards, board_cards)
    straight_draw_with_hole = has_straight_draw_with_hole(hole_cards, board_cards)
    flush_draw = flush_draw_with_hole
    straight_draw = straight_draw_with_hole

    pair_ranks = [r for r, c in all_counter.items() if c >= 2]
    trip_ranks = [r for r, c in all_counter.items() if c >= 3]

    board_pair = any(c >= 2 for c in board_counter.values())
    board_trips = any(c >= 3 for c in board_counter.values())
    board_counts = sorted(board_counter.values(), reverse=True)
    board_two_pair = board_counts[:2] == [2, 2] if len(board_counts) >= 2 else False
    board_quads = any(c >= 4 for c in board_counter.values())

    pocket_pair = hole_ranks[0] == hole_ranks[1]

    overpair = pocket_pair and hole_ranks[0] > board_high if board_cards else False
    underpair = pocket_pair and hole_ranks[0] < board_high if board_cards else False

    set_made = False
    if trips and pocket_pair and len(board_cards) > 0:
        if hole_ranks[0] in trip_ranks:
            set_made = True

    trips_with_hole = trips and not set_made and any(r in trip_ranks for r in hole_ranks)

    hole_pair_ranks = [r for r in hole_ranks if r in pair_ranks]

    top_pair = False
    second_pair = False
    weak_pair = False

    if hole_pair_ranks and board_cards and not trips and not full_house and not quads and not two_pair:
        best_hole_pair_rank = max(hole_pair_ranks)
        if best_hole_pair_rank == top_board:
            top_pair = True
        elif best_hole_pair_rank == second_board:
            second_pair = True
        elif best_hole_pair_rank == third_board or best_hole_pair_rank < second_board:
            weak_pair = True

    kicker_strength = 0.0
    if top_pair:
        if hole_ranks[0] == top_board and hole_ranks[1] != top_board:
            other_hole = hole_ranks[1]
        elif hole_ranks[1] == top_board and hole_ranks[0] != top_board:
            other_hole = hole_ranks[0]
        else:
            other_hole = max(hole_ranks)

        if other_hole >= rank_to_index("K"):
            kicker_strength = 1.0
        elif other_hole >= rank_to_index("T"):
            kicker_strength = 0.7
        elif other_hole >= rank_to_index("7"):
            kicker_strength = 0.45
        else:
            kicker_strength = 0.2

    overcards = 0
    if board_cards:
        overcards = sum(1 for r in hole_ranks if r > board_high)

    nut_flush_draw = False
    if flush_draw_with_hole:
        suit_counts = Counter(_all_suits(all_cards))
        draw_suit = None
        for s, c in suit_counts.items():
            if c == 4:
                draw_suit = s
                break

        if draw_suit is not None:
            ace_of_draw = any(
                card_rank_index(c) == rank_to_index("A") and card_suit(c) == draw_suit
                for c in hole_cards
            )
            nut_flush_draw = ace_of_draw

    combo_draw = flush_draw_with_hole and straight_draw_with_hole

    board_flush = False
    board_straight = False
    board_full_house = False
    if board_cards:
        board_flush = has_flush(board_cards)
        board_straight = has_straight(board_ranks)
        board_full_house = len(board_cards) >= 5 and (
            sorted(Counter(board_ranks).values(), reverse=True)[:2] == [3, 2]
        )

    board_pair_two_pair = board_pair and two_pair and not trips and not full_house and not quads
    two_pair_with_hole = two_pair and not board_two_pair and not board_pair
    straight_with_hole = straight and not board_straight
    flush_with_hole = flush and not board_flush
    full_house_with_hole = full_house and not board_full_house
    quads_with_hole = quads and not board_quads

    hand_from_board_only = any([
        board_two_pair and two_pair and not two_pair_with_hole,
        board_straight and straight and not straight_with_hole,
        board_flush and flush and not flush_with_hole,
        board_full_house and full_house and not full_house_with_hole,
        board_quads and quads and not quads_with_hole,
    ])

    return {
        "pair": pair,
        "two_pair": two_pair,
        "two_pair_with_hole": two_pair_with_hole,
        "board_pair_two_pair": board_pair_two_pair,
        "trips": trips,
        "straight": straight,
        "straight_with_hole": straight_with_hole,
        "flush": flush,
        "flush_with_hole": flush_with_hole,
        "full_house": full_house,
        "full_house_with_hole": full_house_with_hole,
        "quads": quads,
        "quads_with_hole": quads_with_hole,

        "flush_draw": flush_draw,
        "straight_draw": straight_draw,
        "flush_draw_with_hole": flush_draw_with_hole,
        "straight_draw_with_hole": straight_draw_with_hole,

        "top_pair": top_pair,
        "second_pair": second_pair,
        "weak_pair": weak_pair,
        "overpair": overpair,
        "underpair": underpair,
        "set_made": set_made,
        "trips_with_hole": trips_with_hole,
        "overcards": overcards,
        "combo_draw": combo_draw,
        "nut_flush_draw": nut_flush_draw,
        "kicker_strength": kicker_strength,
        "board_texture": _board_texture(board_cards),
        "hand_from_board_only": hand_from_board_only,
        "board_pair": board_pair,
        "board_trips": board_trips,
    }


def _danger_board_factor(info: Dict[str, Any], players_in_hand: int) -> float:
    penalty = 0.0
    texture = info["board_texture"]

    if texture == "very_wet":
        penalty += 0.10
    elif texture == "wet":
        penalty += 0.07
    elif texture == "monotone":
        penalty += 0.08
    elif texture == "paired_wet":
        penalty += 0.08
    elif texture == "paired":
        penalty += 0.03

    if players_in_hand >= 3:
        penalty += 0.03
    if players_in_hand >= 4:
        penalty += 0.03

    if info["hand_from_board_only"]:
        penalty += 0.12
    if info["board_pair"] and (info["top_pair"] or info["overpair"]):
        penalty += 0.04
    if info.get("board_pair_two_pair", False):
        penalty += 0.12
    if info["board_trips"] and (info["top_pair"] or info["overpair"]):
        penalty += 0.06

    return penalty


def _has_real_showdown_value(info: Dict[str, Any]) -> bool:
    return any([
        info["top_pair"],
        info["second_pair"],
        info["weak_pair"],
        info["overpair"],
        info.get("board_pair_two_pair", False),
        info["two_pair_with_hole"],
        info["trips_with_hole"],
        info["set_made"],
        info["straight_with_hole"],
        info["flush_with_hole"],
        info["full_house_with_hole"],
        info["quads_with_hole"],
    ])


def postflop_strength(hole_cards, board_cards, cfg: negreanu_V2_BotConfig, players_in_hand: int = 2) -> float:
    info = classify_postflop(hole_cards, board_cards)

    score = 0.0

    if info["weak_pair"]:
        score += 0.17
    if info["second_pair"]:
        score += 0.24
    if info["top_pair"]:
        score += 0.32 + (cfg.top_pair_bonus * info["kicker_strength"])
    if info["overpair"]:
        score += 0.42 + cfg.overpair_bonus
    if info.get("board_pair_two_pair", False):
        score += 0.28
    if info["two_pair_with_hole"]:
        score += 0.60
    if info["trips_with_hole"]:
        score += 0.69
    if info["set_made"]:
        score += 0.82 + cfg.set_bonus
    if info["straight_with_hole"]:
        score += 0.78
    if info["flush_with_hole"]:
        score += 0.80
    if info["full_house_with_hole"]:
        score += 0.94
    if info["quads_with_hole"]:
        score += 1.00

    if info["flush_draw_with_hole"]:
        score += cfg.draw_bonus
    if info["straight_draw_with_hole"]:
        score += cfg.draw_bonus * 0.80
    if info["combo_draw"]:
        score += cfg.combo_draw_bonus
    if info["nut_flush_draw"]:
        score += cfg.nut_flush_draw_bonus

    if info["overcards"] == 2 and len(board_cards) <= 4:
        score += 0.04
    elif info["overcards"] == 1 and len(board_cards) <= 4:
        score += 0.02

    score -= _danger_board_factor(info, players_in_hand)

    if info["top_pair"] and info["kicker_strength"] <= 0.25:
        score -= 0.04

    if info["underpair"] and players_in_hand >= 3:
        score -= 0.05

    return _clamp(score, 0.0, 1.0)


# =========================================================
# BOT
# =========================================================

class SmartParametricBot:
    def __init__(self, config: negreanu_V2_BotConfig):
        self.config = config
        self.name = config.name
        self.stats_tracker = PlayerStatsTracker(self.name)

    def start_stats_hand(
        self,
        hand_id: int,
        position: str,
        stack_bb: float,
        players_in_hand: int,
    ) -> None:
        self.stats_tracker.start_hand(hand_id, position, stack_bb, players_in_hand)

    def note_stats_saw_flop(self) -> None:
        self.stats_tracker.note_saw_flop()

    def note_stats_showdown(self) -> None:
        self.stats_tracker.note_showdown()

    def get_stats_snapshot(self) -> Dict[str, Any]:
        return self.stats_tracker.build_stats().to_dict()

    def _raise_amount(
        self,
        state,
        stack: int,
        strength: float = 0.75,
        street: str = "preflop",
        stats_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        min_raise = _safe_get(state, "min_completion_betting_or_raising_to_amount", None)
        max_raise = _safe_get(state, "max_completion_betting_or_raising_to_amount", None)

        if min_raise is None or max_raise is None:
            return None

        min_raise = _safe_int(min_raise, 0)
        max_raise = _safe_int(max_raise, 0)

        if min_raise <= 0 or max_raise <= 0:
            return None

        pot = _estimate_pot(state, stats_context)
        call_amount = _safe_int(_safe_get(state, "checking_or_calling_amount", 0), 0)
        street = _norm_text(street)

        if street == "preflop":
            bb = _safe_float((stats_context or {}).get("big_blind", 0.0), 0.0)
            raise_count = _safe_int((stats_context or {}).get("raise_count_before_action", 0), 0)
            position = (stats_context or {}).get("position", "")
            effective_stack_bb = _safe_float((stats_context or {}).get("effective_stack_bb", 0.0), 0.0)
            limper_count = _safe_int((stats_context or {}).get("limper_count", 0), 0)

            if 0 < effective_stack_bb <= 10:
                if raise_count == 0:
                    target = max(min_raise, int(round(bb * 2.5))) if bb > 0 else min_raise
                elif strength >= 0.88:
                    target = min(max_raise, stack)
                else:
                    target = max(min_raise, min(call_amount * 2, stack))
            elif bb > 0:
                if raise_count == 0:
                    if limper_count > 0:
                        mult = 4.0 + max(0, limper_count - 1) * 0.6
                        if strength >= 0.80:
                            mult += 0.3
                    else:
                        if _is_late_position(position) and effective_stack_bb >= 25:
                            mult = 2.3
                        elif _is_late_position(position):
                            mult = 2.5
                        else:
                            mult = 3.0

                        if _is_blind(position) or _is_early_position(position):
                            mult += 0.3

                    target = int(round(bb * mult))
                else:
                    if 0 < effective_stack_bb <= 12 and strength >= 0.74:
                        target = min(max_raise, stack)
                    else:
                        target = max(min_raise, call_amount * 3)
            else:
                factor = _clamp((self.config.aggression * 0.55) + (strength * 0.45), 0.20, 0.75)
                target = min_raise + int((max_raise - min_raise) * factor)
        else:
            bet_profile = _norm_text((stats_context or {}).get("bet_profile", ""))
            if pot > 0:
                if bet_profile == "stab_small":
                    target = int(round(pot * 0.30))
                elif bet_profile == "cbet_small":
                    target = int(round(pot * 0.36))
                elif bet_profile == "semibluff_medium":
                    target = int(round(pot * 0.42))
                elif bet_profile == "value_large":
                    target = int(round(pot * (0.68 if strength >= 0.90 else 0.58)))
                elif strength >= 0.88:
                    target = int(round(pot * 0.66))
                elif strength >= 0.75:
                    target = int(round(pot * 0.54))
                else:
                    target = int(round(pot * 0.40))
                target = max(target, min_raise)
            else:
                factor = _clamp((self.config.aggression * 0.45) + (strength * 0.35), 0.20, 0.60)
                target = min_raise + int((max_raise - min_raise) * factor)

        target = max(min_raise, min(target, max_raise, stack))

        if target <= 0:
            return None
        return target

    def _adapt_preflop_strength(
        self,
        strength: float,
        stats_context: Optional[Dict[str, Any]],
        call_ratio: float,
    ) -> float:
        if not stats_context:
            return strength

        opponents = stats_context.get("opponents", [])
        profile = _effective_opponent_profile(opponents)

        position = stats_context.get("position", "")
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        hero_stack_bb = _safe_float(stats_context.get("hero_stack_bb", 0.0), 0.0)
        effective_stack_bb = _safe_float(stats_context.get("effective_stack_bb", hero_stack_bb), hero_stack_bb)
        players_yet_to_act = _safe_int(stats_context.get("players_yet_to_act", 0), 0)
        limper_count = _safe_int(stats_context.get("limper_count", 0), 0)
        is_limped_pot = bool(stats_context.get("is_limped_pot", False))

        short_stacks = _count_short_stacks(opponents, 15.0)
        big_stacks = _count_big_stacks(opponents, 45.0)
        weak_limpers = _count_weak_limpers(opponents)
        unknown_opponents = _count_unknown_opponents(opponents)
        blind_defenders = _opponents_in_positions(opponents, {"SB", "BB"})
        avg_blind_fold = _avg_stat(blind_defenders, "fold_to_raise", 0.35)
        avg_blind_three_bet = _avg_stat(blind_defenders, "3bet", 0.10)
        avg_blind_vpip = _avg_stat(blind_defenders, "vpip", 0.28)

        if _is_late_position(position):
            strength += 0.04 + self.config.steal_bonus_late
        elif _is_early_position(position):
            strength -= 0.04
        elif _is_blind(position):
            strength -= 0.01

        if players_in_hand <= 4:
            strength += 0.05
        elif players_in_hand >= 7:
            strength -= 0.02

        if profile["avg_fold_to_raise"] > 0.45:
            strength += 0.04

        if profile["avg_vpip"] > 0.40:
            strength -= 0.02

        if profile["avg_three_bet"] > 0.16 or profile["avg_pfr"] > 0.24:
            strength -= 0.04

        if _is_isolation_spot(stats_context, _safe_int(stats_context.get("call_amount", 0), 0)):
            strength += self.config.isolate_bonus

        if _is_open_spot(stats_context) and _is_late_position(position):
            if avg_blind_fold > 0.42:
                strength += 0.05
            if avg_blind_three_bet > 0.14 or avg_blind_vpip > 0.38:
                strength -= 0.04

        if is_limped_pot:
            if weak_limpers > 0 and not _is_early_position(position):
                strength += 0.05 + (self.config.isolate_bonus * 0.50)
            elif limper_count >= 2 and _is_early_position(position):
                strength -= 0.03

        if players_yet_to_act >= 3 and not _is_late_position(position):
            strength -= 0.02

        if unknown_opponents > 0:
            strength -= 0.03
            if _is_open_spot(stats_context) and _is_late_position(position):
                strength -= 0.03
            if not _is_open_spot(stats_context):
                strength -= 0.02
            if unknown_opponents >= 2:
                strength -= 0.02

        if hero_stack_bb >= 40 and short_stacks >= 1 and _is_late_position(position):
            strength += self.config.big_stack_bully_bonus

        if 0 < effective_stack_bb <= 12:
            if call_ratio > 0.10:
                strength -= 0.05
            else:
                strength += self.config.short_stack_push_bonus
            if not _is_open_spot(stats_context):
                strength -= 0.05

        if big_stacks >= 2 and not _is_late_position(position):
            strength -= 0.03

        if _has_heavy_preflop_resistance(stats_context):
            strength -= self.config.fold_vs_heavy_resistance_penalty

        return _clamp(strength, 0.0, 1.0)

    def _adapt_postflop_strength(
        self,
        strength: float,
        stats_context: Optional[Dict[str, Any]],
        call_ratio: float,
        board_cards,
        hole_cards,
    ) -> float:
        if not stats_context:
            return strength

        info = classify_postflop(hole_cards, board_cards)
        opponents = stats_context.get("opponents", [])
        profile = _effective_opponent_profile(opponents)

        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        is_cbet_opportunity = bool(stats_context.get("is_cbet_opportunity", False))
        is_facing_cbet = bool(stats_context.get("is_facing_cbet", False))
        street = _norm_text(stats_context.get("street", ""))
        hero_has_initiative = bool(stats_context.get("hero_has_initiative", False))
        pot_was_limped_preflop = bool(stats_context.get("pot_was_limped_preflop", False))
        last_action_kind = _norm_text(stats_context.get("last_action_kind", ""))
        last_action_street = _norm_text(stats_context.get("last_action_street", ""))
        last_actor_stats = stats_context.get("last_actor_stats", None)

        if is_cbet_opportunity and len(board_cards) == 3:
            if info["board_texture"] == "dry" and profile["avg_fold_to_cbet"] >= 0.35:
                strength += self.config.cbet_bonus_dry
            elif info["board_texture"] in {"wet", "very_wet", "monotone", "paired_wet"}:
                strength -= 0.03

        if hero_has_initiative and street == "flop" and players_in_hand == 2 and info["board_texture"] == "dry":
            strength += 0.03

        if pot_was_limped_preflop and players_in_hand > 2 and not _has_real_showdown_value(info):
            strength -= 0.03

        if street == "turn" and profile["avg_fold_to_cbet"] > 0.45 and not _has_real_showdown_value(info):
            strength += self.config.second_barrel_scare_bonus

        if players_in_hand > 2:
            if info["top_pair"] or info["second_pair"] or info["overpair"]:
                strength -= 0.03
            else:
                strength -= 0.03

        if profile["avg_wtsd"] > 0.36 or profile["avg_vpip"] > 0.40:
            if not _has_real_showdown_value(info):
                strength -= 0.06

        if (
            street == "turn"
            and last_action_kind == "call"
            and last_action_street == "flop"
            and _is_weak_passive_player(last_actor_stats)
        ):
            if _has_real_showdown_value(info):
                strength += 0.03
            else:
                strength -= 0.06

        if is_facing_cbet and profile["avg_af"] > 2.3 and call_ratio > 0.10:
            strength -= 0.05

        if last_action_kind == "raise" and last_action_street == street and _is_loose_aggressive_player(last_actor_stats):
            strength -= 0.04

        if info["combo_draw"]:
            strength += 0.05

        if info["flush_draw_with_hole"] or info["straight_draw_with_hole"]:
            strength += 0.04

        if (
            (info["top_pair"] or info["second_pair"])
            and (info["flush_draw_with_hole"] or info["straight_draw_with_hole"])
        ):
            strength += 0.05

        if info["nut_flush_draw"]:
            strength += 0.03

        if info["top_pair"] and info["board_texture"] in {"wet", "very_wet", "monotone", "paired_wet"}:
            strength -= 0.03

        if info["overpair"] and info["board_texture"] in {"wet", "very_wet", "monotone", "paired", "paired_wet"}:
            strength -= 0.03

        return _clamp(strength, 0.0, 1.0)

    def _preflop_thresholds(
        self,
        stats_context: Optional[Dict[str, Any]],
    ) -> Tuple[float, float]:
        raise_threshold = self.config.preflop_raise_threshold
        call_threshold = self.config.preflop_call_threshold

        if not stats_context:
            return raise_threshold, call_threshold

        opponents = stats_context.get("opponents", [])
        profile = _effective_opponent_profile(opponents)

        position = stats_context.get("position", "")
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        raise_count = _safe_int(stats_context.get("raise_count_before_action", 0), 0)
        hero_stack_bb = _safe_float(stats_context.get("hero_stack_bb", 0.0), 0.0)
        is_limped_pot = bool(stats_context.get("is_limped_pot", False))
        blind_defenders = _opponents_in_positions(opponents, {"SB", "BB"})
        avg_blind_fold = _avg_stat(blind_defenders, "fold_to_raise", 0.35)
        avg_blind_three_bet = _avg_stat(blind_defenders, "3bet", 0.10)
        avg_blind_vpip = _avg_stat(blind_defenders, "vpip", 0.28)
        weak_limpers = _count_weak_limpers(opponents)
        unknown_opponents = _count_unknown_opponents(opponents)

        if _is_late_position(position) and raise_count == 0:
            raise_threshold -= 0.06
            call_threshold -= 0.03

        if players_in_hand <= 4:
            raise_threshold -= 0.03
            call_threshold -= 0.03

        if profile["avg_fold_to_raise"] > 0.45:
            raise_threshold -= 0.03

        if profile["avg_three_bet"] > 0.16:
            raise_threshold += 0.04
            call_threshold += 0.04

        if _is_open_spot(stats_context) and _is_late_position(position) and avg_blind_fold > 0.42:
            raise_threshold -= 0.03

        if _is_open_spot(stats_context) and _is_late_position(position) and (avg_blind_three_bet > 0.14 or avg_blind_vpip > 0.38):
            raise_threshold += 0.03
            call_threshold += 0.02

        if is_limped_pot and weak_limpers > 0 and not _is_early_position(position):
            raise_threshold -= 0.04
            call_threshold += 0.01

        if 0 < hero_stack_bb <= 12:
            raise_threshold -= 0.03
            call_threshold += 0.03
            if not _is_open_spot(stats_context):
                call_threshold += 0.05

        if raise_count >= 2:
            raise_threshold += 0.05
            call_threshold += 0.06

        if unknown_opponents > 0:
            raise_threshold += 0.04
            call_threshold += 0.03
            if _is_open_spot(stats_context) and _is_late_position(position):
                raise_threshold += 0.03
            if raise_count > 0:
                call_threshold += 0.03
            if unknown_opponents >= 2:
                raise_threshold += 0.02
                call_threshold += 0.02

        return _clamp(raise_threshold, 0.40, 0.90), _clamp(call_threshold, 0.25, 0.78)

    def _postflop_thresholds(
        self,
        stats_context: Optional[Dict[str, Any]],
    ) -> Tuple[float, float]:
        raise_threshold = self.config.postflop_raise_threshold
        call_threshold = self.config.postflop_call_threshold

        if not stats_context:
            return raise_threshold, call_threshold

        opponents = stats_context.get("opponents", [])
        profile = _effective_opponent_profile(opponents)
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        street = _norm_text(stats_context.get("street", ""))
        hero_has_initiative = bool(stats_context.get("hero_has_initiative", False))
        pot_was_limped_preflop = bool(stats_context.get("pot_was_limped_preflop", False))
        last_action_kind = _norm_text(stats_context.get("last_action_kind", ""))
        last_action_street = _norm_text(stats_context.get("last_action_street", ""))
        last_actor_stats = stats_context.get("last_actor_stats", None)
        unknown_opponents = _count_unknown_opponents(opponents)

        if profile["avg_fold_to_cbet"] > 0.48:
            raise_threshold -= 0.04

        if profile["avg_wtsd"] > 0.38:
            raise_threshold += 0.03
            call_threshold += 0.03

        if players_in_hand > 2:
            raise_threshold += 0.03
            call_threshold += 0.03

        if hero_has_initiative and street == "flop":
            raise_threshold -= 0.02

        if pot_was_limped_preflop and players_in_hand > 2:
            raise_threshold += 0.02

        if (
            street == "turn"
            and last_action_kind == "call"
            and last_action_street == "flop"
            and _is_weak_passive_player(last_actor_stats)
        ):
            raise_threshold += 0.03

        if street == "flop":
            raise_threshold -= 0.02
            call_threshold -= 0.03
        elif street == "turn" and players_in_hand <= 2:
            raise_threshold -= 0.02
            call_threshold -= 0.02
        elif street == "river":
            raise_threshold += 0.03
            call_threshold += 0.08

        if unknown_opponents > 0:
            raise_threshold += 0.04
            call_threshold += 0.03
            if not hero_has_initiative:
                call_threshold += 0.02
            if unknown_opponents >= 2:
                raise_threshold += 0.02
                call_threshold += 0.02

        return _clamp(raise_threshold, 0.48, 0.90), _clamp(call_threshold, 0.28, 0.84)

    def _passive_action(self, call_amount: int) -> BotAction:
        return BotAction("check") if call_amount <= 0 else BotAction("call", call_amount)

    def _with_bet_profile(
        self,
        stats_context: Optional[Dict[str, Any]],
        bet_profile: str,
    ) -> Dict[str, Any]:
        context = dict(stats_context or {})
        context["bet_profile"] = bet_profile
        return context

    def _pick_postflop_bet_profile(
        self,
        info: Dict[str, Any],
        stats_context: Optional[Dict[str, Any]],
        call_amount: int,
    ) -> str:
        street = _norm_text((stats_context or {}).get("street", ""))

        if street != "river" and call_amount == 0 and self._should_stab(info, stats_context):
            return "stab_small"

        is_cbet_opportunity = bool((stats_context or {}).get("is_cbet_opportunity", False))
        if call_amount == 0 and is_cbet_opportunity and info["board_texture"] in {"dry", "paired"}:
            return "cbet_small"

        if any([
            info["top_pair"],
            info["overpair"],
            info["two_pair_with_hole"],
            info["trips_with_hole"],
            info["set_made"],
            info["straight_with_hole"],
            info["flush_with_hole"],
            info["full_house_with_hole"],
            info["quads_with_hole"],
        ]):
            return "value_large"

        if info["combo_draw"] or info["nut_flush_draw"]:
            return "semibluff_medium"
        return "cbet_small"

    def _should_stab(
        self,
        info: Dict[str, Any],
        stats_context: Optional[Dict[str, Any]],
    ) -> bool:
        if not stats_context or _has_real_showdown_value(info):
            return False

        players_in_hand = _safe_int(stats_context.get("players_in_hand", 2), 2)
        players_acted_this_street = _safe_int(stats_context.get("players_acted_this_street", 0), 0)
        last_action_kind = _norm_text(stats_context.get("last_action_kind", ""))
        last_action_street = _norm_text(stats_context.get("last_action_street", ""))
        hero_has_initiative = bool(stats_context.get("hero_has_initiative", False))
        pot_was_limped_preflop = bool(stats_context.get("pot_was_limped_preflop", False))
        street = _norm_text(stats_context.get("street", ""))
        texture = info["board_texture"]

        passive_line = players_acted_this_street >= 1 and last_action_kind in {"", "check", "call"}

        if street != "flop":
            return False

        if players_in_hand == 2:
            if hero_has_initiative:
                return False
            return (
                passive_line
                and players_acted_this_street >= 1
                and last_action_street == street
                and texture in {"dry", "paired"}
            )

        if hero_has_initiative and not pot_was_limped_preflop:
            return False

        scary_or_paired = texture in {"monotone", "paired", "paired_wet", "wet", "very_wet"}
        everyone_looked_weak = players_acted_this_street >= players_in_hand - 1 and last_action_street == street
        return everyone_looked_weak and scary_or_paired and passive_line and players_in_hand <= 3

    def _facing_strong_river_line(
        self,
        stats_context: Optional[Dict[str, Any]],
        info: Dict[str, Any],
        call_amount: int,
        pot: float,
        call_ratio: float,
    ) -> bool:
        if not stats_context or _norm_text(stats_context.get("street", "")) != "river" or call_amount <= 0:
            return False

        raise_count = _safe_int(stats_context.get("raise_count_before_action", 0), 0)
        last_action_kind = _norm_text(stats_context.get("last_action_kind", ""))
        last_action_street = _norm_text(stats_context.get("last_action_street", ""))
        big_bet = call_ratio >= 0.09 or (pot > 0 and (call_amount / max(pot, 1.0)) >= 0.42)
        scary_board = info["board_texture"] in {"wet", "very_wet", "monotone", "paired", "paired_wet"}
        turn_then_river_force = last_action_street == "river" and last_action_kind == "raise"
        return raise_count > 0 or turn_then_river_force or (big_bet and scary_board)

    def _should_fold_river_medium_strength(
        self,
        info: Dict[str, Any],
        stats_context: Optional[Dict[str, Any]],
        players_in_hand: int,
        call_amount: int,
        pot: float,
        call_ratio: float,
    ) -> bool:
        if not self._facing_strong_river_line(stats_context, info, call_amount, pot, call_ratio):
            return False

        scary_board = info["board_texture"] in {"wet", "very_wet", "monotone", "paired", "paired_wet"}
        bigger_bet = call_ratio >= 0.10 or (pot > 0 and (call_amount / max(pot, 1.0)) >= 0.45)

        if info["weak_pair"]:
            return True
        if info["second_pair"]:
            return players_in_hand > 2 or bigger_bet or scary_board
        if info["top_pair"] and info["kicker_strength"] < 0.60:
            return bigger_bet or scary_board

        return False

    def _should_check_back_river(
        self,
        info: Dict[str, Any],
        stats_context: Optional[Dict[str, Any]],
        strength: float,
        call_amount: int,
    ) -> bool:
        if call_amount > 0 or not stats_context or _norm_text(stats_context.get("street", "")) != "river":
            return False

        position = _norm_pos(stats_context.get("position", ""))
        players_in_hand = _safe_int(stats_context.get("players_in_hand", 2), 2)
        hero_has_initiative = bool(stats_context.get("hero_has_initiative", False))
        board_texture = info["board_texture"]

        monster = any([
            info["full_house_with_hole"],
            info["quads_with_hole"],
            info["flush_with_hole"],
            info["set_made"],
        ])
        if monster:
            return False

        if info["trips_with_hole"]:
            if players_in_hand > 2:
                return True
            if position in {"SB", "BB"} and board_texture in {"wet", "very_wet", "monotone", "paired", "paired_wet"}:
                return True
            if not hero_has_initiative:
                return True

        if info["straight_with_hole"]:
            if players_in_hand > 2 and not hero_has_initiative and board_texture in {"very_wet", "monotone", "paired_wet"}:
                return True
            if (
                position in {"SB", "BB"}
                and not hero_has_initiative
                and board_texture in {"very_wet", "monotone", "paired_wet"}
                and strength < 0.86
            ):
                return True
            return False

        if players_in_hand > 2 and not hero_has_initiative and strength < 0.92:
            return True

        if position in {"SB", "BB"} and not hero_has_initiative and strength < 0.90:
            return True

        if info["weak_pair"] or info["second_pair"]:
            return True

        if info["top_pair"] and info["kicker_strength"] < 0.70:
            return True

        return strength < 0.78

    def _should_fold_under_postflop_pressure(
        self,
        info: Dict[str, Any],
        stats_context: Optional[Dict[str, Any]],
        strength: float,
        call_amount: int,
        pot: float,
        call_ratio: float,
        players_in_hand: int,
    ) -> bool:
        if call_amount <= 0:
            return False

        street = _norm_text((stats_context or {}).get("street", ""))
        raise_count = _safe_int((stats_context or {}).get("raise_count_before_action", 0), 0)
        board_texture = info["board_texture"]
        big_bet = call_ratio >= 0.16 or (pot > 0 and (call_amount / max(pot, 1.0)) >= 0.45)
        medium_bet = call_ratio >= 0.10 or (pot > 0 and (call_amount / max(pot, 1.0)) >= 0.28)
        scary_board = board_texture in {"wet", "very_wet", "monotone", "paired", "paired_wet"}

        if _has_strong_made_hand(info):
            return False

        cheap_continue = call_ratio <= 0.10 or (pot > 0 and (call_amount / max(pot, 1.0)) <= 0.28)

        if info["combo_draw"] and cheap_continue:
            return False

        if info["flush_draw_with_hole"] and info["straight_draw_with_hole"] and cheap_continue:
            return False

        if info["straight_draw_with_hole"] and street == "flop" and cheap_continue:
            return False

        if info["flush_draw_with_hole"] and street in {"flop", "turn"} and cheap_continue:
            return False

        if info["top_pair"] and (info["flush_draw_with_hole"] or info["straight_draw_with_hole"]) and medium_bet:
            return False

        if info["second_pair"] and (info["flush_draw_with_hole"] or info["straight_draw_with_hole"]) and cheap_continue:
            return False

        if info["top_pair"] and cheap_continue:
            return False

        if info["second_pair"] and street == "flop" and cheap_continue and players_in_hand <= 2:
            return False

        if info["second_pair"] and cheap_continue and players_in_hand <= 2:
            return False

        if info["weak_pair"] and street == "flop" and cheap_continue and players_in_hand <= 2:
            return False

        if players_in_hand > 2 and medium_bet and not info["top_pair"]:
            return True

        if raise_count >= 1 and big_bet and not info["top_pair"] and not info["nut_flush_draw"]:
            return True

        if street in {"flop", "turn"}:
            if info["weak_pair"]:
                if cheap_continue and players_in_hand <= 2:
                    return False
                return medium_bet
            if info["second_pair"]:
                if cheap_continue and players_in_hand <= 2:
                    return False
                return players_in_hand > 2 or big_bet or scary_board
            if info["top_pair"] and info["kicker_strength"] < 0.62:
                if cheap_continue:
                    return False
                return big_bet and scary_board
            if info["flush_draw_with_hole"] and not info["straight_draw_with_hole"] and big_bet and pot > 0 and (call_amount / max(pot, 1.0)) >= 0.55:
                return True
            if info["straight_draw_with_hole"] and not info["flush_draw_with_hole"] and medium_bet and call_ratio >= 0.12:
                return True

        return False

    def act(self, state, player_index: int, stats_context: Optional[Dict[str, Any]] = None) -> BotAction:
        hole_cards = state.hole_cards[player_index]
        board_cards = state.board_cards

        stack = _safe_int(state.stacks[player_index], 0)
        call_amount = _safe_int(_safe_get(state, "checking_or_calling_amount", 0), 0)

        if stack <= 0:
            return BotAction("fold")

        stack_bb = _estimate_stack_bb(stack, stats_context)
        effective_stack_bb = _estimate_effective_stack_bb(stack_bb, stats_context)
        pot = _estimate_pot(state, stats_context)
        call_ratio = call_amount / max(stack, 1)
        pot_odds_req = _pot_odds_required(call_amount, pot)
        is_preflop = len(board_cards) == 0

        position = (stats_context or {}).get("position", "")
        players_in_hand = _safe_int((stats_context or {}).get("players_in_hand", 2), 2)
        raise_count = _safe_int((stats_context or {}).get("raise_count_before_action", 0), 0)
        preflop_aggressor_position = (stats_context or {}).get("preflop_aggressor_position", "")

        if is_preflop:
            strength = preflop_strength(
                hole_cards,
                position=position,
                players_in_hand=players_in_hand,
                stack_bb=effective_stack_bb if effective_stack_bb > 0 else stack_bb,
            )

            strength += (self.config.looseness - 0.5) * 0.14
            strength = self._adapt_preflop_strength(strength, stats_context, call_ratio)

            raise_threshold, call_threshold = self._preflop_thresholds(stats_context)

            if 0 < effective_stack_bb <= 12:
                if raise_count == 0 and strength >= max(0.58, raise_threshold - 0.06):
                    if not _is_open_raise_candidate(hole_cards, position, effective_stack_bb, players_in_hand, strength):
                        action = self._passive_action(call_amount) if call_amount == 0 else BotAction("fold")
                        self._record_stats_decision(action, stats_context)
                        return action
                    amount = self._raise_amount(state, stack, max(strength, 0.70), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if raise_count >= 1:
                    if strength >= 0.86 and _is_value_reraise_candidate(hole_cards, effective_stack_bb, strength):
                        amount = self._raise_amount(state, stack, max(strength, 0.82), "preflop", stats_context)
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action
                    if strength >= max(call_threshold, 0.64) and call_ratio <= 0.12:
                        action = BotAction("call", call_amount)
                        self._record_stats_decision(action, stats_context)
                        return action
                    action = BotAction("fold")
                    self._record_stats_decision(action, stats_context)
                    return action

            if raise_count == 0:
                hi, lo, suited, pair, gap = _hole_features(hole_cards)
                if strength >= raise_threshold:
                    if not _is_open_raise_candidate(hole_cards, position, effective_stack_bb, players_in_hand, strength):
                        action = self._passive_action(call_amount) if call_amount == 0 else BotAction("fold")
                        self._record_stats_decision(action, stats_context)
                        return action
                    amount = self._raise_amount(state, stack, strength, "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if _is_late_position(position) and strength >= raise_threshold - 0.04:
                    if not _is_open_raise_candidate(hole_cards, position, effective_stack_bb, players_in_hand, strength):
                        action = self._passive_action(call_amount) if call_amount == 0 else BotAction("fold")
                        self._record_stats_decision(action, stats_context)
                        return action
                    amount = self._raise_amount(state, stack, max(strength, 0.62), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if (
                    call_amount > 0
                    and _is_blind(position)
                    and call_ratio <= 0.04
                    and (
                        pair
                        or (hi == rank_to_index("A") and lo >= rank_to_index("2"))
                        or (suited and hi >= rank_to_index("K") and lo >= rank_to_index("6"))
                        or (suited and hi >= rank_to_index("Q") and lo >= rank_to_index("8") and gap <= 2)
                        or (position == "SB" and hi >= rank_to_index("T") and lo >= rank_to_index("8") and gap <= 2)
                    )
                ):
                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                action = self._passive_action(call_amount) if call_amount == 0 else BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if raise_count == 1:
                pocket_pair = _is_pocket_pair(hole_cards)
                if (
                    call_amount > 0
                    and pocket_pair
                    and _is_blind(position)
                    and call_ratio <= 0.08
                    and effective_stack_bb >= 18
                ):
                    bb_units = _safe_int((stats_context or {}).get("big_blind", 0), 0)
                    if position == "SB" and bb_units > 0:
                        target_amount = max(
                            _safe_int(_safe_get(state, "min_completion_betting_or_raising_to_amount", 0), 0),
                            bb_units * 10,
                        )
                        max_raise_to = _safe_int(_safe_get(state, "max_completion_betting_or_raising_to_amount", 0), 0)
                        if max_raise_to > 0:
                            target_amount = min(target_amount, max_raise_to)
                        if target_amount > 0:
                            action = BotAction("raise", target_amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                if (
                    call_amount > 0
                    and pocket_pair
                    and call_ratio <= 0.06
                    and effective_stack_bb >= 20
                    and not (raise_count >= 2)
                ):
                    if not _is_early_position(position) or card_rank_index(hole_cards[0]) >= rank_to_index("4"):
                        action = BotAction("call", call_amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if strength >= raise_threshold + 0.05 and _is_value_reraise_candidate(hole_cards, effective_stack_bb, strength):
                    amount = self._raise_amount(state, stack, max(strength, 0.74), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if (
                    strength >= max(call_threshold + 0.03, 0.52)
                    and call_ratio <= 0.06
                    and not _is_early_position(position)
                    and _is_flat_call_candidate(hole_cards, position, effective_stack_bb, strength)
                ):
                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                if (
                    call_amount > 0
                    and call_ratio <= 0.12
                    and _is_blind_defend_continue_candidate(
                        hole_cards,
                        position,
                        preflop_aggressor_position,
                        effective_stack_bb,
                        strength,
                    )
                ):
                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                hi, lo, suited, pair, gap = _hole_features(hole_cards)
                if (
                    call_amount > 0
                    and _is_blind(position)
                    and call_ratio <= 0.08
                    and effective_stack_bb >= 18
                    and (
                        (suited and hi >= rank_to_index("8") and lo >= rank_to_index("6") and gap <= 2)
                        or (hi == rank_to_index("A") and lo >= rank_to_index("7"))
                        or (hi >= rank_to_index("K") and lo >= rank_to_index("T") and gap <= 2)
                        or (position == "SB" and hi >= rank_to_index("T") and lo >= rank_to_index("8") and gap <= 2)
                    )
                ):
                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if raise_count >= 2:
                strong_allin_zone = (
                    strength >= 0.90
                    and (
                        (0 < effective_stack_bb <= 20)
                        or call_ratio <= 0.10
                    )
                )

                very_strong_flat_zone = (
                    strength >= 0.80
                    and call_ratio <= 0.05
                )

                if strong_allin_zone:
                    amount = self._raise_amount(state, stack, max(strength, 0.92), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if very_strong_flat_zone:
                    action = BotAction("call", call_amount)
                    self._record_stats_decision(action, stats_context)
                    return action

                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

        info = classify_postflop(hole_cards, board_cards)
        strength = postflop_strength(hole_cards, board_cards, self.config, players_in_hand=players_in_hand)
        strength += (self.config.looseness - 0.5) * 0.05

        if call_ratio < 0.03:
            strength += self.config.cheap_call_bonus * 0.20

        strength = self._adapt_postflop_strength(
            strength,
            stats_context,
            call_ratio,
            board_cards,
            hole_cards,
        )

        raise_threshold, call_threshold = self._postflop_thresholds(stats_context)
        bet_profile_context = self._with_bet_profile(
            stats_context,
            self._pick_postflop_bet_profile(info, stats_context, call_amount),
        )

        if self._should_check_back_river(info, stats_context, strength, call_amount):
            action = self._passive_action(call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        if strength >= raise_threshold:
            if (
                _norm_text((stats_context or {}).get("street", "")) == "turn"
                and call_amount > 0
                and not any([
                    info["straight_with_hole"],
                    info["flush_with_hole"],
                    info["full_house_with_hole"],
                    info["quads_with_hole"],
                    info["set_made"],
                    info["two_pair_with_hole"],
                ])
            ):
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action
            amount = self._raise_amount(state, stack, strength, "postflop", bet_profile_context)
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if info["combo_draw"] and call_ratio <= 0.06 and players_in_hand == 2:
            amount = self._raise_amount(
                state,
                stack,
                max(strength, raise_threshold + 0.01),
                "postflop",
                self._with_bet_profile(stats_context, "semibluff_medium"),
            )
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if (
            len(board_cards) == 3
            and players_in_hand == 2
            and (info["nut_flush_draw"] or (info["flush_draw_with_hole"] and info["straight_draw_with_hole"]))
            and call_ratio <= 0.05
        ):
            amount = self._raise_amount(
                state,
                stack,
                max(strength, 0.78),
                "postflop",
                self._with_bet_profile(stats_context, "semibluff_medium"),
            )
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if strength >= call_threshold:
            street = _norm_text((stats_context or {}).get("street", ""))
            if call_amount == 0:
                street_name = _norm_text((stats_context or {}).get("street", ""))
                if street_name == "river":
                    if any([
                        info["straight_with_hole"],
                        info["flush_with_hole"],
                        info["full_house_with_hole"],
                        info["quads_with_hole"],
                        info["set_made"],
                        info["trips_with_hole"],
                        info["two_pair_with_hole"],
                    ]):
                        amount = self._raise_amount(
                            state,
                            stack,
                            max(strength, 0.74 if players_in_hand > 2 else 0.78),
                            "postflop",
                            self._with_bet_profile(stats_context, "value_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                if street_name in {"flop", "turn"}:
                    # Avoid the too-passive line where medium/strong hands auto-check
                    # before reaching the proactive value/semi-bluff logic below.
                    if any([
                        info["set_made"],
                        info["trips_with_hole"],
                        info["straight_with_hole"],
                        info["flush_with_hole"],
                        info["full_house_with_hole"],
                        info["quads_with_hole"],
                        info["two_pair_with_hole"],
                        info["overpair"],
                    ]):
                        amount = self._raise_amount(
                            state,
                            stack,
                            max(strength, 0.72 if players_in_hand > 2 else 0.76),
                            "postflop",
                            self._with_bet_profile(stats_context, "value_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if info["top_pair"] and info["kicker_strength"] >= 0.50:
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.65 if players_in_hand > 2 else 0.69,
                            "postflop",
                            self._with_bet_profile(stats_context, "value_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if (
                        players_in_hand <= 2
                        and info["top_pair"]
                        and info["kicker_strength"] >= 0.28
                    ):
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.62 if street_name == "turn" else 0.64,
                            "postflop",
                            self._with_bet_profile(stats_context, "value_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if (
                        players_in_hand <= 2
                        and street_name in {"flop", "turn"}
                        and info["second_pair"]
                        and (
                            info["kicker_strength"] >= 0.45
                            or info["flush_draw_with_hole"]
                            or info["straight_draw_with_hole"]
                        )
                    ):
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.58 if street_name == "turn" else 0.60,
                            "postflop",
                            self._with_bet_profile(stats_context, "value_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if info["combo_draw"] or info["nut_flush_draw"]:
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.64 if players_in_hand > 2 else 0.68,
                            "postflop",
                            self._with_bet_profile(stats_context, "semibluff_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if (
                        players_in_hand <= 2
                        and street_name in {"flop", "turn"}
                        and (
                            info["flush_draw_with_hole"]
                            or info["straight_draw_with_hole"]
                        )
                    ):
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.60 if info["nut_flush_draw"] else 0.58,
                            "postflop",
                            self._with_bet_profile(stats_context, "semibluff_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                    if (
                        players_in_hand <= 2
                        and info["second_pair"]
                        and (info["flush_draw_with_hole"] or info["straight_draw_with_hole"])
                    ):
                        amount = self._raise_amount(
                            state,
                            stack,
                            0.62,
                            "postflop",
                            self._with_bet_profile(stats_context, "semibluff_medium"),
                        )
                        if amount is not None:
                            action = BotAction("raise", amount)
                            self._record_stats_decision(action, stats_context)
                            return action

                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if info["top_pair"] and call_ratio <= 0.12:
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if info["second_pair"] and players_in_hand <= 2 and call_ratio <= 0.08:
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if info["weak_pair"] and players_in_hand <= 2 and street == "flop" and call_ratio <= 0.06:
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if self._should_fold_under_postflop_pressure(
                info,
                stats_context,
                strength,
                call_amount,
                pot,
                call_ratio,
                players_in_hand,
            ):
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if self._should_fold_river_medium_strength(info, stats_context, players_in_hand, call_amount, pot, call_ratio):
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if info["top_pair"] and info["kicker_strength"] < 0.45 and call_ratio > 0.16:
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if info["second_pair"] and players_in_hand > 2 and call_ratio > 0.08:
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            action = self._passive_action(call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        if call_amount > 0 and info["overpair"]:
            small_bet = call_ratio <= 0.12 or (pot > 0 and (call_amount / max(pot, 1.0)) <= 0.33)
            board_not_extreme = info["board_texture"] not in {"very_wet", "monotone"}
            if small_bet or board_not_extreme:
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

        if call_amount > 0 and info["top_pair"] and info["kicker_strength"] >= 0.70:
            cheap_continue = call_ratio <= 0.08 or (pot > 0 and (call_amount / max(pot, 1.0)) <= 0.25)
            if cheap_continue:
                action = self._passive_action(call_amount)
                self._record_stats_decision(action, stats_context)
                return action

        approx_equity = 0.0
        if info["combo_draw"]:
            approx_equity = 0.40
        elif info["flush_draw_with_hole"] and len(board_cards) == 3:
            approx_equity = 0.35
        elif info["straight_draw_with_hole"] and len(board_cards) == 3:
            approx_equity = 0.28
        elif info["flush_draw_with_hole"] or info["straight_draw_with_hole"]:
            approx_equity = 0.20

        if call_amount > 0 and approx_equity > 0 and pot_odds_req <= approx_equity:
            if self._should_fold_under_postflop_pressure(
                info,
                stats_context,
                strength,
                call_amount,
                pot,
                call_ratio,
                players_in_hand,
            ):
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action
            action = self._passive_action(call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        if call_amount == 0:
            if (
                _norm_text((stats_context or {}).get("street", "")) in {"flop", "turn"}
                and (
                    info["overpair"]
                    or (info["top_pair"] and info["kicker_strength"] >= 0.70)
                    or info["two_pair_with_hole"]
                )
            ):
                amount = self._raise_amount(
                    state,
                    stack,
                    0.67 if players_in_hand > 2 else 0.71,
                    "postflop",
                    self._with_bet_profile(stats_context, "value_medium"),
                )
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            if (
                _norm_text((stats_context or {}).get("street", "")) in {"flop", "turn"}
                and players_in_hand <= 2
                and (
                    (info["top_pair"] and info["kicker_strength"] >= 0.28)
                    or (
                        info["second_pair"]
                        and (
                            info["kicker_strength"] >= 0.45
                            or info["flush_draw_with_hole"]
                            or info["straight_draw_with_hole"]
                        )
                    )
                )
            ):
                amount = self._raise_amount(
                    state,
                    stack,
                    0.60 if _norm_text((stats_context or {}).get("street", "")) == "turn" else 0.63,
                    "postflop",
                    self._with_bet_profile(stats_context, "value_medium"),
                )
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            if (
                _norm_text((stats_context or {}).get("street", "")) in {"flop", "turn"}
                and players_in_hand <= 2
                and (
                    info["combo_draw"]
                    or info["nut_flush_draw"]
                    or info["flush_draw_with_hole"]
                    or info["straight_draw_with_hole"]
                )
            ):
                amount = self._raise_amount(
                    state,
                    stack,
                    0.59 if info["straight_draw_with_hole"] and not info["flush_draw_with_hole"] else 0.62,
                    "postflop",
                    self._with_bet_profile(stats_context, "semibluff_medium"),
                )
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            if self._should_stab(info, stats_context):
                amount = self._raise_amount(
                    state,
                    stack,
                    0.64 if players_in_hand > 2 else 0.68,
                    "postflop",
                    self._with_bet_profile(stats_context, "stab_small"),
                )
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            action = self._passive_action(call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        action = BotAction("fold")
        self._record_stats_decision(action, stats_context)
        return action

    def _record_stats_decision(
        self,
        action: BotAction,
        stats_context: Optional[Dict[str, Any]],
    ) -> None:
        if not stats_context:
            return

        self.stats_tracker.record_decision(
            street=stats_context.get("street", ""),
            action_kind=action.kind,
            call_amount=_safe_int(stats_context.get("call_amount", 0), 0),
            raise_count_before_action=_safe_int(stats_context.get("raise_count_before_action", 0), 0),
            is_cbet_opportunity=bool(stats_context.get("is_cbet_opportunity", False)),
            is_facing_cbet=bool(stats_context.get("is_facing_cbet", False)),
        )


# =========================================================
# CONTEXT BUILDER
# =========================================================

def build_stats_context(
    street: str,
    call_amount: int,
    raise_count_before_action: int,
    position: str = "",
    players_in_hand: int = 0,
    opponents: Optional[List[Dict[str, Any]]] = None,
    is_cbet_opportunity: bool = False,
    is_facing_cbet: bool = False,
    big_blind: float = 0.0,
    pot: float = 0.0,
    hero_stack_bb: float = 0.0,
    effective_stack_bb: float = 0.0,
    limper_count: int = 0,
    is_limped_pot: bool = False,
    pot_was_limped_preflop: bool = False,
    players_acted_this_street: int = 0,
    players_yet_to_act: int = 0,
    current_street_aggressor_position: str = "",
    preflop_aggressor_position: str = "",
    hero_has_initiative: bool = False,
    hero_is_preflop_aggressor: bool = False,
    hero_is_current_street_aggressor: bool = False,
    last_action_kind: str = "",
    last_action_street: str = "",
    last_action_position: str = "",
    last_actor_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "street": street,
        "call_amount": call_amount,
        "raise_count_before_action": raise_count_before_action,
        "position": position,
        "players_in_hand": players_in_hand,
        "opponents": opponents or [],
        "is_cbet_opportunity": is_cbet_opportunity,
        "is_facing_cbet": is_facing_cbet,
        "big_blind": big_blind,
        "pot": pot,
        "hero_stack_bb": hero_stack_bb,
        "effective_stack_bb": effective_stack_bb,
        "limper_count": limper_count,
        "is_limped_pot": is_limped_pot,
        "pot_was_limped_preflop": pot_was_limped_preflop,
        "players_acted_this_street": players_acted_this_street,
        "players_yet_to_act": players_yet_to_act,
        "current_street_aggressor_position": current_street_aggressor_position,
        "preflop_aggressor_position": preflop_aggressor_position,
        "hero_has_initiative": hero_has_initiative,
        "hero_is_preflop_aggressor": hero_is_preflop_aggressor,
        "hero_is_current_street_aggressor": hero_is_current_street_aggressor,
        "last_action_kind": last_action_kind,
        "last_action_street": last_action_street,
        "last_action_position": last_action_position,
        "last_actor_stats": last_actor_stats or {},
    }


# =========================================================
# FINAL BOT CLASS
# =========================================================

class BotNegreanu_V2(SmartParametricBot):
    BotConfig = negreanu_V2_BotConfig
    BotAction = BotAction

    def __init__(self, config: Optional[negreanu_V2_BotConfig] = None, profile_name: Optional[str] = None):
        if config is None:
            config = make_profile(profile_name or "blind_stealer")
        super().__init__(config)
