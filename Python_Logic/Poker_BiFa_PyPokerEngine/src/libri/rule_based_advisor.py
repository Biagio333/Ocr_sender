import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from treys import Card, Evaluator


_HAND_EVALUATOR = Evaluator()


# =============================================================================
# ENUM E CONFIG
# =============================================================================

class HandCategory(Enum):
    PREMIUM = "premium"          # AA, KK, QQ, AK
    STRONG = "strong"            # JJ, TT, AQs, AJs, KQs
    MEDIUM = "medium"            # 99-77, AQo, ATs, KJs, QJs, JTs
    SPECULATIVE = "speculative"  # 66-22, A9s-A2s, suited connectors
    WEAK = "weak"                # offsuit broadway marginali
    TRASH = "trash"


class PlayerType(Enum):
    UNKNOWN = "unknown"
    NIT = "nit"
    TAG = "tag"
    LAG = "lag"
    MANIAC = "maniac"
    STATION = "station"
    FISH = "fish"


@dataclass
class AdvisorProfileConfig:
    name: str = "cash_mixed"
    game_type: str = "cash"
    play_style: str = "mixed"

    short_stack_bb: float = 15.0
    medium_stack_bb: float = 40.0

    preflop_base_shift: float = 0.0
    preflop_open_shift: float = 0.0
    preflop_call_shift: float = 0.0
    preflop_3bet_shift: float = 0.0
    preflop_speculative_shift: float = 0.0
    preflop_short_stack_tightening: float = 0.0
    preflop_deep_stack_loosening: float = 0.0

    postflop_base_shift: float = 0.0
    postflop_raise_shift: float = 0.0
    postflop_call_shift: float = 0.0
    postflop_bluff_shift: float = 0.0
    postflop_draw_shift: float = 0.0
    postflop_thin_value_shift: float = 0.0

    tournament_survival_bias: float = 0.0
    cash_ev_bias: float = 0.0

    open_size_mult: float = 1.0
    iso_size_mult: float = 1.0
    raise_size_mult: float = 1.0
    postflop_bet_size_mult: float = 1.0


_PROFILE_LIBRARY: Dict[str, AdvisorProfileConfig] = {
    "cash_aggressive": AdvisorProfileConfig(
        name="cash_aggressive",
        play_style="aggressive",
        preflop_base_shift=0.04,
        preflop_open_shift=0.03,
        postflop_raise_shift=0.03,
        postflop_bluff_shift=0.03,
    ),
    "cash_conservative": AdvisorProfileConfig(
        name="cash_conservative",
        play_style="conservative",
        preflop_base_shift=-0.03,
        preflop_call_shift=-0.02,
        postflop_bluff_shift=-0.05,
    ),
    "cash_mixed": AdvisorProfileConfig(name="cash_mixed"),
}


def get_advisor_profile(
    profile_name: Optional[str] = None,
    game_type: str = "cash",
    play_style: str = "mixed",
) -> AdvisorProfileConfig:
    if profile_name and profile_name in _PROFILE_LIBRARY:
        return _PROFILE_LIBRARY[profile_name]
    key = f"{game_type}_{play_style}"
    return _PROFILE_LIBRARY.get(key, _PROFILE_LIBRARY["cash_mixed"])


# =============================================================================
# UTILITY
# =============================================================================

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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _extract_amount(text: Any) -> Optional[float]:
    matches = re.findall(r"\d+(?:[\.,]\d+)?", str(text or ""))
    if not matches:
        return None
    return float(matches[-1].replace(",", "."))


def _parse_player_type(raw: Any) -> PlayerType:
    s = _normalize_text(raw)
    mapping = {
        "nit": PlayerType.NIT,
        "tag": PlayerType.TAG,
        "lag": PlayerType.LAG,
        "maniac": PlayerType.MANIAC,
        "station": PlayerType.STATION,
        "calling_station": PlayerType.STATION,
        "fish": PlayerType.FISH,
        "unknown": PlayerType.UNKNOWN,
    }
    return mapping.get(s, PlayerType.UNKNOWN)


