from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple

from bot.BotAction import BotAction
from player_stats import PlayerStatsTracker


RANK_ORDER = "23456789TJQKA"
RANK_MAP = {
    "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9",
    "10": "T", "T": "T",
    "J": "J", "Q": "Q", "K": "K", "A": "A",
}


class HandCategory(Enum):
    PREMIUM = "premium"
    STRONG = "strong"
    MEDIUM = "medium"
    SPECULATIVE = "speculative"
    WEAK = "weak"
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
class RuleBasedBotConfig:
    name: str = "rule_based"
    game_type: str = "tournament"
    play_style: str = "mixed"
    open_size_mult: float = 1.0
    iso_size_mult: float = 1.0
    raise_size_mult: float = 1.0
    postflop_bet_size_mult: float = 1.0


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


def parse_card(card) -> Tuple[str, str]:
    text = str(card).strip()
    patterns = [
        r"\(([2-9TJQKA]|10)([cdhs])\)",
        r"\[([2-9TJQKA]|10)([cdhs])\]",
        r"^([2-9TJQKA]|10)([cdhs])$",
        r"([2-9TJQKA]|10)([cdhs])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper(), match.group(2).lower()
    raise ValueError(f"Formato carta non riconosciuto: {text!r}")


def rank_to_index(rank: str) -> int:
    return RANK_ORDER.index(RANK_MAP.get(rank, "2"))


def card_rank_index(card) -> int:
    rank, _ = parse_card(card)
    return rank_to_index(rank)


def card_suit(card) -> str:
    _, suit = parse_card(card)
    return suit


def _all_rank_indices(cards) -> List[int]:
    return [card_rank_index(card) for card in cards]


def _all_suits(cards) -> List[str]:
    return [card_suit(card) for card in cards]


def has_flush_draw(all_cards) -> bool:
    suit_counts: Dict[str, int] = {}
    for suit in _all_suits(all_cards):
        suit_counts[suit] = suit_counts.get(suit, 0) + 1
    return any(count == 4 for count in suit_counts.values())


def has_flush(all_cards) -> bool:
    suit_counts: Dict[str, int] = {}
    for suit in _all_suits(all_cards):
        suit_counts[suit] = suit_counts.get(suit, 0) + 1
    return any(count >= 5 for count in suit_counts.values())


def has_straight(rank_values: List[int]) -> bool:
    values = sorted(set(rank_values))
    if {12, 0, 1, 2, 3}.issubset(set(values)):
        return True
    for index in range(len(values) - 4):
        if values[index + 4] - values[index] == 4:
            return True
    return False


def has_straight_draw(rank_values: List[int]) -> bool:
    values = sorted(set(rank_values))
    if 12 in values:
        values = sorted(set(values + [-1]))
    for index in range(len(values)):
        window = values[index:index + 4]
        if len(window) < 4:
            break
        if max(window) - min(window) <= 4:
            return True
    return False


def _normalize_hole(cards) -> Tuple[int, int, bool]:
    rank_1 = card_rank_index(cards[0])
    rank_2 = card_rank_index(cards[1])
    suited = card_suit(cards[0]) == card_suit(cards[1])
    return max(rank_1, rank_2), min(rank_1, rank_2), suited


def _hand_to_category(hero_cards) -> HandCategory:
    if len(hero_cards) != 2:
        return HandCategory.TRASH

    hi, lo, suited = _normalize_hole(hero_cards)

    if hi == lo:
        if hi >= rank_to_index("Q"):
            return HandCategory.PREMIUM
        if hi >= rank_to_index("T"):
            return HandCategory.STRONG
        if hi >= rank_to_index("7"):
            return HandCategory.MEDIUM
        return HandCategory.SPECULATIVE

    if hi == rank_to_index("A") and lo == rank_to_index("K"):
        return HandCategory.PREMIUM
    if suited and hi == rank_to_index("A") and lo in {rank_to_index("Q"), rank_to_index("J")}:
        return HandCategory.STRONG
    if suited and hi == rank_to_index("K") and lo == rank_to_index("Q"):
        return HandCategory.STRONG
    if hi == rank_to_index("A") and lo == rank_to_index("Q") and not suited:
        return HandCategory.MEDIUM
    if suited and hi == rank_to_index("A") and lo <= rank_to_index("9"):
        return HandCategory.SPECULATIVE
    if suited and hi - lo <= 1 and lo >= rank_to_index("5"):
        return HandCategory.SPECULATIVE
    if suited and hi >= rank_to_index("J") and lo >= rank_to_index("T"):
        return HandCategory.MEDIUM
    if not suited and hi == rank_to_index("A") and lo in {rank_to_index("J"), rank_to_index("T")}:
        return HandCategory.WEAK
    if not suited and hi >= rank_to_index("Q") and lo >= rank_to_index("T"):
        return HandCategory.WEAK
    if hi <= rank_to_index("8") and lo <= rank_to_index("5"):
        return HandCategory.TRASH
    return HandCategory.WEAK


def classify_postflop(hole_cards, board_cards) -> Dict[str, Any]:
    all_cards = list(hole_cards) + list(board_cards)
    hole_ranks = _all_rank_indices(hole_cards)
    board_ranks = _all_rank_indices(board_cards)
    all_ranks = _all_rank_indices(all_cards)

    rank_counts: Dict[int, int] = {}
    for rank in all_ranks:
        rank_counts[rank] = rank_counts.get(rank, 0) + 1
    counts = sorted(rank_counts.values(), reverse=True)

    pair = counts[0] >= 2 if counts else False
    two_pair = counts[:2] == [2, 2] if len(counts) >= 2 else False
    trips = counts[0] >= 3 if counts else False
    full_house = counts[:2] == [3, 2] if len(counts) >= 2 else False
    quads = counts[0] >= 4 if counts else False
    flush = has_flush(all_cards)
    flush_draw = has_flush_draw(all_cards)
    straight = has_straight(all_ranks)
    straight_draw = has_straight_draw(all_ranks)

    top_pair = False
    if board_ranks:
        top_board = max(board_ranks)
        if top_board in hole_ranks and pair:
            top_pair = True

    overcards = 0
    if board_ranks:
        max_board = max(board_ranks)
        overcards = sum(1 for rank in hole_ranks if rank > max_board)

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
        "combo_draw": flush_draw and straight_draw,
        "top_pair": top_pair,
        "overcards": overcards,
    }


