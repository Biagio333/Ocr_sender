from pokerkit import Automation, NoLimitTexasHoldem
from collections import Counter
import random

from bot.bot_biagio.bot_biagio import BotBiagio, build_stats_context as build_biagio_stats_context
from bot.manual_bot.manual_bot import ManualBot, build_stats_context as build_manual_stats_context
from bot.negreanu_bot.negreanu_bot import BotNegreanu, build_stats_context as build_negreanu_stats_context
from bot.negreanu_bot_V2.negreanu_bot_V2 import BotNegreanu_V2 as BotNegreanuV2, build_stats_context as build_negreanu_v2_stats_context
from bot.sng_bot.sng_bot import SmartParametricBot, build_stats_context as build_sng_stats_context

from utils.utils import (
    build_performance_report,
    build_positions_map,
    build_tournament_bots,
    describe_hand,
    format_cards,
    get_blind_level,
    PLAYER_RESPONSE_TIME_SECONDS,
    street_name,
)

import bot.BotAction as BotAction


Debug_hand = False


AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HOLE_DEALING,
    Automation.BOARD_DEALING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)


DEFAULT_INTERACTIVE_MODE = False
DEFAULT_STEP_BY_STEP = False 
DEFAULT_TOURNAMENTS_TO_RUN = 100