def _action_kind_from_label(label: Any) -> Optional[str]:
    normalized = _normalize_text(label)
    if any(t in normalized for t in ("fold", "passa", "muck")):
        return "fold"
    if "check" in normalized:
        return "check"
    if any(t in normalized for t in ("call", "chiama")):
        return "call"
    if any(t in normalized for t in ("raise", "rilancia")):
        return "raise"
    if any(t in normalized for t in ("bet", "punta")):
        return "bet"
    return None


def _find_action(table_actions: List[Dict[str, Any]], desired_kind: str) -> Optional[Dict[str, Any]]:
    if not table_actions:
        return None

    candidates = [
        a for a in table_actions
        if _action_kind_from_label(a.get("label", "")) == desired_kind
    ]
    if not candidates:
        return None

    if desired_kind in {"raise", "bet"}:
        return min(candidates, key=lambda a: _extract_amount(a.get("label", "")) or float("inf"))
    return candidates[0]


def _amount_button_target_value(label: str, table_state: Dict[str, Any]) -> Optional[float]:
    normalized = _normalize_text(label)
    pot = _safe_float(table_state.get("pot_size", 0.0))
    bb = max(_safe_float(table_state.get("big_blind", 1.0)), 1e-9)
    min_raise = _safe_float(table_state.get("min_raise", 0.0))
    hero_stack = _safe_float(table_state.get("hero_stack", 0.0))
    villain_stack = _safe_float(table_state.get("villain_stack", 0.0))
    eff_stack = min(hero_stack, villain_stack) if villain_stack > 0 else hero_stack

    if "min" in normalized:
        return min_raise if min_raise > 0 else bb * 2
    if any(t in normalized for t in ("max", "all")):
        return eff_stack
    if any(t in normalized for t in ("pot", "piatto")):
        return pot
    if "half" in normalized or "1/2" in normalized:
        return pot * 0.5
    if "2/3" in normalized:
        return pot * (2 / 3)
    if "3/4" in normalized:
        return pot * 0.75

    amt = _extract_amount(normalized)
    if amt is None:
        return None
    if "bb" in normalized or "blind" in normalized:
        return amt * bb
    return amt


