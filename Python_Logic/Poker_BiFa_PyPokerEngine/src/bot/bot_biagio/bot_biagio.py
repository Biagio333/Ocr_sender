from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
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


@dataclass
class biagio_BotConfig:
    name: str = "smart"

    aggression: float = 0.55
    looseness: float = 0.50

    preflop_raise_threshold: float = 0.73
    preflop_call_threshold: float = 0.46

    postflop_raise_threshold: float = 0.79
    postflop_call_threshold: float = 0.50

    cheap_call_bonus: float = 0.10
    draw_bonus: float = 0.10
    top_pair_bonus: float = 0.10
    overpair_bonus: float = 0.16
    set_bonus: float = 0.20
    combo_draw_bonus: float = 0.10
    nut_flush_draw_bonus: float = 0.05


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
    return RANK_ORDER.index(RANK_MAP.get(rank, "2"))


def card_rank_index(card) -> int:
    rank, _ = parse_card(card)
    return rank_to_index(rank)


def card_suit(card) -> str:
    _, suit = parse_card(card)
    return suit


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


def _is_late_position(position: str) -> bool:
    return position in {"HJ", "CO", "BTN"}


def _is_early_position(position: str) -> bool:
    return position in {"UTG", "UTG+1", "EP"}


def _is_blind(position: str) -> bool:
    return position in {"SB", "BB"}


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
            0: 0.44,   # 22
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
            12: 0.99,  # AA
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

    # posizione
    if _is_late_position(position):
        score += 0.04
    elif _is_early_position(position):
        score -= 0.04
    elif _is_blind(position):
        score -= 0.02

    # short-handed
    if players_in_hand <= 4:
        score += 0.04
    elif players_in_hand >= 7:
        score -= 0.02

    # stack depth
    if stack_bb > 0:
        if stack_bb <= 12:
            # meno mani speculative, più mani che tengono bene preflop
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
    if {12, 0, 1, 2, 3}.issubset(set(vals)):  # wheel
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