class PokerTournament:
    TABLE_COLUMNS = (
        ("Seat", 4),
        ("Bot", 28),
        ("Pos", 3),
        ("Stack", 5),
        ("Cards", 5),
        ("Hand", 14),
        ("Actions", 31),
        ("Status", 14),
    )

    def __init__(self, interactive_mode: bool = False, step_by_step: bool = False):
        self.interactive_mode = interactive_mode
        self.step_by_step = step_by_step
        self.bots = build_tournament_bots()

        self.initial_stacks = [3000] * len(self.bots)
        self.initial_small_blind = 1
        self.initial_big_blind = 2
        self.initial_ante = 0

        if len(self.bots) != len(self.initial_stacks):
            raise ValueError("Il numero di bot deve corrispondere al numero di stack iniziali.")

        self.initial_bots = self.bots.copy()
        self.winner_names = []
        self.runner_up_names = []
        self.total_profit_by_name = Counter()
        self.total_profit_sq_by_name = Counter()
        self.tournament_id = 0
        self.reset_tournament()

    def _wait_for_user(self, message: str = "Premi Invio per continuare..."):
        if self.step_by_step:
            input(message)

    def _clip_cell(self, value, width):
        text = str(value)
        if len(text) <= width:
            return text
        if width <= 1:
            return text[:width]
        return text[: width - 1] + "."

    def _table_separator(self):
        return "+" + "+".join("-" * (width + 2) for _, width in self.TABLE_COLUMNS) + "+"

    def _table_header(self):
        header_cells = [
            f" {label:<{width}} "
            for label, width in self.TABLE_COLUMNS
        ]
        return "|" + "|".join(header_cells) + "|"

    def _format_seat_line(
        self,
        state,
        local_index,
        global_index,
        positions_map,
        active_in_hand_locals,
        player_street_last_action=None,
    ):
        bot = self.bots[global_index]
        position = positions_map.get(global_index, "-")
        cards = format_cards(state.hole_cards[local_index])
        hand_label = describe_hand(state, local_index)
        stack = state.stacks[local_index]
        status = []

        if local_index == state.actor_index:
            status.append("ACT")
        if local_index in active_in_hand_locals:
            status.append("IN_HAND")
        else:
            status.append("FOLDED")
        if stack <= 0:
            status.append("ALL_IN/OUT")

        street_action_text = "P:- F:- T:- R:-"
        if player_street_last_action is not None:
            street_actions = player_street_last_action.get(local_index, {})
            street_action_text = (
                f"P:{street_actions.get('preflop', '-'):>5} "
                f"F:{street_actions.get('flop', '-'):>5} "
                f"T:{street_actions.get('turn', '-'):>5} "
                f"R:{street_actions.get('river', '-'):>5}"
            )

        cells = [
            f" {global_index:>{self.TABLE_COLUMNS[0][1]}} ",
            f" {self._clip_cell(bot.name, self.TABLE_COLUMNS[1][1]):<{self.TABLE_COLUMNS[1][1]}} ",
            f" {self._clip_cell(position, self.TABLE_COLUMNS[2][1]):<{self.TABLE_COLUMNS[2][1]}} ",
            f" {stack:>{self.TABLE_COLUMNS[3][1]}} ",
            f" {self._clip_cell(cards or '-', self.TABLE_COLUMNS[4][1]):<{self.TABLE_COLUMNS[4][1]}} ",
            f" {self._clip_cell(hand_label or '-', self.TABLE_COLUMNS[5][1]):<{self.TABLE_COLUMNS[5][1]}} ",
            f" {self._clip_cell(street_action_text, self.TABLE_COLUMNS[6][1]):<{self.TABLE_COLUMNS[6][1]}} ",
            f" {self._clip_cell(' '.join(status), self.TABLE_COLUMNS[7][1]):<{self.TABLE_COLUMNS[7][1]}} ",
        ]
        return "|" + "|".join(cells) + "|"

    def _format_action_label(self, action, call_amount_before_action):
        if action.kind == "raise":
            return f"raise {action.amount}"
        if action.kind == "call":
            return "check" if call_amount_before_action == 0 else f"call {call_amount_before_action}"
        if action.kind == "check":
            return "check"
        return action.kind

    def _print_recent_actions(self, action_log, limit=12):
        print("-" * 80)
        print("Action log")
        if not action_log:
            print("  - nessuna azione ancora")
            return
        for action_line in action_log[-limit:]:
            print(f"  - {action_line}")

    def _print_table_snapshot(
        self,
        state,
        local_to_global,
        positions_map,
        active_in_hand_locals,
        title,
        player_street_last_action=None,
        action_log=None,
    ):
        table_separator = self._table_separator()
        print("\n" + "=" * len(table_separator))
        print(title)
        print(f"Hand         : {self.hand_no}")
        print(f"Street       : {street_name(state)}")
        print(f"Board        : {format_cards(state.board_cards) or '-'}")
        print(f"Pot          : {state.total_pot_amount}")
        print(f"Call amount  : {state.checking_or_calling_amount}")
        print(f"Min raise to : {state.min_completion_betting_or_raising_to_amount}")
        print(f"Max raise to : {state.max_completion_betting_or_raising_to_amount}")
        print(f"Button global: {self.button_global_index}")
        print(f"Blind        : SB={self.small_blind} BB={self.big_blind} Ante={self.ante}")
        print(table_separator)
        print(self._table_header())
        print(table_separator)
        for local_index, global_index in enumerate(local_to_global):
            print(
                self._format_seat_line(
                    state,
                    local_index,
                    global_index,
                    positions_map,
                    active_in_hand_locals,
                    player_street_last_action=player_street_last_action,
                )
            )
        print(table_separator)
        self._print_recent_actions(action_log or [])
        print("=" * len(table_separator))

    def _print_action_summary(self, state, actor_local, actor_global, positions_map, action):
        bot = self.bots[actor_global]
        if action.kind == "call":
            call_amount = state.checking_or_calling_amount or 0
            action_text = "check" if call_amount == 0 else f"call {call_amount}"
        elif action.kind == "raise":
            action_text = f"raise a {action.amount}"
        else:
            action_text = action.kind
        print(
            f"Azione -> {bot.name} "
            f"(seat {actor_global}, pos {positions_map.get(actor_global, '-')}) "
            f"fa {action_text}"
        )

    def _print_hand_result(self, state, local_to_global, previous_stacks):
        print("\n" + "=" * 80)
        print(f"HAND {self.hand_no} FINITA")
        print(f"Board finale : {format_cards(state.board_cards) or '-'}")
        print(f"Stacks finali: {self.stacks}")

        busted_players = [
            i for i, (before, after) in enumerate(zip(previous_stacks, self.stacks))
            if before > 0 and after == 0
        ]
        if busted_players:
            print("Eliminati    :")
            for player_index in busted_players:
                print(f"  - seat {player_index} | {self.bots[player_index].name}")
        else:
            print("Eliminati    : nessuno")
        print("=" * 80)

    def reset_tournament(self):
        self.bots = self.initial_bots.copy()
        random.shuffle(self.bots)
        self.stacks = self.initial_stacks.copy()
        self.hand_no = 0
        self.small_blind = self.initial_small_blind
        self.big_blind = self.initial_big_blind
        self.ante = self.initial_ante
        self.elimination_order = []
        self.elapsed_tournament_seconds = 0.0

        # Seat del bottone sui 6 seat originali
        self.button_global_index = -1

    def _apply_action(self, state, action: BotAction):
        if action.kind == "fold":
            call_amount = state.checking_or_calling_amount or 0
            if call_amount <= 0 and state.can_check_or_call():
                state.check_or_call()
            else:
                state.fold()
            return

        if action.kind in {"call", "check"}:
            state.check_or_call()
            return

        if action.kind == "raise":
            if action.amount is None:
                state.check_or_call()
                return

            min_raise_to = state.min_completion_betting_or_raising_to_amount
            max_raise_to = state.max_completion_betting_or_raising_to_amount

            # Se non posso rilanciare, faccio call/check
            if min_raise_to is None or max_raise_to is None:
                state.check_or_call()
                return

            # Clamp dell'importo nel range valido
            amount = max(min_raise_to, min(action.amount, max_raise_to))
            state.complete_bet_or_raise_to(amount)
            return

        raise ValueError(f"Azione sconosciuta: {action.kind}")


    def _print_header(self, state, active_players):
        print("-" * 80)
        print(f"Hand         : {self.hand_no}")
        print(f"Street       : {street_name(state)}")
        print(f"Board        : {[str(c) for c in state.board_cards]}")
        print(f"Pot          : {state.total_pot_amount}")
        print(f"Local stacks : {list(state.stacks)}")
        print(f"Global stacks: {self.stacks}")
        print(f"Actor local  : {state.actor_index}")
        print(f"Active seats : {active_players}")
        print(f"Button global: {self.button_global_index}")
        print(f"Blind        : SB={self.small_blind} BB={self.big_blind} Ante={self.ante}")
        print("-" * 80)

    def _blind_level_update(self):
        self.small_blind, self.big_blind = get_blind_level(self.elapsed_tournament_seconds)

    def _active_players(self):
        return [i for i, stack in enumerate(self.stacks) if stack > 0]

    def _next_active_seat(self, start_seat, active_players):
        if not active_players:
            return None

        seat = start_seat
        for _ in range(len(self.stacks)):
            seat = (seat + 1) % len(self.stacks)
            if seat in active_players:
                return seat
        return None

    def _record_stack_snapshots(self):
        players_remaining = sum(1 for stack in self.stacks if stack > 0)
        for player_index, bot in enumerate(self.bots):
            bot.stats_tracker.record_stack_snapshot(
                tournament_id=self.tournament_id,
                hand_no=self.hand_no,
                stack=self.stacks[player_index],
                big_blind=self.big_blind,
                players_remaining=players_remaining,
            )

    def _advance_button(self, active_players):
        if len(active_players) <= 1:
            return

        if self.button_global_index not in active_players:
            self.button_global_index = active_players[0]
        else:
            nxt = self._next_active_seat(self.button_global_index, active_players)
            if nxt is not None:
                self.button_global_index = nxt

    def _order_active_players_for_hand(self, active_players):
        if not active_players:
            return []

        if self.button_global_index not in active_players:
            return active_players[:]

        button_idx = active_players.index(self.button_global_index)

        # PokerKit expects seats ordered by blind/action flow.
        # In heads-up the button is also the small blind, so it stays first.
        if len(active_players) == 2:
            return active_players[button_idx:] + active_players[:button_idx]

        small_blind_idx = (button_idx + 1) % len(active_players)
        return active_players[small_blind_idx:] + active_players[:small_blind_idx]

    def play_one_hand(self):
        active_players = self._active_players()
        if len(active_players) <= 1:
            return

        previous_stacks = self.stacks.copy()
        self.hand_no += 1
        self._blind_level_update()
        self._advance_button(active_players)

        # tavolo locale solo con i giocatori vivi
        local_to_global = self._order_active_players_for_hand(active_players)
        global_to_local = {g: i for i, g in enumerate(local_to_global)}
        local_stacks = tuple(self.stacks[g] for g in local_to_global)
        positions_map = build_positions_map(local_to_global, self.button_global_index)

        state = NoLimitTexasHoldem.create_state(
            AUTOMATIONS,
            True,
            self.ante,
            (self.small_blind, self.big_blind),
            self.big_blind,
            local_stacks,
            len(local_to_global),
        )

        if Debug_hand:
            print(f"\n=== START HAND {self.hand_no} ===")
            self._print_header(state, local_to_global)

        player_street_last_action = {
            local_index: {
                "preflop": "-",
                "flop": "-",
                "turn": "-",
                "river": "-",
            }
            for local_index in range(len(local_to_global))
        }
        action_log = []

        if self.interactive_mode:
            self._print_table_snapshot(
                state,
                local_to_global,
                positions_map,
                active_in_hand_locals=set(range(len(local_to_global))),
                title=f"INIZIO HAND {self.hand_no}",
                player_street_last_action=player_street_last_action,
                action_log=action_log,
            )
            self._wait_for_user()

        last_board_len = len(state.board_cards)
        active_in_hand_locals = set(range(len(local_to_global)))
        street_raise_count = {
            "preflop": 0,
            "flop": 0,
            "turn": 0,
            "river": 0,
        }
        player_street_actions = {
            local_index: {
                street_name_key: Counter()
                for street_name_key in street_raise_count
            }
            for local_index in range(len(local_to_global))
        }
        player_last_action = {
            local_index: {"kind": "", "street": ""}
            for local_index in range(len(local_to_global))
        }
        preflop_aggressor_local = None
        current_street_aggressor_local = None
        preflop_limpers = set()
        last_action_local = None
        last_action_kind = ""
        last_action_street = ""
        cbet_candidate_local = None
        cbet_made = False

        for local_index, global_index in enumerate(local_to_global):
            bot = self.bots[global_index]
            position = positions_map.get(global_index, "")
            stack_bb = self.stacks[global_index] / max(self.big_blind, 1)
            bot.start_stats_hand(
                hand_id=self.hand_no,
                position=position,
                stack_bb=stack_bb,
                players_in_hand=len(local_to_global),
            )

        while state.status:
            actor_local = state.actor_index
            if actor_local is None:
                break

            current_board_len = len(state.board_cards)
            if current_board_len != last_board_len:
                last_board_len = current_board_len
                current_street_aggressor_local = None
                if current_board_len == 3:
                    for local_index in list(active_in_hand_locals):
                        actor_global_index = local_to_global[local_index]
                        self.bots[actor_global_index].note_stats_saw_flop()
                    if (
                        preflop_aggressor_local is not None
                        and preflop_aggressor_local in active_in_hand_locals
                        and len(active_in_hand_locals) > 1
                    ):
                        cbet_candidate_local = preflop_aggressor_local
                    street_raise_count["flop"] = 0
                elif current_board_len == 4:
                    street_raise_count["turn"] = 0
                elif current_board_len == 5:
                    street_raise_count["river"] = 0
                if Debug_hand :
                    self._print_header(state, local_to_global)
                if self.interactive_mode:
                    self._print_table_snapshot(
                        state,
                        local_to_global,
                        positions_map,
                        active_in_hand_locals,
                        title=f"NUOVA STREET: {street_name(state).upper()}",
                        player_street_last_action=player_street_last_action,
                        action_log=action_log,
                    )
                    self._wait_for_user()

            # protezione
            if actor_local < 0 or actor_local >= len(local_to_global):
                break

            if state.stacks[actor_local] <= 0:
                # Un giocatore puo' essere all-in a stack zero: lasciamo avanzare
                # PokerKit fino alla chiusura naturale della mano e al push del pot.
                if state.can_check_or_call():
                    state.check_or_call()
                    continue
                break

            actor_global = local_to_global[actor_local]
            bot = self.bots[actor_global]
            street = street_name(state)
            players_acted_this_street = sum(
                1
                for local_index in active_in_hand_locals
                if player_street_actions[local_index][street].get("total", 0) > 0
            )
            players_yet_to_act = sum(
                1
                for local_index in active_in_hand_locals
                if local_index != actor_local and player_street_actions[local_index][street].get("total", 0) == 0
            )
            opponent_stats = []
            for local_index in active_in_hand_locals:
                if local_index == actor_local:
                    continue
                snapshot = self.bots[local_to_global[local_index]].get_stats_snapshot().copy()
                snapshot.update({
                    "seat": local_to_global[local_index],
                    "position": positions_map.get(local_to_global[local_index], ""),
                    "last_action_kind": player_last_action[local_index]["kind"],
                    "last_action_street": player_last_action[local_index]["street"],
                    "was_preflop_aggressor": preflop_aggressor_local == local_index,
                    "is_current_aggressor": current_street_aggressor_local == local_index,
                    "street_actions_total": player_street_actions[local_index][street].get("total", 0),
                    "street_checks": player_street_actions[local_index][street].get("check", 0),
                    "street_calls": player_street_actions[local_index][street].get("call", 0),
                    "street_raises": player_street_actions[local_index][street].get("raise", 0),
                    "street_folds": player_street_actions[local_index][street].get("fold", 0),
                })
                opponent_stats.append(snapshot)

            is_cbet_opportunity = (
                street == "flop"
                and cbet_candidate_local == actor_local
                and not cbet_made
                and street_raise_count["flop"] == 0
            )
            is_facing_cbet = (
                street == "flop"
                and cbet_made
                and actor_local in active_in_hand_locals
                and actor_local != cbet_candidate_local
            )
            call_amount_before_action = state.checking_or_calling_amount or 0
            hero_stack_bb = self.stacks[actor_global] / max(self.big_blind, 1)
            opponent_stack_bbs = [
                snapshot.get("stack_bb", 0.0)
                for snapshot in opponent_stats
                if snapshot.get("stack_bb", 0.0) > 0
            ]
            effective_stack_bb = min([hero_stack_bb, *opponent_stack_bbs]) if opponent_stack_bbs else hero_stack_bb
            last_actor_stats = None
            if last_action_local is not None and last_action_local != actor_local:
                last_actor_global = local_to_global[last_action_local]
                last_actor_stats = self.bots[last_actor_global].get_stats_snapshot().copy()
                last_actor_stats.update({
                    "seat": last_actor_global,
                    "position": positions_map.get(last_actor_global, ""),
                    "last_action_kind": last_action_kind,
                    "last_action_street": last_action_street,
                })
            current_street_aggressor_position = (
                positions_map.get(local_to_global[current_street_aggressor_local], "")
                if current_street_aggressor_local is not None
                else ""
            )
            preflop_aggressor_position = (
                positions_map.get(local_to_global[preflop_aggressor_local], "")
                if preflop_aggressor_local is not None
                else ""
            )

            if isinstance(bot, BotBiagio):
                stats_context = build_biagio_stats_context(
                    street=street,
                    call_amount=call_amount_before_action,
                    raise_count_before_action=street_raise_count.get(street, 0),
                    position=positions_map.get(actor_global, ""),
                    players_in_hand=len(active_in_hand_locals),
                    opponents=opponent_stats,
                    is_cbet_opportunity=is_cbet_opportunity,
                    is_facing_cbet=is_facing_cbet,
                    big_blind=self.big_blind,
                    pot=state.total_pot_amount,
                    hero_stack_bb=hero_stack_bb,
                    effective_stack_bb=effective_stack_bb,
                )
            elif isinstance(bot, ManualBot):
                stats_context = build_manual_stats_context(
                    street=street,
                    call_amount=call_amount_before_action,
                    raise_count_before_action=street_raise_count.get(street, 0),
                    position=positions_map.get(actor_global, ""),
                    players_in_hand=len(active_in_hand_locals),
                    opponents=opponent_stats,
                    is_cbet_opportunity=is_cbet_opportunity,
                    is_facing_cbet=is_facing_cbet,
                    big_blind=self.big_blind,
                    pot=state.total_pot_amount,
                    hero_stack_bb=hero_stack_bb,
                    effective_stack_bb=effective_stack_bb,
                )
            elif isinstance(bot, (BotNegreanu, BotNegreanuV2)):
                build_context = (
                    build_negreanu_v2_stats_context
                    if isinstance(bot, BotNegreanuV2)
                    else build_negreanu_stats_context
                )
                stats_context = build_context(
                    street=street,
                    call_amount=call_amount_before_action,
                    raise_count_before_action=street_raise_count.get(street, 0),
                    position=positions_map.get(actor_global, ""),
                    players_in_hand=len(active_in_hand_locals),
                    opponents=opponent_stats,
                    is_cbet_opportunity=is_cbet_opportunity,
                    is_facing_cbet=is_facing_cbet,
                    big_blind=self.big_blind,
                    pot=state.total_pot_amount,
                    hero_stack_bb=hero_stack_bb,
                    effective_stack_bb=effective_stack_bb,
                    limper_count=len(preflop_limpers),
                    is_limped_pot=street == "preflop" and street_raise_count["preflop"] == 0 and bool(preflop_limpers),
                    pot_was_limped_preflop=street != "preflop" and preflop_aggressor_local is None and bool(preflop_limpers),
                    players_acted_this_street=players_acted_this_street,
                    players_yet_to_act=players_yet_to_act,
                    current_street_aggressor_position=current_street_aggressor_position,
                    preflop_aggressor_position=preflop_aggressor_position,
                    hero_has_initiative=street != "preflop" and preflop_aggressor_local == actor_local,
                    hero_is_preflop_aggressor=preflop_aggressor_local == actor_local,
                    hero_is_current_street_aggressor=current_street_aggressor_local == actor_local,
                    last_action_kind=last_action_kind,
                    last_action_street=last_action_street,
                    last_action_position=(
                        positions_map.get(local_to_global[last_action_local], "")
                        if last_action_local is not None
                        else ""
                    ),
                    last_actor_stats=last_actor_stats,
                )
            else:
                stats_context = build_sng_stats_context(
                    street=street,
                    call_amount=call_amount_before_action,
                    raise_count_before_action=street_raise_count.get(street, 0),
                    position=positions_map.get(actor_global, ""),
                    players_in_hand=len(active_in_hand_locals),
                    opponents=opponent_stats,
                    is_cbet_opportunity=is_cbet_opportunity,
                    is_facing_cbet=is_facing_cbet,
                )
            action = bot.act(state, actor_local, stats_context=stats_context)
            self.elapsed_tournament_seconds += PLAYER_RESPONSE_TIME_SECONDS

            if Debug_hand :
                print(
                    f"{bot.name} | "
                    f"global={actor_global} local={actor_local} | "
                    f"hole={[str(c) for c in state.hole_cards[actor_local]]} | "
                    f"call={state.checking_or_calling_amount} | "
                    f"min_raise={state.min_completion_betting_or_raising_to_amount} | "
                    f"max_raise={state.max_completion_betting_or_raising_to_amount} | "
                    f"action={action}"
                )
            if self.interactive_mode:
                self._print_table_snapshot(
                    state,
                    local_to_global,
                    positions_map,
                    active_in_hand_locals,
                    title="SITUAZIONE PRIMA DELL'AZIONE",
                    player_street_last_action=player_street_last_action,
                    action_log=action_log,
                )
                self._print_action_summary(state, actor_local, actor_global, positions_map, action)
                self._wait_for_user("Premi Invio per eseguire l'azione...")

            if street == "preflop" and action.kind == "raise":
                preflop_aggressor_local = actor_local

            if is_cbet_opportunity and action.kind == "raise":
                cbet_made = True

            normalized_action_kind = "check" if action.kind == "call" and call_amount_before_action == 0 else action.kind

            self._apply_action(state, action)

            player_street_actions[actor_local][street]["total"] += 1
            player_street_actions[actor_local][street][normalized_action_kind] += 1
            if normalized_action_kind != action.kind:
                player_street_actions[actor_local][street][action.kind] += 1
            player_last_action[actor_local] = {
                "kind": normalized_action_kind,
                "street": street,
            }
            player_street_last_action[actor_local][street] = normalized_action_kind
            last_action_local = actor_local
            last_action_kind = normalized_action_kind
            last_action_street = street
            action_log.append(
                f"{street.upper():<7} | "
                f"{bot.name} (seat {actor_global}, {positions_map.get(actor_global, '-')}, "
                f"cards {format_cards(state.hole_cards[actor_local]) or '-'}) -> "
                f"{self._format_action_label(action, call_amount_before_action)}"
            )

            if (
                street == "preflop"
                and normalized_action_kind == "call"
                and street_raise_count["preflop"] == 0
                and call_amount_before_action > 0
            ):
                preflop_limpers.add(actor_local)

            if action.kind == "raise":
                street_raise_count[street] = street_raise_count.get(street, 0) + 1
                current_street_aggressor_local = actor_local

            if action.kind == "fold":
                active_in_hand_locals.discard(actor_local)

            if self.interactive_mode:
                self._print_table_snapshot(
                    state,
                    local_to_global,
                    positions_map,
                    active_in_hand_locals,
                    title="SITUAZIONE DOPO L'AZIONE",
                    player_street_last_action=player_street_last_action,
                    action_log=action_log,
                )
                self._print_action_summary(state, actor_local, actor_global, positions_map, action)
                self._wait_for_user()

        # aggiorno gli stack globali dai locali
        for local_index, global_index in enumerate(local_to_global):
            self.stacks[global_index] = state.stacks[local_index]

        # chi è busto resta a zero
        for i in range(len(self.stacks)):
            if self.stacks[i] < 0:
                self.stacks[i] = 0

        busted_players = [
            i for i, (before, after) in enumerate(zip(previous_stacks, self.stacks))
            if before > 0 and after == 0
        ]
        self.elimination_order.extend(busted_players)

        if len(state.board_cards) == 5 and len(active_in_hand_locals) > 1:
            for local_index in active_in_hand_locals:
                global_index = local_to_global[local_index]
                self.bots[global_index].note_stats_showdown()

        if Debug_hand :
            print("=" * 80)
            print(f"HAND {self.hand_no} FINISHED")
            print("Board finale :", [str(c) for c in state.board_cards])
            print("Local stacks :", list(state.stacks))
            print("Global stacks:", self.stacks)
            print("Statuses     :", state.statuses)
            print("=" * 80)

        if self.interactive_mode:
            self._print_hand_result(state, local_to_global, previous_stacks)
            self._wait_for_user("Premi Invio per andare alla hand successiva...")

    def run_tournament(self):
        self.tournament_id += 1
        self._record_stack_snapshots()

        while sum(1 for s in self.stacks if s > 0) > 1:
            self.play_one_hand()
            self._record_stack_snapshots()

        profits = [
            self.stacks[i] - self.initial_stacks[i]
            for i in range(len(self.stacks))
        ]

        print("\n" + "#" * 80)
        print("TORNEO FINITO")
        for i, stack in enumerate(self.stacks):
            profit = profits[i]
            print(f"{self.bots[i].name}: {stack} ({profit:+d})")
        active_players = [i for i, stack in enumerate(self.stacks) if stack > 0]
        winner = active_players[0] if active_players else max(range(len(self.stacks)), key=lambda i: self.stacks[i])
        runner_up = self.elimination_order[-1] if self.elimination_order else None
        top_gainer = max(range(len(profits)), key=lambda i: profits[i])

        self.winner_names.append(self.bots[winner].name)
        if runner_up is not None:
            self.runner_up_names.append(self.bots[runner_up].name)
        for i, bot in enumerate(self.bots):
            self.total_profit_by_name[bot.name] += profits[i]
            self.total_profit_sq_by_name[bot.name] += profits[i] ** 2

        for bot in self.bots:
            bot.stats_tracker.save_to_db()

        print(f"Top profitto torneo: {self.bots[top_gainer].name} ({profits[top_gainer]:+d})")

        if Debug_hand :
            print("Vincitore:", self.bots[winner].name)
            if runner_up is not None:
                print("Secondo  :", self.bots[runner_up].name)
            print("\nSTATISTICHE BOT")
            for bot in self.bots:
                stats = bot.get_stats_snapshot()
                print(
                    f"{bot.name}: "
                    f"vpip={stats['vpip']:.4f} "
                    f"pfr={stats['pfr']:.4f} "
                    f"af={stats['af']:.4f} "
                    f"fold_to_raise={stats['fold_to_raise']:.4f} "
                    f"fold_to_cbet={stats['fold_to_cbet']:.4f} "
                    f"cbet={stats['cbet']:.4f} "
                    f"3bet={stats['3bet']:.4f} "
                    f"fold_to_3bet={stats['fold_to_3bet']:.4f} "
                    f"wtsd={stats['wtsd']:.4f} "
                    f"position={stats['position']} "
                    f"stack_bb={stats['stack_bb']:.2f} "
                    f"players_in_hand={stats['players_in_hand']}"
                )
            print("#" * 80)