def _select_amount_button(
    amount_buttons: List[Dict[str, Any]],
    target_amount: Optional[float],
    table_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not amount_buttons or target_amount is None or target_amount <= 0:
        return None

    best_btn = None
    best_diff = float("inf")
    for btn in amount_buttons:
        val = _amount_button_target_value(btn.get("label", ""), table_state)
        if val is None:
            continue
        diff = abs(val - target_amount)
        if diff < best_diff:
            best_diff = diff
            best_btn = btn
    return best_btn


# =============================================================================
# HAND / BOARD HELPERS
# =============================================================================

_RANK_ORDER = "23456789TJQKA"
_RANK_TO_VALUE = {r: i + 2 for i, r in enumerate(_RANK_ORDER)}


def _hero_cards_normalized(hero_cards: Any) -> List[str]:
    if not isinstance(hero_cards, (list, tuple)) or len(hero_cards) != 2:
        return []
    out: List[str] = []
    for c in hero_cards:
        if isinstance(c, str) and len(c) >= 2:
            out.append(c[:2].upper())
    return out if len(out) == 2 else []


def _card_rank(card: str) -> str:
    return card[0].upper() if card else ""


def _card_suit(card: str) -> str:
    return card[1].lower() if len(card) > 1 else ""


def _rank_value(rank: str) -> int:
    return _RANK_TO_VALUE.get(rank, 0)


def _is_suited(cards: List[str]) -> bool:
    return len(cards) == 2 and _card_suit(cards[0]) == _card_suit(cards[1])


def _hand_to_category(hero_cards: Any) -> HandCategory:
    cards = _hero_cards_normalized(hero_cards)
    if len(cards) != 2:
        return HandCategory.TRASH

    r1, r2 = _card_rank(cards[0]), _card_rank(cards[1])
    v1, v2 = _rank_value(r1), _rank_value(r2)
    suited = _is_suited(cards)

    if v1 < v2:
        v1, v2 = v2, v1
        r1, r2 = r2, r1

    if v1 == v2:
        if v1 >= 12:   # AA KK QQ
            return HandCategory.PREMIUM
        if v1 >= 10:   # JJ TT
            return HandCategory.STRONG
        if v1 >= 7:    # 99 88 77
            return HandCategory.MEDIUM
        return HandCategory.SPECULATIVE

    if (r1, r2) == ("A", "K"):
        return HandCategory.PREMIUM

    if suited and (r1, r2) in {("A", "Q"), ("A", "J"), ("K", "Q")}:
        return HandCategory.STRONG

    if (r1, r2) == ("A", "Q") and not suited:
        return HandCategory.MEDIUM

    if suited and r1 == "A" and v2 <= 9:
        return HandCategory.SPECULATIVE

    if suited and v1 - v2 <= 1 and v2 >= 5:
        return HandCategory.SPECULATIVE

    if suited and v1 >= 11 and v2 >= 10:
        return HandCategory.MEDIUM

    if not suited and r1 == "A" and r2 in {"J", "T"}:
        return HandCategory.WEAK

    if not suited and v1 >= 12 and v2 >= 10:
        return HandCategory.WEAK

    if v1 <= 8 and v2 <= 5:
        return HandCategory.TRASH

    return HandCategory.WEAK


def _analyze_postflop_hand(hero_cards: Any, board_cards: Any) -> Dict[str, Any]:
    hero = _hero_cards_normalized(hero_cards)
    board = [str(c)[:2].upper() for c in (board_cards or []) if isinstance(c, str) and len(c) >= 2]

    result = {
        "made_hand": "High Card",
        "hand_strength": 0,
        "bucket": "air",
        "flush_draw": False,
        "straight_draw": False,
        "combo_draw": False,
        "overcards": 0,
    }

    if len(hero) != 2 or len(board) < 3:
        return result

    try:
        hero_t = [Card.new(c) for c in hero]
        board_t = [Card.new(c) for c in board]

        score = _HAND_EVALUATOR.evaluate(board_t, hero_t)
        rank_class = _HAND_EVALUATOR.get_rank_class(score)
        class_str = _HAND_EVALUATOR.class_to_string(rank_class)

        result["made_hand"] = class_str

        strength_map = {
            "Straight Flush": 9,
            "Four of a Kind": 8,
            "Full House": 7,
            "Flush": 6,
            "Straight": 5,
            "Three of a Kind": 4,
            "Two Pair": 3,
            "Pair": 2,
            "High Card": 1,
        }
        result["hand_strength"] = strength_map.get(class_str, 0)

        if result["hand_strength"] >= 7:
            result["bucket"] = "monster"
        elif result["hand_strength"] >= 5:
            result["bucket"] = "strong"
        elif result["hand_strength"] >= 3:
            result["bucket"] = "medium"
        elif result["hand_strength"] == 2:
            result["bucket"] = "weak_pair"
        else:
            result["bucket"] = "air"
    except Exception:
        return result

    all_cards = hero + board

    suit_counts: Dict[str, int] = {}
    for c in all_cards:
        s = _card_suit(c)
        suit_counts[s] = suit_counts.get(s, 0) + 1
    if any(count == 4 for count in suit_counts.values()):
        result["flush_draw"] = True

    ranks = sorted(set(_rank_value(_card_rank(c)) for c in all_cards))
    if 14 in ranks:
        ranks = [1] + ranks

    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] <= 4:
            result["straight_draw"] = True
            break

    result["combo_draw"] = result["flush_draw"] and result["straight_draw"]

    board_ranks = [_rank_value(_card_rank(c)) for c in board]
    max_board = max(board_ranks) if board_ranks else 0
    hero_ranks = [_rank_value(_card_rank(c)) for c in hero]
    result["overcards"] = sum(1 for r in hero_ranks if r > max_board)

    return result


# =============================================================================
# PREFLOP
# =============================================================================

def _detect_preflop_spot(table_state: Dict[str, Any]) -> str:
    bb = max(_safe_float(table_state.get("big_blind", 1.0)), 1e-9)
    to_call = _safe_float(table_state.get("to_call", 0.0))
    hero_bet = _safe_float(table_state.get("hero_bet", 0.0))
    highest_bet = hero_bet + to_call

    if highest_bet <= bb:
        return "unopened" if to_call <= 0 else "limped"

    if highest_bet <= 4 * bb:
        return "facing_raise"

    return "facing_3bet"


