from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
from typing import Any

from table_models import TableBase, names_are_similar


POKER_ENGINE_SRC = Path(__file__).resolve().parent / "Poker_BiFa_PyPokerEngine" / "src"
if str(POKER_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(POKER_ENGINE_SRC))

from bot.bot_biagio.bot_biagio import BotBiagio, build_stats_context as build_biagio_stats_context
from bot.negreanu_bot.negreanu_bot import BotNegreanu, build_stats_context as build_negreanu_stats_context
from bot.negreanu_bot_V2.negreanu_bot_V2 import BotNegreanu_V2, build_stats_context as build_negreanu_v2_stats_context
from player_stats import PlayerStatsTracker
from utils.utils import build_positions_map


HERO_SEAT = 0
STREETS = ("preflop", "flop", "turn", "river")
ACTION_ALIASES = {
    "check": "check",
    "call": "call",
    "chiama": "call",
    "fold": "fold",
    "muck": "fold",
    "raise": "raise",
    "rilancia": "raise",
    "puntata": "raise",
    "bet": "raise",
    "all-in": "raise",
}
IGNORED_ACTIONS = {"waiting", "vinto", "mettisb", "mettibb", ""}
POSITION_ORDER = {
    "BTN": 0,
    "SB": 1,
    "BB": 2,
    "UTG": 3,
    "UTG+1": 4,
    "MP": 5,
    "LJ": 6,
    "HJ": 7,
    "CO": 8,
}


def _normalize_control_label(label: str) -> str:
    return "".join(ch for ch in (label or "").strip().lower() if ch.isalnum())


def _sanitize_action_button_label(label: str) -> str:
    text = str(label or "").strip()
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_first_amount(text: str) -> float | None:
    normalized_text = str(text or "")
    normalized_text = re.sub(r"(?i)e[o]", "e0", normalized_text)
    normalized_text = re.sub(r"(?i)\bo([.,]\d+)", r"0\1", normalized_text)
    match = re.search(r"(\d+(?:[.,]\d+)?)", normalized_text)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _has_fractional_part(value: float) -> bool:
    return abs(float(value) - round(float(value))) > 1e-6


def _money_scale_for_table(table: TableBase) -> int:
    numeric_values = [float(table.BB_amount or 0.0), float(table.pot_amount or 0.0)]
    numeric_values.extend(float(player.stack_amount or 0.0) for player in table.players)
    numeric_values.extend(float(player.bet_amount or 0.0) for player in table.players)
    if any(_has_fractional_part(value) for value in numeric_values):
        return 100
    parsed_amount = _extract_first_amount(table.amount_value_text or "")
    if parsed_amount is not None and _has_fractional_part(parsed_amount):
        return 100
    return 1


def _to_units(value: float | int | None, scale: int) -> int:
    return int(round(float(value or 0.0) * max(1, scale)))


def _extract_amount_units(text: str, scale: int) -> int | None:
    value = _extract_first_amount(text)
    if value is None:
        return None
    return _to_units(value, scale)


def _format_units(value: int | None, scale: int) -> str:
    if value is None:
        return "-"
    if scale <= 1:
        return str(int(value))
    rendered = f"{float(value) / float(scale):.2f}"
    return rendered.rstrip("0").rstrip(".")


def _button_area(button: dict[str, Any]) -> int:
    rect = button.get("button_rect") or {}
    left = int(rect.get("left") or 0)
    right = int(rect.get("right") or left)
    top = int(rect.get("top") or 0)
    bottom = int(rect.get("bottom") or top)
    return max(0, right - left) * max(0, bottom - top)


def _button_center_y(button: dict[str, Any]) -> float:
    rect = button.get("button_rect") or {}
    top = float(rect.get("top") or 0.0)
    bottom = float(rect.get("bottom") or top)
    return (top + bottom) / 2.0


def _button_width(button: dict[str, Any]) -> int:
    rect = button.get("button_rect") or {}
    left = int(rect.get("left") or 0)
    right = int(rect.get("right") or left)
    return max(0, right - left)


def _button_height(button: dict[str, Any]) -> int:
    rect = button.get("button_rect") or {}
    top = int(rect.get("top") or 0)
    bottom = int(rect.get("bottom") or top)
    return max(0, bottom - top)


def _estimate_shortcut_value(label: str, *, pot_amount: int, min_raise_to: int, max_raise_to: int, bb_amount: int, scale: int) -> int | None:
    normalized = _normalize_control_label(label)
    if not normalized:
        return None
    if "max" in normalized:
        return max_raise_to if max_raise_to > 0 else None
    if "min" in normalized:
        return min_raise_to if min_raise_to > 0 else None
    if "piatto" in normalized or "pot" in normalized:
        return pot_amount if pot_amount > 0 else None
    if "50" in normalized:
        return max(1, int(round(pot_amount * 0.5))) if pot_amount > 0 else None
    if "75" in normalized:
        return max(1, int(round(pot_amount * 0.75))) if pot_amount > 0 else None
    if "3bb" in normalized:
        return 3 * bb_amount if bb_amount > 0 else None
    value = _extract_amount_units(label, scale)
    if value is not None:
        return value
    return None


def _normalize_name_key(name: str) -> str:
    return "".join((name or "").strip().lower().split())


def _names_compatible(left: str, right: str) -> bool:
    left_key = _normalize_name_key(left)
    right_key = _normalize_name_key(right)
    if not left_key or not right_key:
        return False
    return (
        left_key == right_key
        or left_key.startswith(right_key)
        or right_key.startswith(left_key)
        or names_are_similar(left, right, 0.72)
    )


@dataclass
class LivePokerState:
    hole_cards: list[list[str]]
    board_cards: list[str]
    stacks: list[int]
    checking_or_calling_amount: int
    min_completion_betting_or_raising_to_amount: int
    max_completion_betting_or_raising_to_amount: int
    total_pot_amount: int
    pot: int


@dataclass
class HeroBotDecision:
    hand_id: int
    street: str
    action_kind: str
    action_amount: int | None
    hero_stack: int
    hero_bet: int
    call_amount: int
    min_raise_to: int
    max_raise_to: int
    money_scale: int
    position: str
    source_action_player: int | None
    source_action_kind: str | None
    selected_action_button: dict[str, Any] | None = None
    selected_amount_button: dict[str, Any] | None = None

    def summary(self) -> str:
        amount_part = f" {self.format_amount(self.action_amount)}" if self.action_amount is not None else ""
        return (
            f"HeroBot | hand={self.hand_id} street={self.street} pos={self.position or '-'} "
            f"hero_stack={self.format_amount(self.hero_stack)} call={self.format_amount(self.call_amount)} "
            f"raise_to=[{self.format_amount(self.min_raise_to)}-{self.format_amount(self.max_raise_to)}] "
            f"-> {self.action_kind}{amount_part}"
        )

    def format_amount(self, value: int | None) -> str:
        return _format_units(value, self.money_scale)


@dataclass
class _StreetState:
    raise_count: int = 0
    players_acted: set[int] = field(default_factory=set)
    actions_by_player: dict[int, dict[str, int]] = field(default_factory=dict)
    last_action_by_player: dict[int, str] = field(default_factory=dict)
    aggressor: int | None = None
    last_raise_to: int = 0
    last_raise_size: int = 0
    last_action_player: int | None = None
    last_action_kind: str = ""


