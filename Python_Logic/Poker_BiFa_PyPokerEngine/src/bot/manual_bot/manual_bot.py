from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bot.BotAction import BotAction
from player_stats import PlayerStatsTracker


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_cards(cards) -> str:
    return " ".join(str(card) for card in cards) or "-"


@dataclass
class ManualBotConfig:
    name: str = "Manual Bot"
    show_opponent_stats: bool = True


class ManualBot:
    ManualBotConfig = ManualBotConfig
    BotAction = BotAction

    def __init__(self, config: Optional[ManualBotConfig] = None):
        self.config = config or ManualBotConfig()
        self.name = self.config.name
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

    def _print_state_summary(self, state, player_index: int, stats_context: Optional[Dict[str, Any]]) -> None:
        call_amount = _safe_int(getattr(state, "checking_or_calling_amount", 0), 0)
        min_raise = getattr(state, "min_completion_betting_or_raising_to_amount", None)
        max_raise = getattr(state, "max_completion_betting_or_raising_to_amount", None)
        stack = _safe_int(state.stacks[player_index], 0)
        street = (stats_context or {}).get("street", "preflop")
        position = (stats_context or {}).get("position", "")
        pot = (stats_context or {}).get("pot", getattr(state, "total_pot_amount", 0))

        print("\n" + "=" * 72)
        print(f"{self.name} to act")
        print(f"Street   : {street}")
        print(f"Position : {position or '-'}")
        print(f"Hole     : {_format_cards(state.hole_cards[player_index])}")
        print(f"Board    : {_format_cards(state.board_cards)}")
        print(f"Pot      : {pot}")
        print(f"Stack    : {stack}")
        print(f"Call     : {call_amount}")
        print(f"Min raise: {min_raise}")
        print(f"Max raise: {max_raise}")

        opponents = list((stats_context or {}).get("opponents", []))
        if opponents and self.config.show_opponent_stats:
            print("Opponents:")
            for opp in opponents:
                print(
                    "  - "
                    f"seat={opp.get('seat', '-')} "
                    f"pos={opp.get('position', '-')} "
                    f"vpip={opp.get('vpip', 0):.2f} "
                    f"pfr={opp.get('pfr', 0):.2f} "
                    f"af={opp.get('af', 0):.2f} "
                    f"stack_bb={opp.get('stack_bb', 0):.2f}"
                )

        print("Comandi: fold | check | call | raise <amount> | info | stats")
        print("=" * 72)

    def _print_extra_info(self, stats_context: Optional[Dict[str, Any]]) -> None:
        if not stats_context:
            print("Nessun contesto statistico disponibile.")
            return

        print("Context:")
        for key in (
            "street",
            "position",
            "players_in_hand",
            "call_amount",
            "raise_count_before_action",
            "big_blind",
            "hero_stack_bb",
            "effective_stack_bb",
            "is_cbet_opportunity",
            "is_facing_cbet",
        ):
            if key in stats_context:
                print(f"  {key}: {stats_context[key]}")

    def _print_hero_stats(self) -> None:
        stats = self.get_stats_snapshot()
        print("Hero stats:")
        print(
            "  "
            f"hands={stats['hands_played']} "
            f"vpip={stats['vpip']:.2f} "
            f"pfr={stats['pfr']:.2f} "
            f"af={stats['af']:.2f} "
            f"3bet={stats['3bet']:.2f} "
            f"wtsd={stats['wtsd']:.2f} "
            f"conf={stats['confidence']:.2f}"
        )

    def _normalize_manual_action(self, raw_action: str, state, player_index: int) -> Optional[BotAction]:
        stack = _safe_int(state.stacks[player_index], 0)
        call_amount = _safe_int(getattr(state, "checking_or_calling_amount", 0), 0)
        min_raise = getattr(state, "min_completion_betting_or_raising_to_amount", None)
        max_raise = getattr(state, "max_completion_betting_or_raising_to_amount", None)

        command = raw_action.strip().lower()
        if not command:
            return None

        if command in {"fold", "f"}:
            return BotAction("fold")

        if command in {"check", "k"}:
            if call_amount == 0:
                return BotAction("call", 0)
            print("Non puoi fare check: c'e' da chiamare.")
            return None

        if command in {"call", "c"}:
            return BotAction("call", call_amount)

        if command.startswith("raise") or command.startswith("r "):
            parts = command.split()
            if len(parts) < 2:
                print("Formato raise non valido. Usa: raise <amount>")
                return None

            amount = _safe_int(parts[1], -1)
            if amount <= 0:
                print("Importo raise non valido.")
                return None
            if min_raise is None or max_raise is None:
                print("Raise non disponibile in questo stato.")
                return None

            min_raise = _safe_int(min_raise, 0)
            max_raise = _safe_int(max_raise, 0)
            if amount < min_raise or amount > max_raise:
                print(f"Raise fuori range: deve essere tra {min_raise} e {max_raise}.")
                return None
            if amount > stack:
                print(f"Raise oltre lo stack disponibile ({stack}).")
                return None
            return BotAction("raise", amount)

        return None

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

    def act(self, state, player_index: int, stats_context: Optional[Dict[str, Any]] = None) -> BotAction:
        if _safe_int(state.stacks[player_index], 0) <= 0:
            action = BotAction("fold")
            self._record_stats_decision(action, stats_context)
            return action

        while True:
            self._print_state_summary(state, player_index, stats_context)
            raw = input(f"{self.name}> ").strip()

            if raw.lower() in {"info", "i", "help", "h"}:
                self._print_extra_info(stats_context)
                continue

            if raw.lower() in {"stats", "s"}:
                self._print_hero_stats()
                continue

            action = self._normalize_manual_action(raw, state, player_index)
            if action is None:
                print("Comando non riconosciuto.")
                continue

            self._record_stats_decision(action, stats_context)
            return action


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