def _preflop_short_stack(
    category: HandCategory,
    spot: str,
    eff_stack_bb: float,
    can_raise: bool,
    can_call: bool,
    can_fold: bool,
) -> Dict[str, Any]:
    if eff_stack_bb <= 10:
        push_range = {
            HandCategory.PREMIUM,
            HandCategory.STRONG,
            HandCategory.MEDIUM,
            HandCategory.SPECULATIVE,
        }
    elif eff_stack_bb <= 15:
        push_range = {
            HandCategory.PREMIUM,
            HandCategory.STRONG,
            HandCategory.MEDIUM,
        }
    else:
        push_range = {
            HandCategory.PREMIUM,
            HandCategory.STRONG,
        }

    if spot in {"unopened", "limped"} and category in push_range and can_raise:
        return {
            "action": "raise",
            "confidence": 0.85,
            "reason": f"Push {eff_stack_bb:.0f}bb",
            "debug": {
                "category": category.value,
                "spot": spot,
                "eff_stack_bb": round(eff_stack_bb, 2),
                "sizing": "all-in",
                "selected_amount_label": "max",
            },
        }

    if spot == "facing_raise" and category in {HandCategory.PREMIUM, HandCategory.STRONG}:
        if can_raise:
            return {
                "action": "raise",
                "confidence": 0.8,
                "reason": "Jam vs raise short",
                "debug": {
                    "category": category.value,
                    "spot": spot,
                    "eff_stack_bb": round(eff_stack_bb, 2),
                    "all_in": True,
                },
            }
        if can_call:
            return {
                "action": "call",
                "confidence": 0.65,
                "reason": "Call short stack",
                "debug": {
                    "category": category.value,
                    "spot": spot,
                    "eff_stack_bb": round(eff_stack_bb, 2),
                },
            }

    action = "fold" if can_fold else "check"
    return {
        "action": action,
        "confidence": 0.9,
        "reason": f"Fold short stack {category.value}",
        "debug": {
            "category": category.value,
            "spot": spot,
            "eff_stack_bb": round(eff_stack_bb, 2),
        },
    }