class HeroBotBridge:
    def __init__(self, bot_kind: str = "negreanu_v2", profile_name: str = "blind_stealer"):
        self.bot_kind = bot_kind
        self.profile_name = profile_name
        self.bot = self._create_bot(bot_kind, profile_name)

        self._active_hand_id: int | None = None
        self._active_players: list[int] = []
        self._positions_map: dict[int, str] = {}
        self._folded_players: set[int] = set()
        self._trackers: dict[str, PlayerStatsTracker] = {}
        self._seat_tracker_keys: dict[int, str] = {}
        self._seat_display_names: dict[int, str] = {}
        self._consumed_action_keys: set[tuple[int, int, str, str, int, int]] = set()
        self._street_states: dict[str, _StreetState] = {}
        self._preflop_limpers: set[int] = set()
        self._preflop_aggressor: int | None = None
        self._button_player: int | None = None
        self._action_log: list[str] = []
        self._player_street_last_action: dict[int, dict[str, str]] = {}
        self._last_decision_key: tuple[Any, ...] | None = None
        self._last_emitted_recommendation: tuple[Any, ...] | None = None
        self._last_seen_street = "unknown"
        self._state_changed = False
        self._pending_hero_turn = False
        self._last_observed_actor: int | None = None
        self._hand_flushed = False
        self._hero_buttons_visible = False
        self._hero_available_actions: list[dict[str, Any]] = []
        self._hero_amount_buttons: list[dict[str, Any]] = []
        self._hero_raw_available_actions: list[dict[str, Any]] = []
        self._hero_raw_amount_buttons: list[dict[str, Any]] = []
        self._hero_amount_value_text = ""
        self._last_controls_key: tuple[Any, ...] | None = None
        self._stable_controls_frames = 0
        self._money_scale = 1
        self._last_turn_decision_key: tuple[Any, ...] | None = None
        self._hero_committed_actions: dict[str, tuple[str, int | None]] = {}

    def process_table(self, table: TableBase) -> HeroBotDecision | None:
        if table.hands_number <= 0:
            return None
        self._money_scale = _money_scale_for_table(table)

        state_changed = self._state_changed
        if self._active_hand_id != table.hands_number:
            self._finalize_hand()
            self._start_hand(table)
            state_changed = True
        elif table.street != self._last_seen_street:
            self._on_street_change(table)
            state_changed = True

        state_changed = self._sync_hero_controls(table) or state_changed
        state_changed = self._ingest_observed_actions(table) or state_changed
        self._maybe_flush_finished_hand(table)
        self._state_changed = state_changed
        self._last_seen_street = table.street

        if not state_changed:
            return None

        committed_action_kind = self._hero_committed_actions.get(table.street, ("", None))[0]
        street_state = self._street_state(table.street)
        if committed_action_kind and street_state.last_action_player == HERO_SEAT:
            return None

        if not self._pending_hero_turn:
            return None

        if not self._hero_ready_to_act(table):
            return None

        turn_decision_key = self._build_turn_decision_key(table)
        if turn_decision_key == self._last_turn_decision_key:
            return None

        decision_key = self._build_decision_key(table)
        if decision_key == self._last_decision_key:
            return None

        state = self._build_live_state(table)
        if state is None:
            return None

        stats_context = self._build_stats_context(table, state)
        action = self.bot.act(state, HERO_SEAT, stats_context=stats_context)
        action = self._coerce_action_to_visible_controls(action, state)
        selected_action_button = self._select_action_button(action.kind, state.checking_or_calling_amount)
        if selected_action_button is None:
            selected_action_button = self._force_visible_action_button(
                table,
                action.kind,
                state.checking_or_calling_amount,
            )
        selected_amount_button = None
        if action.kind == "raise" and action.amount is not None:
            selected_amount_button = self._select_amount_button(action.amount)

        # If the current frame still lacks a real action target, keep waiting for
        # the next packets of the same turn instead of consuming the decision.
        if selected_action_button is None:
            print(
                "Hero bot skip: no matching visible action button "
                f"wanted={action.kind} call_amount={state.checking_or_calling_amount} "
                f"available={[button.get('label', '') for button in self._hero_available_actions]}"
            )
            return None

        recommendation_key = (
            table.hands_number,
            table.street,
            action.kind,
            action.amount,
            state.checking_or_calling_amount,
            state.min_completion_betting_or_raising_to_amount,
            state.max_completion_betting_or_raising_to_amount,
            tuple(state.board_cards),
            tuple(state.hole_cards[HERO_SEAT]),
            state.stacks[HERO_SEAT],
        )
        if recommendation_key == self._last_emitted_recommendation:
            return None
        self._last_decision_key = decision_key
        self._last_emitted_recommendation = recommendation_key
        self._last_turn_decision_key = turn_decision_key
        self._pending_hero_turn = False
        self._record_hero_committed_action(table, state, action.kind, action.amount)

        return HeroBotDecision(
            hand_id=table.hands_number,
            street=table.street,
            action_kind=action.kind,
            action_amount=action.amount,
            hero_stack=state.stacks[HERO_SEAT],
            hero_bet=self._player_bet(table, HERO_SEAT),
            call_amount=state.checking_or_calling_amount,
            min_raise_to=state.min_completion_betting_or_raising_to_amount,
            max_raise_to=state.max_completion_betting_or_raising_to_amount,
            money_scale=self._money_scale,
            position=self._positions_map.get(HERO_SEAT, ""),
            source_action_player=self._street_state(table.street).last_action_player,
            source_action_kind=self._street_state(table.street).last_action_kind or None,
            selected_action_button=selected_action_button,
            selected_amount_button=selected_amount_button,
        )

    def _create_bot(self, bot_kind: str, profile_name: str):
        if bot_kind == "biagio":
            return BotBiagio()
        if bot_kind == "negreanu_v1":
            return BotNegreanu(profile_name=profile_name)
        return BotNegreanu_V2(profile_name=profile_name)

    def _start_hand(self, table: TableBase) -> None:
        self._active_hand_id = table.hands_number
        self._folded_players = set()
        self._consumed_action_keys = set()
        self._street_states = {street: _StreetState() for street in STREETS}
        self._preflop_limpers = set()
        self._preflop_aggressor = None
        self._action_log = []
        self._last_decision_key = None
        self._last_emitted_recommendation = None
        self._last_turn_decision_key = None
        self._active_players = self._detect_active_players(table)
        self._seat_display_names = {
            player.player_index: (player.name or "").strip()
            for player in table.players
            if (player.name or "").strip()
        }
        self._button_player = self._find_button_player(table)
        self._positions_map = build_positions_map(self._active_players, self._button_player)
        self._seat_tracker_keys = {}
        self._player_street_last_action = {
            seat: {street: "-" for street in STREETS}
            for seat in range(max((player.player_index for player in table.players), default=HERO_SEAT) + 1)
        }
        self._last_seen_street = table.street
        self._state_changed = True
        self._pending_hero_turn = self._hero_is_first_to_act(table.street)
        self._last_observed_actor = None
        self._hand_flushed = False
        self._hero_buttons_visible = bool(table.buttons_visible or table.hero_to_act)
        self._hero_raw_available_actions = list(table.available_actions)
        self._hero_raw_amount_buttons = list(table.amount_buttons)
        self._hero_amount_value_text = table.amount_value_text
        self._hero_available_actions = self._clean_available_actions(table)
        self._hero_amount_buttons = self._clean_amount_buttons(table)
        self._last_controls_key = self._controls_key(table)
        self._stable_controls_frames = 0
        self._hero_committed_actions = {}

        players_in_hand = len(self._active_players)
        big_blind = max(1.0, float(self._bb_amount_units(table)))
        for seat in self._active_players:
            tracker = self._resolve_tracker(table, seat)
            tracker.start_hand(
                hand_id=table.hands_number,
                position=self._positions_map.get(seat, ""),
                stack_bb=self._player_stack(table, seat) / big_blind,
                players_in_hand=players_in_hand,
            )

        self.bot.start_stats_hand(
            hand_id=table.hands_number,
            position=self._positions_map.get(HERO_SEAT, ""),
            stack_bb=self._player_stack(table, HERO_SEAT) / big_blind,
            players_in_hand=players_in_hand,
        )

    def _finalize_hand(self) -> None:
        self.flush()
        self._hand_flushed = True

    def flush(self) -> None:
        for tracker in self._trackers.values():
            tracker.save_to_db()
        stats_tracker = getattr(self.bot, "stats_tracker", None)
        if stats_tracker is not None:
            stats_tracker.save_to_db()

    def _maybe_flush_finished_hand(self, table: TableBase) -> None:
        if self._active_hand_id is None or self._hand_flushed:
            return

        winner_detected = any(
            ((player.inferred_action or "").strip().lower().startswith("vin"))
            for player in table.players
        )
        if winner_detected:
            self.flush()
            self._hand_flushed = True

    def _on_street_change(self, table: TableBase) -> None:
        self._last_decision_key = None
        self._last_emitted_recommendation = None
        self._last_turn_decision_key = None
        self._state_changed = True
        self._pending_hero_turn = self._hero_is_first_to_act(table.street)
        self._last_observed_actor = None
        self._hero_committed_actions[table.street] = ("", None)
        if self._hero_buttons_visible:
            self._pending_hero_turn = True
        if table.street == "flop":
            for seat in self._active_players:
                if seat not in self._folded_players:
                    self._resolve_tracker(table, seat).note_saw_flop()
            self.bot.note_stats_saw_flop()

    def _detect_active_players(self, table: TableBase) -> list[int]:
        active = []
        hero_has_cards = len(table.hero_cards) == 2
        for player in table.players:
            if player.player_index == HERO_SEAT and hero_has_cards:
                active.append(player.player_index)
            elif player.has_covered_card:
                active.append(player.player_index)
            elif player.has_dealer_button:
                active.append(player.player_index)
            elif float(player.stack_amount or 0.0) > 0.0:
                active.append(player.player_index)
        return active

    def _find_button_player(self, table: TableBase) -> int:
        for player in table.players:
            if player.has_dealer_button:
                return player.player_index
        return self._active_players[0] if self._active_players else HERO_SEAT

    def _stable_player_name(self, table: TableBase, seat: int) -> str:
        player = table.get_player(seat)
        current_name = ((player.name if player is not None else "") or "").strip()
        if current_name:
            self._seat_display_names[seat] = current_name
            return current_name
        return self._seat_display_names.get(seat, "")

    def _resolve_tracker(self, table: TableBase, seat: int) -> PlayerStatsTracker:
        name = self._stable_player_name(table, seat) or f"seat_{seat}"
        normalized_name = _normalize_name_key(name)

        previous_key = self._seat_tracker_keys.get(seat)
        if previous_key:
            previous_tracker = self._trackers.get(previous_key)
            if previous_tracker is not None:
                if previous_key.startswith("seat_") and normalized_name:
                    del self._trackers[previous_key]
                elif not normalized_name or _names_compatible(previous_tracker.player_name, name):
                    return previous_tracker

        if normalized_name:
            for tracker_key, tracker in self._trackers.items():
                if _names_compatible(tracker.player_name, name):
                    self._seat_tracker_keys[seat] = tracker_key
                    return tracker
            tracker_key = normalized_name
        else:
            tracker_key = previous_key or f"seat_{seat}"

        tracker = self._trackers.get(tracker_key)
        if tracker is None:
            tracker = PlayerStatsTracker(name)
            self._trackers[tracker_key] = tracker
        self._seat_tracker_keys[seat] = tracker_key
        return tracker

    def _street_state(self, street: str) -> _StreetState:
        return self._street_states.setdefault(street, _StreetState())

    def _ingest_observed_actions(self, table: TableBase) -> bool:
        state_changed = False
        street = table.street
        state = self._street_state(street)
        current_max_bet = max((self._player_bet(table, seat) for seat in self._active_players), default=0)

        for player in table.players:
            normalized_action = self._normalize_action(player.inferred_action)
            if normalized_action is None:
                continue

            if (
                player.player_index == HERO_SEAT
                and (table.hero_to_act or self._hero_buttons_visible or table.available_actions or table.amount_buttons)
                and not self._hero_committed_actions.get(street, ("", None))[0]
            ):
                continue

            action_key = (
                table.hands_number,
                player.player_index,
                street,
                normalized_action,
                self._player_bet(table, player.player_index),
                self._player_stack(table, player.player_index),
            )
            if action_key in self._consumed_action_keys:
                continue

            if normalized_action == "raise" and not self._is_plausible_raise_action(table, player.player_index):
                self._consumed_action_keys.add(action_key)
                continue

            if player.player_index == HERO_SEAT and self._hero_committed_actions.get(street, ("", None))[0]:
                self._consumed_action_keys.add(action_key)
                continue

            self._consumed_action_keys.add(action_key)
            state_changed = True
            self._last_observed_actor = player.player_index

            if normalized_action == "fold":
                self._folded_players.add(player.player_index)

            if normalized_action == "raise":
                raise_to = self._player_bet(table, player.player_index)
                previous_to_call = max(state.last_raise_to, self._bb_amount_units(table))
                raise_size = max(raise_to - previous_to_call, self._bb_amount_units(table))
                state.raise_count += 1
                state.aggressor = player.player_index
                state.last_raise_to = max(state.last_raise_to, raise_to, current_max_bet)
                state.last_raise_size = max(state.last_raise_size, raise_size)
                if street == "preflop":
                    self._preflop_aggressor = player.player_index

            if (
                street == "preflop"
                and normalized_action == "call"
                and state.raise_count == 0
                and self._player_bet(table, player.player_index) > 0
            ):
                self._preflop_limpers.add(player.player_index)

            state.players_acted.add(player.player_index)
            counters = state.actions_by_player.setdefault(
                player.player_index,
                {"total": 0, "check": 0, "call": 0, "raise": 0, "fold": 0},
            )
            counters["total"] += 1
            counters[normalized_action] += 1
            state.last_action_by_player[player.player_index] = normalized_action
            self._player_street_last_action.setdefault(
                player.player_index,
                {street_name: "-" for street_name in STREETS},
            )[street] = normalized_action
            state.last_action_player = player.player_index
            state.last_action_kind = normalized_action
            self._action_log.append(
                f"{street.upper():<7} | "
                f"{(self._stable_player_name(table, player.player_index) or f'Seat {player.player_index}')} "
                f"(seat {player.player_index}, {self._positions_map.get(player.player_index, '-')}, "
                f"cards {self._player_cards_for_log(table, player.player_index)}) -> "
                f"{self._format_logged_action(normalized_action, self._player_bet(table, player.player_index), call_amount=None)}"
            )

            if player.player_index != HERO_SEAT:
                tracker = self._resolve_tracker(table, player.player_index)
                call_amount = self._infer_call_amount_before_action(
                    table=table,
                    seat=player.player_index,
                    street_state=state,
                    normalized_action=normalized_action,
                    current_max_bet=current_max_bet,
                )
                tracker.record_decision(
                    street=street,
                    action_kind=normalized_action,
                    call_amount=call_amount,
                    raise_count_before_action=max(0, state.raise_count - (1 if normalized_action == "raise" else 0)),
                    is_cbet_opportunity=self._is_cbet_opportunity(table, player.player_index),
                    is_facing_cbet=self._is_facing_cbet(table, player.player_index),
                )
                self._action_log[-1] = (
                    f"{street.upper():<7} | "
                    f"{(self._stable_player_name(table, player.player_index) or f'Seat {player.player_index}')} "
                    f"(seat {player.player_index}, {self._positions_map.get(player.player_index, '-')}, "
                    f"cards {self._player_cards_for_log(table, player.player_index)}) -> "
                    f"{self._format_logged_action(normalized_action, self._player_bet(table, player.player_index), call_amount)}"
                )

            if player.player_index == HERO_SEAT:
                self._pending_hero_turn = False
                self._last_turn_decision_key = None
            elif HERO_SEAT in self._active_players and HERO_SEAT not in self._folded_players:
                if self._hero_committed_actions.get(street, ("", None))[0]:
                    self._hero_committed_actions[street] = ("", None)
                self._pending_hero_turn = self._hero_is_next_to_act(table)

        return state_changed

    def _normalize_action(self, action: str | None) -> str | None:
        raw = (action or "").strip().lower()
        if raw in IGNORED_ACTIONS:
            return None
        return ACTION_ALIASES.get(raw)

    def _hero_ready_to_act(self, table: TableBase) -> bool:
        if table.get_player(HERO_SEAT) is None:
            return False
        if len(table.hero_cards) != 2:
            return False
        if HERO_SEAT in self._folded_players:
            return False
        if HERO_SEAT not in self._active_players:
            return False
        if not self._positions_map:
            return False
        controls_visible = (
            bool(self._hero_available_actions)
            or self._has_real_raise_panel(table)
            or self._has_red_action_area(table)
        )
        if table.hero_to_act and controls_visible:
            return True
        if not self._hero_is_next_to_act(table):
            return False
        if self._hero_buttons_visible:
            return controls_visible
        return True

    def _ordered_seats_for_street(self, street: str) -> list[int]:
        if street == "preflop":
            rank_map = {
                "UTG": 0,
                "UTG+1": 1,
                "MP": 2,
                "LJ": 3,
                "HJ": 4,
                "CO": 5,
                "BTN": 6,
                "SB": 7,
                "BB": 8,
            }
        else:
            rank_map = {
                "SB": 0,
                "BB": 1,
                "UTG": 2,
                "UTG+1": 3,
                "MP": 4,
                "LJ": 5,
                "HJ": 6,
                "CO": 7,
                "BTN": 8,
            }
        ordered = [
            seat
            for seat in self._active_players
            if seat not in self._folded_players and self._positions_map.get(seat, "")
        ]
        ordered.sort(key=lambda seat: rank_map.get(self._positions_map.get(seat, ""), 99))
        return ordered

    def _next_seat_to_act(self, street: str) -> int | None:
        ordered = self._ordered_seats_for_street(street)
        if not ordered:
            return None
        street_state = self._street_state(street)
        last_actor = street_state.last_action_player
        if last_actor not in ordered:
            return ordered[0]
        actor_index = ordered.index(last_actor)
        if actor_index + 1 < len(ordered):
            return ordered[actor_index + 1]
        return None

    def _hero_is_next_to_act(self, table: TableBase) -> bool:
        next_seat = self._next_seat_to_act(table.street)
        if next_seat is None:
            return self._hero_is_first_to_act(table.street)
        return next_seat == HERO_SEAT

    def _build_decision_key(self, table: TableBase) -> tuple[Any, ...]:
        hero = table.get_player(HERO_SEAT)
        street_state = self._street_state(table.street)
        board = tuple(card.get("name", "") for card in table.board_cards)
        hero_cards = tuple(card.get("name", "") for card in table.hero_cards)
        return (
            table.hands_number,
            table.street,
            board,
            hero_cards,
            tuple(button.get("label", "") for button in self._hero_available_actions),
            tuple(button.get("label", "") for button in self._hero_amount_buttons),
            self._hero_amount_value_text,
            self._player_stack(table, HERO_SEAT),
            self._player_bet(table, HERO_SEAT),
            max((self._player_bet(table, seat) for seat in self._active_players), default=0),
            street_state.raise_count,
            street_state.last_action_player,
            street_state.last_action_kind,
            hero.inferred_action if hero is not None else "",
        )

    def _build_turn_decision_key(self, table: TableBase) -> tuple[Any, ...]:
        street_state = self._street_state(table.street)
        return (
            table.hands_number,
            table.street,
            tuple(card.get("name", "") for card in table.board_cards),
            tuple(card.get("name", "") for card in table.hero_cards),
            street_state.last_action_player,
            street_state.last_action_kind,
            street_state.raise_count,
            tuple(sorted(self._folded_players)),
        )

    def _build_live_state(self, table: TableBase) -> LivePokerState | None:
        hero = table.get_player(HERO_SEAT)
        if hero is None:
            return None

        max_seat = max((player.player_index for player in table.players), default=HERO_SEAT)
        stacks = [0] * (max_seat + 1)
        hole_cards = [[] for _ in range(max_seat + 1)]

        for player in table.players:
            stacks[player.player_index] = self._player_stack(table, player.player_index)
        hole_cards[HERO_SEAT] = [card.get("name", "") for card in table.hero_cards]

        current_max_bet = max((self._player_bet(table, seat) for seat in self._active_players), default=0)
        hero_bet = self._player_bet(table, HERO_SEAT)
        visible_call_amount = self._visible_call_amount_units(table)
        call_amount = visible_call_amount if visible_call_amount is not None else max(0, current_max_bet - hero_bet)
        street_state = self._street_state(table.street)
        bb_amount = self._bb_amount_units(table)
        min_raise_increment = street_state.last_raise_size or bb_amount
        min_raise_to = current_max_bet + min_raise_increment
        max_raise_to = hero_bet + stacks[HERO_SEAT]
        visible_amount_value = _extract_amount_units(table.amount_value_text or "", self._money_scale)

        if visible_amount_value is not None and visible_amount_value > 0:
            min_raise_to = visible_amount_value
        elif visible_call_amount is not None:
            min_raise_to = hero_bet + visible_call_amount + bb_amount

        if max_raise_to <= current_max_bet:
            min_raise_to = 0
            max_raise_to = 0
        else:
            min_raise_to = min(min_raise_to, max_raise_to)

        board_cards = [card.get("name", "") for card in table.board_cards]
        pot_amount = self._pot_amount_units(table)
        return LivePokerState(
            hole_cards=hole_cards,
            board_cards=board_cards,
            stacks=stacks,
            checking_or_calling_amount=call_amount,
            min_completion_betting_or_raising_to_amount=min_raise_to,
            max_completion_betting_or_raising_to_amount=max_raise_to,
            total_pot_amount=pot_amount,
            pot=pot_amount,
        )

    def _build_stats_context(self, table: TableBase, state: LivePokerState) -> dict[str, Any]:
        street = table.street
        street_state = self._street_state(street)
        hero_stack = state.stacks[HERO_SEAT]
        big_blind = max(1.0, float(self._bb_amount_units(table)))
        hero_stack_bb = hero_stack / big_blind

        opponent_stats = []
        for seat in self._active_players:
            if seat == HERO_SEAT or seat in self._folded_players:
                continue
            tracker = self._resolve_tracker(table, seat)
            snapshot = tracker.build_stats().to_dict()
            snapshot.update(
                {
                    "seat": seat,
                    "position": self._positions_map.get(seat, ""),
                    "last_action_kind": street_state.last_action_by_player.get(seat, ""),
                    "last_action_street": street if seat in street_state.last_action_by_player else "",
                    "was_preflop_aggressor": self._preflop_aggressor == seat,
                    "is_current_aggressor": street_state.aggressor == seat,
                    "street_actions_total": street_state.actions_by_player.get(seat, {}).get("total", 0),
                    "street_checks": street_state.actions_by_player.get(seat, {}).get("check", 0),
                    "street_calls": street_state.actions_by_player.get(seat, {}).get("call", 0),
                    "street_raises": street_state.actions_by_player.get(seat, {}).get("raise", 0),
                    "street_folds": street_state.actions_by_player.get(seat, {}).get("fold", 0),
                }
            )
            opponent_stats.append(snapshot)

        effective_stack_bb = hero_stack_bb
        opp_stack_bbs = [float(entry.get("stack_bb", 0.0)) for entry in opponent_stats if float(entry.get("stack_bb", 0.0)) > 0]
        if opp_stack_bbs:
            effective_stack_bb = min([hero_stack_bb, *opp_stack_bbs])

        last_actor_stats: dict[str, Any] | None = None
        if street_state.last_action_player is not None and street_state.last_action_player != HERO_SEAT:
            tracker = self._resolve_tracker(table, street_state.last_action_player)
            last_actor_stats = tracker.build_stats().to_dict()
            last_actor_stats.update(
                {
                    "seat": street_state.last_action_player,
                    "position": self._positions_map.get(street_state.last_action_player, ""),
                    "last_action_kind": street_state.last_action_kind,
                    "last_action_street": street,
                }
            )

        players_in_hand = len([seat for seat in self._active_players if seat not in self._folded_players])
        players_acted_this_street = len(street_state.players_acted)
        players_yet_to_act = max(0, players_in_hand - players_acted_this_street - 1)

        build_context = build_negreanu_v2_stats_context
        if isinstance(self.bot, BotBiagio):
            build_context = build_biagio_stats_context
        elif isinstance(self.bot, BotNegreanu):
            build_context = build_negreanu_stats_context

        common_kwargs = {
            "street": street,
            "call_amount": state.checking_or_calling_amount,
            "raise_count_before_action": street_state.raise_count,
            "position": self._positions_map.get(HERO_SEAT, ""),
            "players_in_hand": players_in_hand,
            "opponents": opponent_stats,
            "is_cbet_opportunity": self._is_cbet_opportunity(table, HERO_SEAT),
            "is_facing_cbet": self._is_facing_cbet(table, HERO_SEAT),
            "big_blind": big_blind,
            "pot": state.total_pot_amount,
            "hero_stack_bb": hero_stack_bb,
            "effective_stack_bb": effective_stack_bb,
        }

        if build_context is build_biagio_stats_context:
            context = build_context(**common_kwargs)
        else:
            context = build_context(
            **common_kwargs,
            limper_count=len(self._preflop_limpers),
            is_limped_pot=street == "preflop" and street_state.raise_count == 0 and bool(self._preflop_limpers),
            pot_was_limped_preflop=street != "preflop" and self._preflop_aggressor is None and bool(self._preflop_limpers),
            players_acted_this_street=players_acted_this_street,
            players_yet_to_act=players_yet_to_act,
            current_street_aggressor_position=self._positions_map.get(street_state.aggressor or -1, ""),
            preflop_aggressor_position=self._positions_map.get(self._preflop_aggressor or -1, ""),
            hero_has_initiative=street != "preflop" and self._preflop_aggressor == HERO_SEAT,
            hero_is_preflop_aggressor=self._preflop_aggressor == HERO_SEAT,
            hero_is_current_street_aggressor=street_state.aggressor == HERO_SEAT,
            last_action_kind=street_state.last_action_kind,
            last_action_street=street if street_state.last_action_kind else "",
            last_action_position=self._positions_map.get(street_state.last_action_player or -1, ""),
            last_actor_stats=last_actor_stats,
        )
        context.update(
            {
                "available_actions": list(self._hero_available_actions),
                "amount_buttons": list(self._hero_amount_buttons),
                "amount_button_labels": [button.get("label", "") for button in self._hero_amount_buttons],
                "amount_value_text": self._hero_amount_value_text,
                "buttons_visible": self._hero_buttons_visible,
            }
        )
        return context

    def _is_cbet_opportunity(self, table: TableBase, seat: int) -> bool:
        if table.street != "flop":
            return False
        street_state = self._street_state(table.street)
        return self._preflop_aggressor == seat and street_state.raise_count == 0

    def _is_facing_cbet(self, table: TableBase, seat: int) -> bool:
        if table.street != "flop":
            return False
        street_state = self._street_state(table.street)
        return (
            self._preflop_aggressor is not None
            and self._preflop_aggressor != seat
            and street_state.raise_count > 0
            and street_state.aggressor == self._preflop_aggressor
        )

    def _player_stack(self, table: TableBase, seat: int) -> int:
        player = table.get_player(seat)
        if player is None:
            return 0
        return _to_units(player.stack_amount, self._money_scale)

    def _player_bet(self, table: TableBase, seat: int) -> int:
        player = table.get_player(seat)
        if player is None:
            return 0
        return _to_units(player.bet_amount, self._money_scale)

    def _bb_amount_units(self, table: TableBase) -> int:
        return max(1, _to_units(table.BB_amount, self._money_scale))

    def _pot_amount_units(self, table: TableBase) -> int:
        return _to_units(table.pot_amount, self._money_scale)

    def _is_plausible_raise_action(self, table: TableBase, seat: int) -> bool:
        raise_to = self._player_bet(table, seat)
        stack_after_bet = self._player_stack(table, seat)
        bb_amount = self._bb_amount_units(table)
        if raise_to <= 0:
            return False
        max_possible_total = raise_to + stack_after_bet
        if max_possible_total <= 0:
            return False
        if raise_to < bb_amount:
            return False
        if raise_to > int(round(max_possible_total * 1.15)) + bb_amount:
            return False
        return True

    def _call_amount_for_seat(self, table: TableBase, seat: int) -> int:
        current_max_bet = max((self._player_bet(table, active_seat) for active_seat in self._active_players), default=0)
        return max(0, current_max_bet - self._player_bet(table, seat))

    def _visible_call_amount_units(self, table: TableBase) -> int | None:
        for button in table.available_actions:
            label = str(button.get("label", "")).strip().lower()
            if "chiama" not in label and "call" not in label:
                continue
            parsed = _extract_amount_units(label, self._money_scale)
            if parsed is not None:
                return parsed
        return None

    def _infer_call_amount_before_action(
        self,
        *,
        table: TableBase,
        seat: int,
        street_state: _StreetState,
        normalized_action: str,
        current_max_bet: int,
    ) -> int:
        player_bet = self._player_bet(table, seat)
        previous_to_call = max(street_state.last_raise_to, self._bb_amount_units(table), current_max_bet)

        if normalized_action == "call":
            if player_bet > 0:
                return player_bet
            return previous_to_call

        if normalized_action == "raise":
            if street_state.last_raise_to > 0:
                return max(0, street_state.last_raise_to - player_bet)
            return max(0, previous_to_call - player_bet)

        return max(0, previous_to_call - player_bet)

    def get_position_for_seat(self, seat: int) -> str:
        return self._positions_map.get(seat, "-")

    def get_button_player(self) -> int | None:
        return self._button_player

    def get_action_log(self, limit: int = 12) -> list[str]:
        if limit <= 0:
            return []
        return self._action_log[-limit:]

    def get_player_street_actions_text(self, seat: int) -> str:
        seat_actions = self._player_street_last_action.get(seat, {})
        return (
            f"P:{seat_actions.get('preflop', '-'):>5} "
            f"F:{seat_actions.get('flop', '-'):>5} "
            f"T:{seat_actions.get('turn', '-'):>5} "
            f"R:{seat_actions.get('river', '-'):>5}"
        )

    def get_player_status_text(self, seat: int, acting_seat: int | None = HERO_SEAT) -> str:
        status = []
        if seat == acting_seat:
            status.append("ACT")
        if seat in self._active_players and seat not in self._folded_players:
            status.append("IN_HAND")
        else:
            status.append("FOLDED")
        position = self._positions_map.get(seat, "")
        if position == "BTN":
            status.append("BTN")
        elif position == "SB":
            status.append("SB")
        elif position == "BB":
            status.append("BB")
        return " ".join(status)

    def get_acting_seat(self, hero_decision: HeroBotDecision | None = None) -> int | None:
        if hero_decision is not None or self._pending_hero_turn or self._hero_buttons_visible:
            return HERO_SEAT
        return None

    def get_available_actions(self) -> list[dict[str, Any]]:
        return list(self._hero_available_actions)

    def get_amount_buttons(self) -> list[dict[str, Any]]:
        return list(self._hero_amount_buttons)

    def get_amount_value_text(self) -> str:
        return self._hero_amount_value_text

    def invalidate_hero_decision(self, hand_id: int, street: str) -> None:
        if hand_id != self._active_hand_id:
            return
        street_name = str(street or "").strip().lower()
        if street_name and street_name in self._hero_committed_actions:
            self._hero_committed_actions[street_name] = ("", None)
        self._last_decision_key = None
        self._last_emitted_recommendation = None
        self._last_turn_decision_key = None
        self._pending_hero_turn = True
        self._state_changed = True

    def _hero_is_first_to_act(self, street: str) -> bool:
        hero_pos = self._positions_map.get(HERO_SEAT, "")
        if not hero_pos:
            return False

        active_positions = [
            self._positions_map.get(seat, "")
            for seat in self._active_players
            if seat not in self._folded_players and self._positions_map.get(seat, "")
        ]
        if not active_positions:
            return False

        if street == "preflop":
            preflop_order = {
                "UTG": 0,
                "UTG+1": 1,
                "MP": 2,
                "LJ": 3,
                "HJ": 4,
                "CO": 5,
                "BTN": 6,
                "SB": 7,
                "BB": 8,
            }
            hero_rank = preflop_order.get(hero_pos, 99)
            best_rank = min(preflop_order.get(pos, 99) for pos in active_positions)
            return hero_rank == best_rank

        postflop_order = {
            "SB": 0,
            "BB": 1,
            "UTG": 2,
            "UTG+1": 3,
            "MP": 4,
            "LJ": 5,
            "HJ": 6,
            "CO": 7,
            "BTN": 8,
        }
        hero_rank = postflop_order.get(hero_pos, 99)
        best_rank = min(postflop_order.get(pos, 99) for pos in active_positions)
        return hero_rank == best_rank

    def _player_cards_for_log(self, table: TableBase, seat: int) -> str:
        if seat != HERO_SEAT:
            return "-"
        cards = [str(card.get("name", "")).upper() for card in table.hero_cards if card.get("name")]
        return " ".join(cards) if cards else "-"

    def _format_logged_action(self, action_kind: str, bet_amount: int, call_amount: int | None) -> str:
        if action_kind == "raise":
            return f"raise {self._format_amount(bet_amount)}"
        if action_kind == "call":
            if call_amount is not None and call_amount > 0:
                return f"call {self._format_amount(call_amount)}"
            return "check"
        return action_kind

    def _record_hero_committed_action(
        self,
        table: TableBase,
        state: LivePokerState,
        action_kind: str,
        action_amount: int | None,
    ) -> None:
        street = table.street
        street_state = self._street_state(street)
        if self._hero_committed_actions.get(street) == (action_kind, action_amount):
            return

        self._hero_committed_actions[street] = (action_kind, action_amount)
        self._player_street_last_action.setdefault(
            HERO_SEAT,
            {street_name: "-" for street_name in STREETS},
        )[street] = action_kind
        street_state.players_acted.add(HERO_SEAT)
        counters = street_state.actions_by_player.setdefault(
            HERO_SEAT,
            {"total": 0, "check": 0, "call": 0, "raise": 0, "fold": 0},
        )
        counters["total"] += 1
        if action_kind in counters:
            counters[action_kind] += 1
        street_state.last_action_by_player[HERO_SEAT] = action_kind
        street_state.last_action_player = HERO_SEAT
        street_state.last_action_kind = action_kind

        if action_kind == "fold":
            self._folded_players.add(HERO_SEAT)
        elif action_kind == "raise":
            current_to_call = max(
                street_state.last_raise_to,
                max((self._player_bet(table, seat) for seat in self._active_players), default=0),
                self._bb_amount_units(table),
            )
            raise_to = action_amount or state.min_completion_betting_or_raising_to_amount
            raise_size = max(self._bb_amount_units(table), raise_to - current_to_call)
            street_state.raise_count += 1
            street_state.aggressor = HERO_SEAT
            street_state.last_raise_to = max(street_state.last_raise_to, raise_to)
            street_state.last_raise_size = max(street_state.last_raise_size, raise_size)
            if street == "preflop":
                self._preflop_aggressor = HERO_SEAT

        hero_name = self._stable_player_name(table, HERO_SEAT) or f"Seat {HERO_SEAT}"
        logged_amount = action_amount if action_kind == "raise" else self._player_bet(table, HERO_SEAT)
        logged_call = state.checking_or_calling_amount if action_kind == "call" else None
        self._action_log.append(
            f"{street.upper():<7} | "
            f"{hero_name} "
            f"(seat {HERO_SEAT}, {self._positions_map.get(HERO_SEAT, '-')}, "
            f"cards {self._player_cards_for_log(table, HERO_SEAT)}) -> "
            f"{self._format_logged_action(action_kind, logged_amount, logged_call)}"
        )

    def _format_amount(self, value: int | None) -> str:
        return _format_units(value, self._money_scale)

    def _has_red_action_area(self, table: TableBase) -> bool:
        raw_table = table.raw.get("table", table.raw) if isinstance(table.raw, dict) else {}
        return bool(raw_table.get("has_red_action_area", False))

    def _controls_key(self, table: TableBase) -> tuple[Any, ...]:
        return (
            tuple(
                (
                    button.get("label", ""),
                    button.get("roi_label", ""),
                )
                for button in table.available_actions
            ),
            tuple(
                (
                    button.get("label", ""),
                    button.get("roi_label", ""),
                )
                for button in table.amount_buttons
            ),
            table.amount_value_text or "",
            self._has_red_action_area(table),
        )

    def _sync_hero_controls(self, table: TableBase) -> bool:
        controls_key = self._controls_key(table)
        changed = controls_key != self._last_controls_key
        if changed:
            self._stable_controls_frames = 1
        else:
            self._stable_controls_frames += 1
        self._last_controls_key = controls_key
        self._hero_raw_available_actions = list(table.available_actions)
        self._hero_raw_amount_buttons = list(table.amount_buttons)
        self._hero_amount_value_text = table.amount_value_text or ""
        self._hero_available_actions = self._clean_available_actions(table)
        self._hero_amount_buttons = self._clean_amount_buttons(table)
        self._hero_buttons_visible = bool(table.buttons_visible or table.hero_to_act)
        red_action_area_visible = self._has_red_action_area(table)
        if table.hero_to_act and self._hero_available_actions:
            self._pending_hero_turn = True
        elif table.hero_to_act and self._has_real_raise_panel(table):
            self._pending_hero_turn = True
        elif table.hero_to_act and red_action_area_visible:
            self._pending_hero_turn = True
        if (
            self._hero_buttons_visible
            and (self._hero_available_actions or self._has_real_raise_panel(table) or red_action_area_visible)
            and self._stable_controls_frames >= 2
            and not self._pending_hero_turn
        ):
            self._pending_hero_turn = True
        return changed

    def _has_real_raise_panel(self, table: TableBase) -> bool:
        amount_value_text = (table.amount_value_text or "").strip()
        if amount_value_text:
            return True
        shortcut_count = 0
        for amount_button in table.amount_buttons:
            roi_label = str(amount_button.get("roi_label", "")).strip().lower()
            label = str(amount_button.get("label", "")).strip().lower()
            if roi_label == "select_amount_button":
                shortcut_count += 1
                if label and label != "raise":
                    return True
            elif roi_label in {"select_amount_plus", "select_amount_minus"}:
                shortcut_count += 1
        return shortcut_count >= 3

    def _map_button_to_action_kind(self, button: dict[str, Any], call_amount: int = 0) -> str:
        label = _normalize_control_label(str(button.get("label", "")))
        if not label:
            return ""
        if "fold" in label or "passa" in label:
            return "fold"
        if "check" in label or "checkcall" in label:
            return "check"
        if "call" in label or "chiama" in label:
            return "call" if call_amount > 0 else "check"
        if "raise" in label or "rilancia" in label or "bet" in label or "punta" in label:
            return "raise"
        return ""

    def _select_action_button(self, action_kind: str, call_amount: int = 0) -> dict[str, Any] | None:
        wanted = (action_kind or "").strip().lower()
        if not wanted:
            return None

        best: dict[str, Any] | None = None
        fallback: dict[str, Any] | None = None
        for button in self._hero_available_actions:
            if str(button.get("action_kind", "")).strip().lower() == wanted:
                return button
            mapped = self._map_button_to_action_kind(button, call_amount)

            if mapped == wanted:
                return button
            if wanted == "call" and mapped == "check":
                fallback = button
            elif wanted == "check" and mapped == "call":
                fallback = button
            elif wanted == "fold" and mapped == "check":
                fallback = button

        if fallback or best:
            return fallback or best

        raw_buttons = [dict(button) for button in self._hero_raw_available_actions]
        if not raw_buttons:
            return None

        def x_pos(button: dict[str, Any]) -> int:
            click_point = button.get("click_point") or {}
            button_rect = button.get("button_rect") or {}
            return int(click_point.get("x") or button_rect.get("left") or 0)

        raw_buttons.sort(key=x_pos)
        for button in raw_buttons:
            mapped = self._map_button_to_action_kind(button, call_amount)
            if mapped == wanted:
                return button
            if wanted in {"call", "fold"} and mapped == "check":
                fallback = button

        if wanted == "check" and call_amount <= 0 and len(raw_buttons) == 1:
            return raw_buttons[0]
        if wanted == "fold" and call_amount > 0 and raw_buttons:
            return raw_buttons[0]
        if wanted == "call" and call_amount > 0 and len(raw_buttons) >= 2:
            return raw_buttons[1]
        if fallback is not None:
            return fallback

        return None

    def _force_visible_action_button(self, table: TableBase, action_kind: str, call_amount: int = 0) -> dict[str, Any] | None:
        if not self._has_red_action_area(table):
            return None

        visible_buttons = list(self._hero_available_actions) or [dict(button) for button in self._hero_raw_available_actions]
        if not visible_buttons:
            return None

        for button in visible_buttons:
            mapped = self._map_button_to_action_kind(button, call_amount)
            if mapped == action_kind:
                return button

        if action_kind in {"call", "fold"}:
            for button in visible_buttons:
                mapped = self._map_button_to_action_kind(button, call_amount)
                if mapped == "check":
                    return button

        if action_kind == "raise":
            for button in visible_buttons:
                mapped = self._map_button_to_action_kind(button, call_amount)
                if mapped in {"call", "check", "fold"}:
                    return button

        return visible_buttons[0]

    def _coerce_action_to_visible_controls(self, action, state: LivePokerState):
        available_kinds = {
            str(button.get("action_kind", "")).strip().lower()
            for button in self._hero_available_actions
            if str(button.get("action_kind", "")).strip()
        }
        if not available_kinds:
            return action
        if action.kind in available_kinds:
            return action
        if action.kind == "raise":
            if state.checking_or_calling_amount > 0 and "call" in available_kinds:
                return type(action)(kind="call", amount=None)
            if "check" in available_kinds:
                return type(action)(kind="check", amount=None)
            if state.checking_or_calling_amount > 0 and "fold" in available_kinds:
                return type(action)(kind="fold", amount=None)
        if action.kind == "call" and "check" in available_kinds:
            return type(action)(kind="check", amount=None)
        if action.kind == "check" and "call" in available_kinds and state.checking_or_calling_amount > 0:
            return type(action)(kind="call", amount=None)
        if action.kind == "fold":
            if "check" in available_kinds:
                return type(action)(kind="check", amount=None)
            if "call" in available_kinds:
                return type(action)(kind="check", amount=None)
        return action

    def _select_amount_button(self, target_amount: int) -> dict[str, Any] | None:
        if not self._hero_amount_buttons:
            return None

        best: dict[str, Any] | None = None
        best_distance: int | None = None
        for button in self._hero_amount_buttons:
            if str(button.get("button_kind", "")).strip().lower() != "shortcut":
                continue
            value = button.get("estimated_value")
            if value is None:
                continue
            try:
                value_int = int(value)
            except (TypeError, ValueError):
                continue
            distance = abs(value_int - target_amount)
            if best_distance is None or distance < best_distance:
                best = button
                best_distance = distance

        if best is not None:
            return best

        for button in self._hero_amount_buttons:
            label = _normalize_control_label(str(button.get("label", "")))
            if "plus" in label or label == "+":
                return button
        return self._hero_amount_buttons[0]

    def _clean_available_actions(self, table: TableBase) -> list[dict[str, Any]]:
        if not table.available_actions:
            return []

        def x_pos(button: dict[str, Any]) -> int:
            click_point = button.get("click_point") or {}
            button_rect = button.get("button_rect") or {}
            return int(click_point.get("x") or button_rect.get("left") or 0)

        raw_buttons = sorted((dict(button) for button in table.available_actions), key=x_pos)
        if not raw_buttons:
            return []

        max_center_y = max((_button_center_y(button) for button in raw_buttons), default=0.0)
        row_threshold = max_center_y - 35.0

        current_max_bet = max((self._player_bet(table, seat) for seat in self._active_players), default=0)
        hero_bet = self._player_bet(table, HERO_SEAT)
        visible_call_amount = self._visible_call_amount_units(table)
        call_amount = visible_call_amount if visible_call_amount is not None else max(0, current_max_bet - hero_bet)
        amount_value_text = (table.amount_value_text or "").strip()
        amount_value = _extract_amount_units(amount_value_text, self._money_scale)

        amount_shortcuts = 0
        for amount_button in table.amount_buttons:
            roi_label = str(amount_button.get("roi_label", "")).strip().lower()
            label = str(amount_button.get("label", "")).strip().lower()
            if roi_label != "select_amount_button":
                continue
            if label and label != "raise":
                amount_shortcuts += 1
                continue
            ocr_rect_area = int(amount_button.get("ocr_rect_area") or 0)
            if ocr_rect_area > 0:
                amount_shortcuts += 1

        raw_labels = [
            _normalize_control_label(str(button.get("label", "")))
            for button in raw_buttons
        ]
        max_height = max((_button_height(button) for button in raw_buttons), default=0)
        max_width = max((_button_width(button) for button in raw_buttons), default=0)
        only_two_small_buttons = len(raw_buttons) <= 2 and max_height <= 24 and max_width <= 130
        labels_look_like_preactions = (
            any("checkfold" in label for label in raw_labels)
            or (
                len(raw_labels) == 2
                and any("fold" in label for label in raw_labels)
                and any("chiama" in label or "call" in label or label == "check" for label in raw_labels)
            )
        )
        labels_look_like_meta_controls = any(
            label.startswith("tornaagiocare") or label.startswith("rientra") or label.startswith("sitout")
            for label in raw_labels
        )
        has_real_raise_panel = bool(amount_value_text) or amount_shortcuts >= 2
        has_red_action_area = self._has_red_action_area(table)
        if labels_look_like_meta_controls and not has_real_raise_panel and not has_red_action_area:
            return []
        if (
            not has_real_raise_panel
            and not has_red_action_area
            and len(raw_buttons) <= 2
            and raw_labels
            and all(
                ("fold" in label)
                or ("check" in label)
                or ("call" in label)
                or ("chiama" in label)
                or ("passa" in label)
                for label in raw_labels
            )
        ):
            return []
        if only_two_small_buttons and labels_look_like_preactions and not has_real_raise_panel and not has_red_action_area:
            return []

        cleaned: list[dict[str, Any]] = []
        for index, button in enumerate(raw_buttons):
            if _button_center_y(button) < row_threshold:
                continue
            raw_label = _sanitize_action_button_label(str(button.get("label", "")).strip())
            normalized = _normalize_control_label(raw_label)
            if not normalized:
                continue
            cleaned_button = dict(button)
            cleaned_button["raw_label"] = raw_label

            action_kind = ""
            label = raw_label or "-"
            if "fold" in normalized or "passa" in normalized:
                action_kind = "fold"
                label = "Fold"
            elif "chiama" in normalized or "call" in normalized:
                action_kind = "call"
                label = f"Chiama {self._format_amount(call_amount)}" if call_amount > 0 else "Check"
            elif "check" in normalized:
                action_kind = "check"
                label = "Check"
            elif "rilancia" in normalized or "raise" in normalized or "punta" in normalized or "bet" in normalized:
                action_kind = "raise"
                label = f"Rilancia {self._format_amount(amount_value)}" if amount_value else "Rilancia"

            if not action_kind:
                if call_amount > 0:
                    if index == 0:
                        action_kind = "fold"
                        label = "Fold"
                    elif index == 1:
                        action_kind = "call"
                        label = f"Chiama {self._format_amount(call_amount)}"
                    elif index == 2:
                        action_kind = "raise"
                        label = f"Rilancia {self._format_amount(amount_value)}" if amount_value else "Rilancia"
                else:
                    if index == 0:
                        action_kind = "check"
                        label = "Check/Fold"
                    elif index == 1:
                        action_kind = "check"
                        label = "Check"
                    elif index == 2:
                        action_kind = "raise"
                        label = f"Rilancia {self._format_amount(amount_value)}" if amount_value else "Rilancia"

            if not action_kind:
                continue

            cleaned_button["label"] = label
            cleaned_button["action_kind"] = action_kind
            cleaned.append(cleaned_button)

        deduped: list[dict[str, Any]] = []
        seen_kinds: set[str] = set()
        for button in cleaned:
            action_kind = str(button.get("action_kind", ""))
            if action_kind in seen_kinds:
                if action_kind == "check":
                    current_label = str(button.get("label", "")).strip().lower()
                    if current_label == "check" and all(
                        str(existing.get("action_kind", "")) != "check" or str(existing.get("label", "")).strip().lower() != "check"
                        for existing in deduped
                    ):
                        deduped.append(button)
                continue
            deduped.append(button)
            seen_kinds.add(action_kind)

        action_kinds = {str(button.get("action_kind", "")) for button in deduped}
        if not action_kinds:
            return []
        if call_amount <= 0 and action_kinds.issubset({"fold", "check"}):
            return []
        if not has_real_raise_panel and call_amount <= 0 and action_kinds.issubset({"fold", "check"}):
            return []
        if action_kinds == {"fold"}:
            return []
        if call_amount > 0 and action_kinds == {"fold"}:
            return []

        return deduped

    def _clean_amount_buttons(self, table: TableBase) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        pot_amount = self._pot_amount_units(table)
        bb_amount = self._bb_amount_units(table)
        current_max_bet = max((self._player_bet(table, seat) for seat in self._active_players), default=0)
        hero_bet = self._player_bet(table, HERO_SEAT)
        visible_call_amount = self._visible_call_amount_units(table)
        min_raise_to = current_max_bet + bb_amount if current_max_bet > 0 else max(bb_amount * 2, bb_amount + hero_bet)
        if visible_call_amount is not None:
            min_raise_to = hero_bet + visible_call_amount + bb_amount
        max_raise_to = hero_bet + self._player_stack(table, HERO_SEAT)

        for button in table.amount_buttons:
            cleaned_button = dict(button)
            roi_label = str(button.get("roi_label", "")).strip().lower()
            cleaned_button["raw_label"] = str(button.get("label", "")).strip()

            if roi_label == "select_amount_button":
                cleaned_button["button_kind"] = "shortcut"
                cleaned_button["estimated_value"] = _estimate_shortcut_value(
                    cleaned_button["raw_label"],
                    pot_amount=pot_amount,
                    min_raise_to=min_raise_to,
                    max_raise_to=max_raise_to,
                    bb_amount=bb_amount,
                    scale=self._money_scale,
                )
                cleaned_button["label"] = cleaned_button["raw_label"] or "preset"
            elif roi_label == "select_amount_plus":
                cleaned_button["label"] = "+"
                cleaned_button["button_kind"] = "increase"
            elif roi_label == "select_amount_minus":
                cleaned_button["label"] = "-"
                cleaned_button["button_kind"] = "decrease"
            else:
                cleaned_button["button_kind"] = "other"

            cleaned.append(cleaned_button)

        return cleaned
