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
class sng_BotConfig:
    name: str = "smart"
    aggression: float = 0.55       # 0..1
    looseness: float = 0.50        # 0..1
    preflop_raise_threshold: float = 0.72
    preflop_call_threshold: float = 0.44
    postflop_raise_threshold: float = 0.78
    postflop_call_threshold: float = 0.48
    cheap_call_bonus: float = 0.12
    draw_bonus: float = 0.10
    top_pair_bonus: float = 0.12

def parse_card(card) -> Tuple[str, str]:
    text = str(card).strip()

    # 1️⃣ formato con parentesi tonde: "KING OF SPADES (Ks)"
    m = re.search(r"\(([2-9TJQKA]|10)([cdhs])\)", text, re.IGNORECASE)
    if m:
        rank = m.group(1).upper()
        suit = m.group(2).lower()
        return rank, suit

    # 2️⃣ formato con quadre: "[Qd]"
    m = re.search(r"\[([2-9TJQKA]|10)([cdhs])\]", text, re.IGNORECASE)
    if m:
        rank = m.group(1).upper()
        suit = m.group(2).lower()
        return rank, suit

    # 3️⃣ formato semplice: "Qd"
    m = re.search(r"^([2-9TJQKA]|10)([cdhs])$", text, re.IGNORECASE)
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


def preflop_strength(cards) -> float:
    """
    Forza mano iniziale 0..1 circa.
    """
    r1 = card_rank_index(cards[0])
    r2 = card_rank_index(cards[1])

    hi = max(r1, r2)
    lo = min(r1, r2)
    gap = abs(r1 - r2)

    suited = card_suit(cards[0]) == card_suit(cards[1])
    pair = r1 == r2

    score = 0.0

    if pair:
        score += 0.58 + hi * 0.03

    score += hi * 0.035 + lo * 0.018

    if suited:
        score += 0.07

    if gap == 1:
        score += 0.06
    elif gap == 2:
        score += 0.03

    if hi >= rank_to_index("T"):
        score += 0.08
    if lo >= rank_to_index("T"):
        score += 0.03

    return max(0.0, min(1.0, score))


def _all_rank_indices(cards) -> List[int]:
    return [card_rank_index(c) for c in cards]


def _all_suits(cards) -> List[str]:
    return [card_suit(c) for c in cards]


def has_flush_draw(all_cards) -> bool:
    suits = Counter(_all_suits(all_cards))
    return any(v == 4 for v in suits.values())


def has_flush(all_cards) -> bool:
    suits = Counter(_all_suits(all_cards))
    return any(v >= 5 for v in suits.values())


def has_straight(rank_values: List[int]) -> bool:
    vals = sorted(set(rank_values))
    # wheel
    if set([12, 0, 1, 2, 3]).issubset(set(vals)):
        return True
    for i in range(len(vals) - 4):
        if vals[i+4] - vals[i] == 4:
            return True
    return False


def has_straight_draw(rank_values: List[int]) -> bool:
    vals = sorted(set(rank_values))
    # ruota con Asso basso
    if 12 in vals:
        vals = sorted(set(vals + [-1]))

    for i in range(len(vals)):
        window = vals[i:i+4]
        if len(window) < 4:
            break
        if max(window) - min(window) <= 4:
            return True
    return False


def classify_postflop(hole_cards, board_cards):
    """
    Ritorna un dict con info semplici ma utili.
    """
    all_cards = list(hole_cards) + list(board_cards)
    hole_ranks = _all_rank_indices(hole_cards)
    board_ranks = _all_rank_indices(board_cards)
    all_ranks = _all_rank_indices(all_cards)

    rank_counter = Counter(all_ranks)
    counts = sorted(rank_counter.values(), reverse=True)

    board_high = max(board_ranks) if board_ranks else -1
    hole_high = max(hole_ranks) if hole_ranks else -1

    pair = counts[0] >= 2 if counts else False
    two_pair = counts[:2] == [2, 2] if len(counts) >= 2 else False
    trips = counts[0] >= 3 if counts else False
    full_house = counts[:2] == [3, 2] if len(counts) >= 2 else False
    quads = counts[0] >= 4 if counts else False

    flush = has_flush(all_cards)
    flush_draw = has_flush_draw(all_cards)

    straight = has_straight(all_ranks)
    straight_draw = has_straight_draw(all_ranks)

    # top pair semplice
    top_pair = False
    if board_cards:
        board_top = max(board_ranks)
        hole_set = set(hole_ranks)
        if board_top in hole_set and pair:
            top_pair = True

    overcards = 0
    if board_cards:
        overcards = sum(1 for r in hole_ranks if r > board_high)

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
        "overcards": overcards,
    }