def decide_preflop_action(
    table_state: Dict[str, Any],
    advisor_profile: Optional[AdvisorProfileConfig] = None,
) -> Dict[str, Any]:
    profile = advisor_profile or get_advisor_profile()

    hero_cards = table_state.get("hero_cards", [])
    category = _hand_to_category(hero_cards)

    bb = max(_safe_float(table_state.get("big_blind", 1.0)), 1e-9)
    to_call = _safe_float(table_state.get("to_call", 0.0))
    to_call_bb = to_call / bb

    hero_stack = _safe_float(table_state.get("hero_stack", 0.0))
    villain_stack = _safe_float(table_state.get("villain_stack", 0.0))
    eff_stack = min(hero_stack, villain_stack) if villain_stack > 0 else hero_stack
    eff_stack_bb = eff_stack / bb

    position = _normalize_text(table_state.get("hero_position", ""))
    villain_type = _parse_player_type(table_state.get("villain_type", "unknown"))
    num_players_in_hand = max(_safe_int(table_state.get("players_in_hand", 2)), 2)
    num_limppers = max(_safe_int(table_state.get("num_limppers", 0)), 0)

    available = table_state.get("available_actions", [])
    can_raise = any(_action_kind_from_label(a.get("label", "")) in {"raise", "bet"} for a in available)
    can_call = any(_action_kind_from_label(a.get("label", "")) == "call" for a in available)
    can_check = any(_action_kind_from_label(a.get("label", "")) == "check" for a in available)
    can_fold = any(_action_kind_from_label(a.get("label", "")) == "fold" for a in available)

    spot = _detect_preflop_spot(table_state)

    if eff_stack_bb <= 20:
        return _preflop_short_stack(category, spot, eff_stack_bb, can_raise, can_call, can_fold)

    open_ranges = {
        "utg": {HandCategory.PREMIUM, HandCategory.STRONG},
        "mp": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM},
        "co": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM, HandCategory.SPECULATIVE},
        "btn": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM, HandCategory.SPECULATIVE, HandCategory.WEAK},
        "sb": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM},
        "bb": set(),
    }

    action = "fold"
    sizing = None
    reason = ""

    if spot == "unopened":
        allowed = open_ranges.get(position, {HandCategory.PREMIUM, HandCategory.STRONG})

        if villain_type == PlayerType.STATION:
            allowed = {c for c in allowed if c != HandCategory.SPECULATIVE}

        if category in allowed and can_raise:
            open_size_bb = {
                "utg": 2.5,
                "mp": 2.5,
                "co": 2.2,
                "btn": 2.0,
                "sb": 2.8,
            }.get(position, 2.5)
            sizing = open_size_bb * bb * profile.open_size_mult
            action = "raise"
            reason = f"Open {position or 'default'} con {category.value}"
        elif can_check:
            action = "check"
            reason = "Check"
        else:
            action = "fold" if can_fold else "check"
            reason = f"Fold {category.value}"

    elif spot == "limped":
        iso_range = {
            HandCategory.PREMIUM,
            HandCategory.STRONG,
            HandCategory.MEDIUM,
        }
        if position in {"co", "btn", "sb"}:
            iso_range.add(HandCategory.SPECULATIVE)

        if villain_type in {PlayerType.STATION, PlayerType.FISH}:
            iso_range.discard(HandCategory.SPECULATIVE)

        if category in iso_range and can_raise:
            limpers = max(num_limppers, max(num_players_in_hand - 2, 1))
            sizing = (3.5 + limpers * 0.5) * bb * profile.iso_size_mult
            action = "raise"
            reason = f"Iso raise vs {limpers} limp"
        elif can_check:
            action = "check"
            reason = "Check behind"
        else:
            action = "fold" if can_fold else "check"
            reason = "No iso range"

    elif spot == "facing_raise":
        defend_range = {
            HandCategory.PREMIUM,
            HandCategory.STRONG,
            HandCategory.MEDIUM,
        }
        threebet_range = {HandCategory.PREMIUM}
        if position in {"co", "btn"}:
            threebet_range.add(HandCategory.STRONG)

        if villain_type in {PlayerType.STATION, PlayerType.FISH}:
            if category == HandCategory.MEDIUM and can_call:
                action = "call"
                reason = "Call vs station"
            elif category in threebet_range and can_raise:
                action = "raise"
                sizing = to_call * 3.0 * profile.raise_size_mult
                reason = "3bet value vs station"
            else:
                action = "fold" if can_fold else "check"
                reason = f"Fold {category.value} vs station"

        elif category in threebet_range and can_raise:
            mult = 3.0 if position in {"co", "btn"} else 3.5
            action = "raise"
            sizing = to_call * mult * profile.raise_size_mult
            reason = "3bet value"

        elif category in defend_range and can_call:
            if to_call_bb <= eff_stack_bb * 0.10:
                action = "call"
                reason = f"Call vs raise con {category.value}"
            else:
                action = "fold" if can_fold else "check"
                reason = "Too expensive"
        else:
            action = "fold" if can_fold else "check"
            reason = f"Fold {category.value} vs raise"

    else:  # facing_3bet
        if category == HandCategory.PREMIUM:
            if can_raise and eff_stack_bb >= 40:
                action = "raise"
                sizing = to_call * 2.2 * profile.raise_size_mult
                reason = "4bet value"
            elif can_call:
                action = "call"
                reason = "Call premium vs 3bet"
            else:
                action = "fold" if can_fold else "check"
                reason = "No continue action"
        elif category == HandCategory.STRONG and to_call_bb <= eff_stack_bb * 0.15 and can_call:
            action = "call"
            reason = "Call strong vs 3bet"
        else:
            action = "fold" if can_fold else "check"
            reason = "Fold vs 3bet"

    if action == "fold" and can_check:
        action = "check"
    if action == "raise" and not can_raise and can_call:
        action = "call"
        sizing = None

    selected_amount_label = None
    if action in {"raise", "bet"} and sizing is not None:
        btn = _select_amount_button(
            [{"label": l} for l in table_state.get("amount_button_labels", [])],
            sizing,
            table_state,
        )
        selected_amount_label = btn.get("label") if btn else None

    confidence = 0.9 if category == HandCategory.PREMIUM else 0.7

    return {
        "action": action,
        "confidence": round(confidence, 3),
        "reason": reason,
        "debug": {
            "category": category.value,
            "spot": spot,
            "eff_stack_bb": round(eff_stack_bb, 2),
            "to_call_bb": round(to_call_bb, 2),
            "sizing": round(sizing, 2) if sizing is not None else None,
            "selected_amount_label": selected_amount_label,
        },
    }