def _rank_counter(cards) -> Counter:
    return Counter(_all_rank_indices(cards))


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

    hole_counter = Counter(hole_ranks)
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
    flush_draw = has_flush_draw(all_cards)
    straight = has_straight(all_ranks)
    straight_draw = has_straight_draw(all_ranks)

    pair_ranks = [r for r, c in all_counter.items() if c >= 2]
    trip_ranks = [r for r, c in all_counter.items() if c >= 3]

    board_pair = any(c >= 2 for c in board_counter.values())
    board_trips = any(c >= 3 for c in board_counter.values())

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

    if hole_pair_ranks and board_cards:
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
    if flush_draw:
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

    combo_draw = flush_draw and straight_draw

    hand_from_board_only = False
    if board_cards:
        board_flush = has_flush(board_cards)
        board_straight = has_straight(board_ranks)
        board_full_house = len(board_cards) >= 5 and (
            sorted(Counter(board_ranks).values(), reverse=True)[:2] == [3, 2]
        )
        if (board_flush or board_straight or board_full_house) and not any(
            r in pair_ranks for r in hole_ranks
        ):
            hand_from_board_only = True

    return {
        "pair": pair,
        "two_pair": two_pair,
        "trips": trips,
        "straight": straight,
        "flush": flush,
        "full_house": full_house,
        "quads": quads,
        "flush_draw": flush_draw,
        "straight_draw": straight_draw,
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
    if info["board_trips"] and (info["top_pair"] or info["overpair"]):
        penalty += 0.06

    return penalty


def _has_real_showdown_value(info: Dict[str, Any]) -> bool:
    return any([
        info["top_pair"],
        info["second_pair"],
        info["weak_pair"],
        info["overpair"],
        info["two_pair"],
        info["trips_with_hole"],
        info["set_made"],
        info["straight"],
        info["flush"],
        info["full_house"],
        info["quads"],
    ])


def postflop_strength(hole_cards, board_cards, cfg: biagio_BotConfig, players_in_hand: int = 2) -> float:
    info = classify_postflop(hole_cards, board_cards)

    score = 0.0

    # made hands
    if info["weak_pair"]:
        score += 0.17
    if info["second_pair"]:
        score += 0.24
    if info["top_pair"]:
        score += 0.32 + (cfg.top_pair_bonus * info["kicker_strength"])
    if info["overpair"]:
        score += 0.42 + cfg.overpair_bonus
    if info["two_pair"]:
        score += 0.60
    if info["trips_with_hole"]:
        score += 0.69
    if info["set_made"]:
        score += 0.82 + cfg.set_bonus
    if info["straight"]:
        score += 0.78
    if info["flush"]:
        score += 0.80
    if info["full_house"]:
        score += 0.94
    if info["quads"]:
        score += 1.00

    # draws
    if info["flush_draw"]:
        score += cfg.draw_bonus
    if info["straight_draw"]:
        score += cfg.draw_bonus * 0.80
    if info["combo_draw"]:
        score += cfg.combo_draw_bonus
    if info["nut_flush_draw"]:
        score += cfg.nut_flush_draw_bonus

    # overcards
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
    def __init__(self, config: biagio_BotConfig):
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

    def get_stats_snapshot(self) -> Dict[str, float | str | int]:
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

        if street == "preflop":
            bb = _safe_float(stats_context.get("big_blind", 0.0), 0.0) if stats_context else 0.0
            raise_count = _safe_int(stats_context.get("raise_count_before_action", 0), 0) if stats_context else 0
            position = stats_context.get("position", "") if stats_context else ""

            if bb > 0:
                if raise_count == 0:
                    mult = 2.5 if _is_late_position(position) else 3.0
                    if _is_blind(position) or _is_early_position(position):
                        mult += 0.3
                    target = int(round(bb * mult))
                else:
                    # 3bet / iso più decisa ma non folle
                    target = max(min_raise, call_amount * 3)
            else:
                factor = _clamp((self.config.aggression * 0.55) + (strength * 0.45), 0.20, 0.75)
                target = min_raise + int((max_raise - min_raise) * factor)
        else:
            if pot > 0:
                if strength >= 0.88:
                    target = int(round(pot * 0.75))
                elif strength >= 0.75:
                    target = int(round(pot * 0.60))
                else:
                    target = int(round(pot * 0.50))
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
        avg_vpip = _avg_stat(opponents, "vpip", 0.28)
        avg_pfr = _avg_stat(opponents, "pfr", 0.18)
        avg_af = _avg_stat(opponents, "af", 1.5)
        avg_fold_to_raise = _avg_stat(opponents, "fold_to_raise", 0.35)
        avg_three_bet = _avg_stat(opponents, "3bet", 0.10)

        position = stats_context.get("position", "")
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        hero_stack_bb = _safe_float(stats_context.get("hero_stack_bb", 0.0), 0.0)

        if _is_late_position(position):
            strength += 0.03
        elif _is_early_position(position):
            strength -= 0.04

        if players_in_hand <= 4:
            strength += 0.03
        elif players_in_hand >= 7:
            strength -= 0.02

        if avg_fold_to_raise > 0.45 and _is_late_position(position):
            strength += 0.03

        if avg_three_bet > 0.16 or avg_pfr > 0.24:
            strength -= 0.04

        if avg_vpip > 0.40:
            # meno steal light vs calling stations
            strength -= 0.03

        if avg_af > 2.2 and call_ratio > 0.08:
            strength -= 0.04

        if 0 < hero_stack_bb <= 12:
            if call_ratio > 0.12:
                strength -= 0.06
            else:
                strength += 0.03

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
        avg_fold_to_cbet = _avg_stat(opponents, "fold_to_cbet", 0.35)
        avg_wtsd = _avg_stat(opponents, "wtsd", 0.30)
        avg_af = _avg_stat(opponents, "af", 1.5)
        avg_vpip = _avg_stat(opponents, "vpip", 0.28)
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)
        is_cbet_opportunity = bool(stats_context.get("is_cbet_opportunity", False))
        is_facing_cbet = bool(stats_context.get("is_facing_cbet", False))

        if is_cbet_opportunity and len(board_cards) == 3:
            if avg_fold_to_cbet > 0.48 and not info["hand_from_board_only"]:
                strength += 0.04
            elif avg_fold_to_cbet < 0.28:
                strength -= 0.04

        if players_in_hand > 2:
            if info["top_pair"] or info["second_pair"] or info["overpair"]:
                strength -= 0.05
            else:
                strength -= 0.03

        if avg_wtsd > 0.36 or avg_vpip > 0.40:
            if not _has_real_showdown_value(info):
                strength -= 0.05

        if is_facing_cbet and avg_af > 2.3 and call_ratio > 0.10:
            strength -= 0.05

        if info["top_pair"] and info["board_texture"] in {"wet", "very_wet", "monotone", "paired_wet"}:
            strength -= 0.05

        if info["overpair"] and info["board_texture"] in {"wet", "very_wet", "monotone", "paired", "paired_wet"}:
            strength -= 0.04

        if info["combo_draw"]:
            strength += 0.04

        if info["flush_draw"] and info["straight_draw"] and call_ratio <= 0.10:
            strength += 0.02

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
        avg_fold_to_raise = _avg_stat(opponents, "fold_to_raise", 0.35)
        avg_three_bet = _avg_stat(opponents, "3bet", 0.10)
        position = stats_context.get("position", "")
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)

        if avg_fold_to_raise > 0.45 and _is_late_position(position):
            raise_threshold -= 0.03
        if avg_three_bet > 0.16:
            raise_threshold += 0.04
            call_threshold += 0.03
        if players_in_hand <= 4:
            raise_threshold -= 0.02
            call_threshold -= 0.02

        return _clamp(raise_threshold, 0.45, 0.92), _clamp(call_threshold, 0.25, 0.78)

    def _postflop_thresholds(
        self,
        stats_context: Optional[Dict[str, Any]],
    ) -> Tuple[float, float]:
        raise_threshold = self.config.postflop_raise_threshold
        call_threshold = self.config.postflop_call_threshold

        if not stats_context:
            return raise_threshold, call_threshold

        opponents = stats_context.get("opponents", [])
        avg_fold_to_cbet = _avg_stat(opponents, "fold_to_cbet", 0.35)
        avg_wtsd = _avg_stat(opponents, "wtsd", 0.30)
        players_in_hand = _safe_int(stats_context.get("players_in_hand", len(opponents) + 1), len(opponents) + 1)

        if avg_fold_to_cbet > 0.48:
            raise_threshold -= 0.03
        if avg_wtsd > 0.38:
            raise_threshold += 0.03
            call_threshold += 0.03
        if players_in_hand > 2:
            raise_threshold += 0.02
            call_threshold += 0.02

        return _clamp(raise_threshold, 0.52, 0.92), _clamp(call_threshold, 0.28, 0.82)

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

        position = stats_context.get("position", "") if stats_context else ""
        players_in_hand = _safe_int(stats_context.get("players_in_hand", 2), 2) if stats_context else 2

        if is_preflop:
            strength = preflop_strength(
                hole_cards,
                position=position,
                players_in_hand=players_in_hand,
                stack_bb=effective_stack_bb if effective_stack_bb > 0 else stack_bb,
            )
            strength += (self.config.looseness - 0.5) * 0.22

            if call_ratio < 0.035:
                strength += self.config.cheap_call_bonus * 0.50

            strength = self._adapt_preflop_strength(strength, stats_context, call_ratio)
            preflop_raise_threshold, preflop_call_threshold = self._preflop_thresholds(stats_context)

            # short stack: più raise/fold, meno flat marginali
            if 0 < effective_stack_bb <= 12:
                if strength >= max(0.62, preflop_raise_threshold - 0.08):
                    amount = self._raise_amount(state, stack, strength, "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if call_amount == 0 and strength >= max(0.48, preflop_call_threshold - 0.04):
                    amount = self._raise_amount(state, stack, max(strength, 0.55), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                if call_amount == 0:
                    action = BotAction("call", 0)
                    self._record_stats_decision(action, stats_context)
                    return action

                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            if strength >= preflop_raise_threshold:
                amount = self._raise_amount(state, stack, strength, "preflop", stats_context)
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            if strength >= preflop_call_threshold:
                action = BotAction("call", call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if call_amount == 0:
                # steal più attivo da late position
                if _is_late_position(position) and strength >= preflop_call_threshold - 0.10:
                    amount = self._raise_amount(state, stack, max(strength, 0.55), "preflop", stats_context)
                    if amount is not None:
                        action = BotAction("raise", amount)
                        self._record_stats_decision(action, stats_context)
                        return action

                action = BotAction("call", 0)
                self._record_stats_decision(action, stats_context)
                return action

            if call_ratio < 0.02 and strength >= preflop_call_threshold - 0.05:
                action = BotAction("call", call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            action = BotAction("fold")
            self._record_stats_decision(action, stats_context)
            return action

        # POSTFLOP
        info = classify_postflop(hole_cards, board_cards)
        strength = postflop_strength(hole_cards, board_cards, self.config, players_in_hand=players_in_hand)
        strength += (self.config.looseness - 0.5) * 0.08

        if call_ratio < 0.03:
            strength += self.config.cheap_call_bonus * 0.25

        strength = self._adapt_postflop_strength(
            strength,
            stats_context,
            call_ratio,
            board_cards,
            hole_cards,
        )

        postflop_raise_threshold, postflop_call_threshold = self._postflop_thresholds(stats_context)

        if strength >= postflop_raise_threshold:
            amount = self._raise_amount(state, stack, strength, "postflop", stats_context)
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if info["combo_draw"] and strength >= postflop_raise_threshold - 0.05 and call_ratio <= 0.10:
            amount = self._raise_amount(state, stack, strength, "postflop", stats_context)
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if strength >= postflop_call_threshold:
            # top pair kicker debole su size grossa: evita hero call leggeri
            if info["top_pair"] and info["kicker_strength"] < 0.45 and call_ratio > 0.18:
                action = BotAction("fold")
                self._record_stats_decision(action, stats_context)
                return action

            action = BotAction("call", call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        # draw call guidati da pot odds
        approx_equity = 0.0
        if info["combo_draw"]:
            approx_equity = 0.40
        elif info["flush_draw"] and len(board_cards) == 3:
            approx_equity = 0.35
        elif info["straight_draw"] and len(board_cards) == 3:
            approx_equity = 0.28
        elif info["flush_draw"] or info["straight_draw"]:
            approx_equity = 0.20

        if call_amount > 0 and approx_equity > 0 and pot_odds_req <= approx_equity:
            action = BotAction("call", call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        # bluff catcher economico
        if call_ratio <= 0.06 and (info["top_pair"] or info["second_pair"]):
            action = BotAction("call", call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        if call_amount == 0:
            action = BotAction("call", 0)
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
        if (
            stats_context
            and action.kind == "raise"
            and _safe_int(stats_context.get("raise_count_before_action", 0), 0) >= 2
        ):
            call_amount = _safe_int(stats_context.get("call_amount", 0), 0)
            action.kind = "check" if call_amount <= 0 else "call"
            action.amount = None if call_amount <= 0 else call_amount

        if not stats_context:
            return

        self.stats_tracker.record_decision(
            street=stats_context["street"],
            action_kind=action.kind,
            call_amount=stats_context["call_amount"],
            raise_count_before_action=stats_context["raise_count_before_action"],
            is_cbet_opportunity=stats_context.get("is_cbet_opportunity", False),
            is_facing_cbet=stats_context.get("is_facing_cbet", False),
        )


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
    }


class BotBiagio(SmartParametricBot):
    BotConfig = biagio_BotConfig
    BotAction = BotAction