def postflop_strength(hole_cards, board_cards, cfg: sng_BotConfig) -> float:
    info = classify_postflop(hole_cards, board_cards)

    score = 0.0

    if info["pair"]:
        score += 0.35
    if info["top_pair"]:
        score += cfg.top_pair_bonus
    if info["two_pair"]:
        score += 0.22
    if info["trips"]:
        score += 0.30
    if info["straight"]:
        score += 0.34
    if info["flush"]:
        score += 0.34
    if info["full_house"]:
        score += 0.50
    if info["quads"]:
        score += 0.70

    if info["flush_draw"]:
        score += cfg.draw_bonus
    if info["straight_draw"]:
        score += cfg.draw_bonus * 0.9

    # 2 overcards sul flop/turn: piccolo bonus
    if info["overcards"] == 2:
        score += 0.06
    elif info["overcards"] == 1:
        score += 0.03

    return max(0.0, min(1.0, score))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _avg_stat(opponents: List[Dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = [float(opp.get(key, default)) for opp in opponents if opp.get(key) is not None]
    if not values:
        return default
    return sum(values) / len(values)


class SmartParametricBot:
    sng_BotConfig = sng_BotConfig
    BotAction = BotAction

    def __init__(self, config: sng_BotConfig):
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

    def _raise_amount(self, state, stack: int) -> Optional[int]:
        min_raise = state.min_completion_betting_or_raising_to_amount
        max_raise = state.max_completion_betting_or_raising_to_amount

        if min_raise is None or max_raise is None:
            return None

        amount = min_raise + int((max_raise - min_raise) * self.config.aggression * 0.45)
        amount = min(amount, stack)
        if amount <= 0:
            return None
        return amount

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
        avg_stack_bb = _avg_stat(opponents, "stack_bb", 30.0)
        position = stats_context.get("position", "")
        players_in_hand = int(stats_context.get("players_in_hand", len(opponents) + 1))

        if position in {"BTN", "CO"} and players_in_hand <= 4:
            strength += 0.03
        elif position in {"SB", "UTG"} and players_in_hand >= 5:
            strength -= 0.02

        if avg_vpip < 0.22:
            strength += 0.03
        elif avg_vpip > 0.38:
            strength -= 0.03

        if avg_pfr > 0.24:
            strength -= 0.03

        if avg_af > 2.2 and call_ratio > 0.08:
            strength -= 0.04

        if avg_stack_bb < 18:
            strength += 0.02

        return _clamp(strength, 0.0, 1.0)

    def _adapt_postflop_strength(
        self,
        strength: float,
        stats_context: Optional[Dict[str, Any]],
        call_ratio: float,
        board_cards,
    ) -> float:
        if not stats_context:
            return strength

        opponents = stats_context.get("opponents", [])
        avg_fold_to_cbet = _avg_stat(opponents, "fold_to_cbet", 0.35)
        avg_wtsd = _avg_stat(opponents, "wtsd", 0.30)
        avg_af = _avg_stat(opponents, "af", 1.5)
        avg_vpip = _avg_stat(opponents, "vpip", 0.28)
        players_in_hand = int(stats_context.get("players_in_hand", len(opponents) + 1))
        is_cbet_opportunity = bool(stats_context.get("is_cbet_opportunity", False))
        is_facing_cbet = bool(stats_context.get("is_facing_cbet", False))

        if is_cbet_opportunity and len(board_cards) == 3:
            if avg_fold_to_cbet > 0.48:
                strength += 0.05
            elif avg_fold_to_cbet < 0.28:
                strength -= 0.05

        if players_in_hand > 2:
            strength -= 0.03

        if avg_wtsd > 0.36 or avg_vpip > 0.40:
            strength -= 0.04

        if is_facing_cbet and avg_af > 2.3 and call_ratio > 0.10:
            strength -= 0.05

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

        if avg_fold_to_raise > 0.45:
            raise_threshold -= 0.03
        if avg_three_bet > 0.16:
            raise_threshold += 0.03
            call_threshold += 0.02

        return _clamp(raise_threshold, 0.45, 0.92), _clamp(call_threshold, 0.25, 0.75)

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

        if avg_fold_to_cbet > 0.48:
            raise_threshold -= 0.04
        if avg_wtsd > 0.38:
            raise_threshold += 0.03
            call_threshold += 0.01

        return _clamp(raise_threshold, 0.50, 0.92), _clamp(call_threshold, 0.25, 0.80)

    def act(self, state, player_index: int, stats_context: Optional[Dict[str, Any]] = None) -> BotAction:
        hole_cards = state.hole_cards[player_index]
        board_cards = state.board_cards

        stack = state.stacks[player_index]
        call_amount = state.checking_or_calling_amount

        if stack <= 0:
            return BotAction("fold")

        call_ratio = call_amount / max(stack, 1)
        is_preflop = len(board_cards) == 0

        if is_preflop:
            strength = preflop_strength(hole_cards)
            strength += (self.config.looseness - 0.5) * 0.35
            if call_ratio < 0.05:
                strength += self.config.cheap_call_bonus

            strength = self._adapt_preflop_strength(strength, stats_context, call_ratio)
            preflop_raise_threshold, preflop_call_threshold = self._preflop_thresholds(stats_context)

            if strength >= preflop_raise_threshold:
                amount = self._raise_amount(state, stack)
                if amount is not None:
                    action = BotAction("raise", amount)
                    self._record_stats_decision(action, stats_context)
                    return action

            if strength >= preflop_call_threshold:
                action = BotAction("call", call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            if call_ratio < 0.025:
                action = BotAction("call", call_amount)
                self._record_stats_decision(action, stats_context)
                return action

            action = BotAction("fold")
            self._record_stats_decision(action, stats_context)
            return action

        strength = postflop_strength(hole_cards, board_cards, self.config)
        strength += (self.config.looseness - 0.5) * 0.12

        if call_ratio < 0.04:
            strength += self.config.cheap_call_bonus * 0.5

        strength = self._adapt_postflop_strength(
            strength,
            stats_context,
            call_ratio,
            board_cards,
        )
        postflop_raise_threshold, postflop_call_threshold = self._postflop_thresholds(stats_context)

        if strength >= postflop_raise_threshold:
            amount = self._raise_amount(state, stack)
            if amount is not None:
                action = BotAction("raise", amount)
                self._record_stats_decision(action, stats_context)
                return action

        if strength >= postflop_call_threshold:
            action = BotAction("call", call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        # draw cheap / bluff catcher semplice
        if call_ratio <= 0.08 and strength >= max(0.28, postflop_call_threshold - 0.18):
            action = BotAction("call", call_amount)
            self._record_stats_decision(action, stats_context)
            return action

        # se posso checkare, checko
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
    }