# =============================================================================
# POSTFLOP
# =============================================================================

def decide_postflop_action(
    table_state: Dict[str, Any],
    advisor_profile: Optional[AdvisorProfileConfig] = None,
) -> Dict[str, Any]:
    profile = advisor_profile or get_advisor_profile()

    street = _normalize_text(table_state.get("street", "flop"))
    hero_cards = table_state.get("hero_cards", [])
    board = table_state.get("board", [])

    analysis = _analyze_postflop_hand(hero_cards, board)
    bucket = analysis["bucket"]

    bb = max(_safe_float(table_state.get("big_blind", 1.0)), 1e-9)
    pot = _safe_float(table_state.get("pot_size", 0.0))
    to_call = _safe_float(table_state.get("to_call", 0.0))
    hero_stack = _safe_float(table_state.get("hero_stack", 0.0))
    villain_type = _parse_player_type(table_state.get("villain_type", "unknown"))

    equity = _clamp(_safe_float(table_state.get("monte_carlo_equity", 0.0)), 0.0, 1.0)
    if equity <= 0:
        equity_est = {
            "monster": 0.95,
            "strong": 0.75,
            "medium": 0.55,
            "weak_pair": 0.35,
            "air": 0.15,
        }.get(bucket, 0.3)

        if analysis["combo_draw"]:
            equity = max(equity_est, 0.6)
        elif analysis["flush_draw"] or analysis["straight_draw"]:
            equity = max(equity_est, 0.4)
        else:
            equity = equity_est

    available = table_state.get("available_actions", [])
    can_raise = any(_action_kind_from_label(a.get("label", "")) in {"raise", "bet"} for a in available)
    can_call = any(_action_kind_from_label(a.get("label", "")) == "call" for a in available)
    can_check = any(_action_kind_from_label(a.get("label", "")) == "check" for a in available)
    can_fold = any(_action_kind_from_label(a.get("label", "")) == "fold" for a in available)

    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
    spr = hero_stack / pot if pot > 0 else float("inf")

    action = "check"
    sizing = None
    reason = ""

    if to_call > 0:
        if bucket == "monster":
            if can_raise:
                action = "raise"
                sizing = pot * 0.75 * profile.raise_size_mult
                reason = "Raise value monster"
            elif can_call:
                action = "call"
                reason = "Call monster"
            else:
                action = "fold" if can_fold else "check"
                reason = "No continue action"

        elif bucket == "strong":
            margin = 0.05
            if villain_type in {PlayerType.LAG, PlayerType.MANIAC}:
                margin = 0.02
            elif villain_type in {PlayerType.NIT, PlayerType.TAG}:
                margin = 0.07

            if equity > pot_odds + margin:
                if can_raise and equity > 0.75 and villain_type not in {PlayerType.NIT}:
                    action = "raise"
                    sizing = pot * 0.6 * profile.raise_size_mult
                    reason = "Raise strong hand"
                elif can_call:
                    action = "call"
                    reason = "Call strong"
                else:
                    action = "fold" if can_fold else "check"
                    reason = "No call available"
            else:
                action = "fold" if can_fold else "check"
                reason = "No odds strong"

        elif bucket == "medium":
            margin = 0.02
            if villain_type in {PlayerType.LAG, PlayerType.MANIAC}:
                margin = 0.0
            elif villain_type in {PlayerType.NIT}:
                margin = 0.05

            if equity > pot_odds + margin and can_call:
                action = "call"
                reason = "Call medium"
            else:
                action = "fold" if can_fold else "check"
                reason = "Fold medium"

        else:
            if analysis["combo_draw"] and can_raise and villain_type not in {PlayerType.STATION, PlayerType.FISH}:
                action = "raise"
                sizing = pot * 0.6 * profile.raise_size_mult
                reason = "Semi-bluff combo draw"
            elif (analysis["flush_draw"] or analysis["straight_draw"]) and can_call and equity > pot_odds:
                action = "call"
                reason = "Call draw"
            else:
                action = "fold" if can_fold else "check"
                reason = "Fold weak/air"

    else:
        if bucket == "monster":
            if can_raise:
                action = "bet"
                sizing = pot * (0.66 if street == "flop" else 0.75) * profile.postflop_bet_size_mult
                reason = "Bet monster"
            else:
                action = "check"
                reason = "Check"

        elif bucket == "strong":
            if can_raise:
                action = "bet"
                sizing = pot * 0.5 * profile.postflop_bet_size_mult
                reason = "Bet value"
            else:
                action = "check"
                reason = "Check strong"

        elif bucket == "medium":
            if can_check:
                action = "check"
                reason = "Check medium"
            elif can_raise:
                action = "bet"
                sizing = pot * 0.33 * profile.postflop_bet_size_mult
                reason = "Bet thin medium"

        else:
            if analysis["combo_draw"] and can_raise and villain_type not in {PlayerType.STATION, PlayerType.FISH}:
                action = "bet"
                sizing = pot * 0.5 * profile.postflop_bet_size_mult
                reason = "Bet draw"
            else:
                action = "check"
                reason = "Check weak"

    if action == "fold" and can_check:
        action = "check"
    if action in {"raise", "bet"} and not can_raise and can_call and to_call > 0:
        action = "call"
        sizing = None

    selected_amount_label = None
    if action in {"raise", "bet"} and sizing is not None:
        btn = _select_amount_button(
            [{"label": l} for l in table_state.get("amount_button_labels", [])],
            sizing,
            table_state,
        )
        selected_amount_label = btn.get("label") if btn else None

    confidence = min(0.95, 0.5 + equity)

    return {
        "action": action,
        "confidence": round(confidence, 3),
        "reason": f"{street}: {reason} | bucket={bucket} equity={equity:.2f}",
        "debug": {
            "street": street,
            "bucket": bucket,
            "equity": round(equity, 3),
            "pot_odds": round(pot_odds, 3),
            "spr": round(spr, 2),
            "sizing": round(sizing, 2) if sizing is not None else None,
            "selected_amount_label": selected_amount_label,
        },
    }