PokerTournament6Max = PokerTournament


if __name__ == "__main__":
    table = PokerTournament(
        interactive_mode=DEFAULT_INTERACTIVE_MODE,
        step_by_step=DEFAULT_STEP_BY_STEP,
    )
    for a in range(DEFAULT_TOURNAMENTS_TO_RUN):
        table.run_tournament()
        if a < DEFAULT_TOURNAMENTS_TO_RUN - 1:
            table.reset_tournament()

    if DEFAULT_TOURNAMENTS_TO_RUN > 1:
        winner_prizes = Counter({
            name: count * 3.27
            for name, count in Counter(table.winner_names).items()
        })
        runner_up_prizes = Counter({
            name: count * 1.76
            for name, count in Counter(table.runner_up_names).items()
        })
        total_prizes = winner_prizes + runner_up_prizes

        print("\n" + "#" * 80)
        print("RIEPILOGO VINCITORI")
        for name, prize in winner_prizes.most_common():
            print(f"{name}: {prize:.2f}")
        print("\nRIEPILOGO SECONDI POSTI")
        for name, prize in runner_up_prizes.most_common():
            print(f"{name}: {prize:.2f}")
        print("\nRIEPILOGO GUADAGNI TOTALI")
        for name, total in total_prizes.most_common():
            print(f"{name}: {total:.2f}")

        performance_rows = build_performance_report(
            bot_names=[bot.name for bot in table.initial_bots],
            winner_names=table.winner_names,
            runner_up_names=table.runner_up_names,
            total_profit_by_name=table.total_profit_by_name,
            total_profit_sq_by_name=table.total_profit_sq_by_name,
            tournaments_played=table.tournament_id,
        )

        print("\nREPORT PERFORMANCE")
        for row in performance_rows:
            print(
                f"{row['name']:<18} | "
                f"win={row['win_rate']:.1%} | "
                f"itm={row['itm_rate']:.1%} | "
                f"avg={row['avg_profit']:+.2f} | "
                f"std={row['profit_stddev']:.2f} | "
                f"total={row['total_profit']:+.2f}"
            )
        print("#" * 80)