def _postflop_bucket(hole_cards, board_cards) -> str:
    info = classify_postflop(hole_cards, board_cards)
    if info["quads"] or info["full_house"]:
        return "monster"
    if info["flush"] or info["straight"] or info["trips"]:
        return "strong"
    if info["two_pair"]:
        return "strong"
    if info["pair"] and info["top_pair"]:
        return "medium"
    if info["pair"]:
        return "weak_pair"
    return "air"


def _classify_opponent_from_stats(opponents: List[Dict[str, Any]]) -> PlayerType:
    if not opponents:
        return PlayerType.UNKNOWN

    primary = max(opponents, key=lambda opp: _safe_float(opp.get("confidence", 0.0), 0.0))
    if _safe_float(primary.get("confidence", 0.0), 0.0) < 0.20:
        return PlayerType.UNKNOWN

    vpip = _safe_float(primary.get("vpip", 0.0), 0.0)
    pfr = _safe_float(primary.get("pfr", 0.0), 0.0)
    af = _safe_float(primary.get("af", 0.0), 0.0)

    if vpip >= 0.40 and af <= 1.4:
        return PlayerType.STATION
    if vpip >= 0.42 and pfr <= 0.16:
        return PlayerType.FISH
    if vpip <= 0.18 and pfr <= 0.14:
        return PlayerType.NIT
    if vpip >= 0.30 and (af >= 2.6 or pfr >= 0.24):
        return PlayerType.LAG
    if vpip >= 0.38 and af >= 3.0:
        return PlayerType.MANIAC
    if 0.16 <= vpip <= 0.28 and 0.14 <= pfr <= 0.24:
        return PlayerType.TAG
    return PlayerType.UNKNOWN


def _preflop_spot(call_amount: int, big_blind: int, raise_count_before_action: int, limper_count: int) -> str:
    if raise_count_before_action >= 2:
        return "facing_3bet"
    if raise_count_before_action == 1:
        return "facing_raise"
    if call_amount > big_blind or raise_count_before_action > 0:
        return "facing_raise"
    if limper_count > 0 and call_amount > 0:
        return "limped"
    return "unopened"


def _estimate_raise_to(
    state,
    target_amount: float,
) -> Optional[int]:
    min_raise_to = _safe_int(getattr(state, "min_completion_betting_or_raising_to_amount", 0), 0)
    max_raise_to = _safe_int(getattr(state, "max_completion_betting_or_raising_to_amount", 0), 0)
    if min_raise_to <= 0 or max_raise_to <= 0:
        return None
    return max(min_raise_to, min(int(round(target_amount)), max_raise_to))


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
    **extra: Any,
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
        **extra,
    }