def decide_action(
    table_state: Dict[str, Any],
    advisor_profile: Optional[AdvisorProfileConfig] = None,
) -> Dict[str, Any]:
    street = _normalize_text(table_state.get("street", "preflop"))
    if street == "preflop":
        return decide_preflop_action(table_state, advisor_profile)
    return decide_postflop_action(table_state, advisor_profile)


# =============================================================================
# COMPATIBILITÀ
# =============================================================================

def build_table_state(
    table: Any,
    hero_equity: Optional[float] = None,
    hero_position: Optional[str] = None,
    big_blind: Optional[float] = None,
    villain: Any = None,
    seat_to_position: Any = None,
    active_seats: Any = None,
) -> Dict[str, Any]:
    try:
        hero = table.get_player(table.hero_seat)

        active_players = []
        for p in getattr(table, "players", []):
            if getattr(p, "in_hand", False):
                if active_seats is None or p.seat in active_seats or p.seat == table.hero_seat:
                    active_players.append(p)

        villain_obj = villain
        if villain_obj is None:
            for p in active_players:
                if p.seat == table.hero_seat:
                    continue
                if villain_obj is None or getattr(p, "current_bet", 0) > getattr(villain_obj, "current_bet", 0):
                    villain_obj = p

        highest_bet = max([_safe_float(getattr(p, "current_bet", 0.0)) for p in active_players] or [0.0])
        hero_bet = _safe_float(getattr(hero, "current_bet", 0.0))
        to_call = max(0.0, highest_bet - hero_bet)

        available_actions = list(getattr(table, "available_actions", []))
        amount_buttons = list(getattr(table, "avaible_button", []))

        return {
            "street": getattr(table, "street", "preflop"),
            "hero_cards": list(getattr(table, "hero_cards", [])),
            "board": list(getattr(table, "board_cards", [])),
            "hero_position": hero_position or "",
            "hero_stack": _safe_float(getattr(hero, "stack", 0.0)),
            "hero_bet": hero_bet,
            "pot_size": _safe_float(getattr(table, "pot", 0.0)),
            "to_call": to_call,
            "min_raise": _safe_float(getattr(table, "min_raise", 0.0)) or _safe_float(big_blind, 1.0) * 2,
            "big_blind": _safe_float(big_blind, 1.0) or 1.0,
            "players_in_hand": len(active_players),
            "num_limppers": max(len(active_players) - 2, 0) if to_call <= (_safe_float(big_blind, 1.0) or 1.0) else 0,
            "available_actions": available_actions,
            "amount_button_labels": [b.get("label", "") for b in amount_buttons],
            "monte_carlo_equity": _safe_float(hero_equity, 0.0),
            "villain_stack": _safe_float(getattr(villain_obj, "stack", 0.0)) if villain_obj else 0.0,
            "villain_bet": _safe_float(getattr(villain_obj, "current_bet", 0.0)) if villain_obj else 0.0,
            "villain_type": getattr(villain_obj, "classify_player", lambda: "unknown")() if villain_obj else "unknown",
        }
    except Exception:
        return {
            "street": "preflop",
            "hero_cards": [],
            "board": [],
            "hero_position": hero_position or "",
            "hero_stack": 100.0,
            "hero_bet": 0.0,
            "pot_size": 1.5,
            "to_call": 0.0,
            "min_raise": _safe_float(big_blind, 1.0) * 2 if big_blind else 2.0,
            "big_blind": _safe_float(big_blind, 1.0) or 1.0,
            "players_in_hand": 2,
            "num_limppers": 0,
            "available_actions": [],
            "amount_button_labels": [],
            "monte_carlo_equity": 0.0,
            "villain_stack": 0.0,
            "villain_bet": 0.0,
            "villain_type": "unknown",
        }