class RuleBasedAdvisorBot:
    BotConfig = RuleBasedBotConfig
    BotAction = BotAction

    def __init__(self, config: Optional[RuleBasedBotConfig] = None):
        self.config = config or RuleBasedBotConfig()
        self.name = self.config.name
        self.stats_tracker = PlayerStatsTracker(self.name)

    def start_stats_hand(self, hand_id: int, position: str, stack_bb: float, players_in_hand: int) -> None:
        self.stats_tracker.start_hand(hand_id, position, stack_bb, players_in_hand)

    def note_stats_saw_flop(self) -> None:
        self.stats_tracker.note_saw_flop()

    def note_stats_showdown(self) -> None:
        self.stats_tracker.note_showdown()

    def get_stats_snapshot(self) -> Dict[str, float | str | int]:
        return self.stats_tracker.build_stats().to_dict()

    def _record_stats_decision(self, action: BotAction, stats_context: Optional[Dict[str, Any]]) -> None:
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

    def _decide_preflop(self, state, stats_context: Dict[str, Any]) -> BotAction:
        hole_cards = state.hole_cards[state.actor_index]
        category = _hand_to_category(hole_cards)
        big_blind = max(_safe_int(stats_context.get("big_blind", 2), 2), 1)
        call_amount = _safe_int(stats_context.get("call_amount", 0), 0)
        position = str(stats_context.get("position", "")).lower()
        effective_stack_bb = _safe_float(stats_context.get("effective_stack_bb", 0.0), 0.0)
        villain_type = _classify_opponent_from_stats(stats_context.get("opponents", []))
        limper_count = _safe_int(stats_context.get("limper_count", 0), 0)
        spot = _preflop_spot(
            call_amount=call_amount,
            big_blind=big_blind,
            raise_count_before_action=_safe_int(stats_context.get("raise_count_before_action", 0), 0),
            limper_count=limper_count,
        )

        if effective_stack_bb <= 20:
            push_range = {
                HandCategory.PREMIUM,
                HandCategory.STRONG,
                HandCategory.MEDIUM,
            }
            if effective_stack_bb <= 10:
                push_range.add(HandCategory.SPECULATIVE)

            if spot in {"unopened", "limped"} and category in push_range:
                amount = _estimate_raise_to(state, state.stacks[state.actor_index])
                return BotAction("raise", amount) if amount is not None else BotAction("call")

            if spot == "facing_raise" and category in {HandCategory.PREMIUM, HandCategory.STRONG}:
                amount = _estimate_raise_to(state, state.stacks[state.actor_index])
                return BotAction("raise", amount) if amount is not None else BotAction("call")

            return BotAction("fold")

        if spot == "unopened":
            open_ranges = {
                "utg": {HandCategory.PREMIUM, HandCategory.STRONG},
                "hj": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM},
                "co": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM, HandCategory.SPECULATIVE},
                "btn": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM, HandCategory.SPECULATIVE, HandCategory.WEAK},
                "sb": {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM},
                "bb": set(),
            }
            allowed = open_ranges.get(position, {HandCategory.PREMIUM, HandCategory.STRONG})
            if villain_type == PlayerType.STATION:
                allowed = {hand for hand in allowed if hand != HandCategory.SPECULATIVE}
            if category in allowed:
                open_size_bb = {
                    "utg": 2.5,
                    "hj": 2.4,
                    "co": 2.2,
                    "btn": 2.0,
                    "sb": 2.8,
                }.get(position, 2.4)
                amount = _estimate_raise_to(state, open_size_bb * big_blind * self.config.open_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")
            return BotAction("check" if call_amount == 0 else "fold")

        if spot == "limped":
            iso_range = {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM}
            if position in {"co", "btn", "sb"}:
                iso_range.add(HandCategory.SPECULATIVE)
            if villain_type in {PlayerType.STATION, PlayerType.FISH}:
                iso_range.discard(HandCategory.SPECULATIVE)
            if category in iso_range:
                limpers = max(limper_count, 1)
                amount = _estimate_raise_to(state, (3.5 + limpers * 0.5) * big_blind * self.config.iso_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")
            return BotAction("check" if call_amount == 0 else "fold")

        if spot == "facing_raise":
            defend_range = {HandCategory.PREMIUM, HandCategory.STRONG, HandCategory.MEDIUM}
            three_bet_range = {HandCategory.PREMIUM}
            if position in {"co", "btn"}:
                three_bet_range.add(HandCategory.STRONG)

            if villain_type in {PlayerType.STATION, PlayerType.FISH}:
                if category == HandCategory.MEDIUM and call_amount > 0:
                    return BotAction("call")
                if category in three_bet_range:
                    amount = _estimate_raise_to(state, call_amount * 3.0 * self.config.raise_size_mult)
                    return BotAction("raise", amount) if amount is not None else BotAction("call")
                return BotAction("fold")

            if category in three_bet_range:
                mult = 3.0 if position in {"co", "btn"} else 3.5
                amount = _estimate_raise_to(state, call_amount * mult * self.config.raise_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")

            if category in defend_range and call_amount <= (effective_stack_bb * big_blind * 0.10):
                return BotAction("call")
            return BotAction("fold")

        if category == HandCategory.PREMIUM:
            if effective_stack_bb >= 40:
                amount = _estimate_raise_to(state, call_amount * 2.2 * self.config.raise_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")
            return BotAction("call")

        if category == HandCategory.STRONG and call_amount <= (effective_stack_bb * big_blind * 0.15):
            return BotAction("call")

        return BotAction("fold")

    def _decide_postflop(self, state, stats_context: Dict[str, Any]) -> BotAction:
        actor_index = state.actor_index
        hole_cards = state.hole_cards[actor_index]
        board_cards = state.board_cards
        bucket = _postflop_bucket(hole_cards, board_cards)
        info = classify_postflop(hole_cards, board_cards)

        pot = _safe_float(stats_context.get("pot", getattr(state, "total_pot_amount", 0.0)), 0.0)
        call_amount = _safe_int(stats_context.get("call_amount", 0), 0)
        villain_type = _classify_opponent_from_stats(stats_context.get("opponents", []))

        equity = {
            "monster": 0.95,
            "strong": 0.75,
            "medium": 0.55,
            "weak_pair": 0.35,
            "air": 0.15,
        }.get(bucket, 0.30)
        if info["combo_draw"]:
            equity = max(equity, 0.60)
        elif info["flush_draw"] or info["straight_draw"]:
            equity = max(equity, 0.40)

        pot_odds = call_amount / (pot + call_amount) if call_amount > 0 else 0.0

        if call_amount > 0:
            if bucket == "monster":
                amount = _estimate_raise_to(state, pot * 0.75 * self.config.raise_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")

            if bucket == "strong":
                margin = 0.05
                if villain_type in {PlayerType.LAG, PlayerType.MANIAC}:
                    margin = 0.02
                elif villain_type == PlayerType.NIT:
                    margin = 0.07
                if equity > pot_odds + margin:
                    if equity > 0.75 and villain_type != PlayerType.NIT:
                        amount = _estimate_raise_to(state, pot * 0.60 * self.config.raise_size_mult)
                        return BotAction("raise", amount) if amount is not None else BotAction("call")
                    return BotAction("call")
                return BotAction("fold")

            if bucket == "medium":
                margin = 0.02
                if villain_type in {PlayerType.LAG, PlayerType.MANIAC}:
                    margin = 0.0
                elif villain_type == PlayerType.NIT:
                    margin = 0.05
                return BotAction("call" if equity > pot_odds + margin else "fold")

            if info["combo_draw"] and villain_type not in {PlayerType.STATION, PlayerType.FISH}:
                amount = _estimate_raise_to(state, pot * 0.60 * self.config.raise_size_mult)
                return BotAction("raise", amount) if amount is not None else BotAction("call")
            if (info["flush_draw"] or info["straight_draw"]) and equity > pot_odds:
                return BotAction("call")
            return BotAction("fold")

        if bucket == "monster":
            amount = _estimate_raise_to(state, pot * 0.66 * self.config.postflop_bet_size_mult)
            return BotAction("raise", amount) if amount is not None else BotAction("call")

        if bucket == "strong":
            amount = _estimate_raise_to(state, pot * 0.50 * self.config.postflop_bet_size_mult)
            return BotAction("raise", amount) if amount is not None else BotAction("check")

        if bucket == "medium":
            return BotAction("check")

        if info["combo_draw"] and villain_type not in {PlayerType.STATION, PlayerType.FISH}:
            amount = _estimate_raise_to(state, pot * 0.50 * self.config.postflop_bet_size_mult)
            return BotAction("raise", amount) if amount is not None else BotAction("check")

        return BotAction("check")

    def act(self, state, player_index: int, stats_context: Optional[Dict[str, Any]] = None) -> BotAction:
        if state.actor_index != player_index:
            player_index = state.actor_index

        context = stats_context or {}
        street = str(context.get("street", "preflop")).lower()
        if street == "preflop":
            action = self._decide_preflop(state, context)
        else:
            action = self._decide_postflop(state, context)

        self._record_stats_decision(action, context)
        return action