def choose_action_with_rules(
    table: Any,
    hero_equity: Optional[float] = None,
    hero_position: Optional[str] = None,
    big_blind: Optional[float] = None,
    seat_to_position: Any = None,
    active_seats: Any = None,
    advisor_profile: Optional[AdvisorProfileConfig] = None,
    profile_name: Optional[str] = None,
    game_type: str = "cash",
    play_style: str = "mixed",
) -> Dict[str, Any]:
    if not hasattr(table, "available_actions") or not table.available_actions:
        return {
            "selected_action": None,
            "selected_amount_button": None,
            "reason": "Nessuna azione disponibile.",
            "debug": {},
            "table_state": {},
            "advisor_profile": None,
        }

    table_state = build_table_state(
        table=table,
        hero_equity=hero_equity,
        hero_position=hero_position,
        big_blind=big_blind,
        villain=None,
        seat_to_position=seat_to_position,
        active_seats=active_seats,
    )

    profile = advisor_profile or get_advisor_profile(profile_name, game_type, play_style)
    decision = decide_action(table_state, profile)

    selected = _find_action(table.available_actions, decision["action"])

    if selected is None:
        for fallback in ["call", "check", "fold", "bet", "raise"]:
            if fallback == decision["action"]:
                continue
            selected = _find_action(table.available_actions, fallback)
            if selected:
                decision["reason"] += f" (fallback: {fallback})"
                break

    amount_btn = None
    if decision["action"] in {"raise", "bet"} and selected:
        target = decision.get("debug", {}).get("sizing")
        if target is not None:
            amount_btn = _select_amount_button(
                getattr(table, "avaible_button", []),
                target,
                table_state,
            )

    return {
        "selected_action": selected,
        "selected_amount_button": amount_btn,
        "reason": decision["reason"],
        "debug": decision.get("debug", {}),
        "table_state": table_state,
        "advisor_profile": profile.name,
    }
