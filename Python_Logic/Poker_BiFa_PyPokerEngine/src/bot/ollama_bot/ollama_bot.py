from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Optional
from urllib import error, request

from bot.BotAction import BotAction
from bot.negreanu_bot_V2.negreanu_bot_V2 import BotNegreanu_V2
from config import IS_TOURNEI


ACTION_ALIASES = {
    "fold": "fold",
    "pass": "fold",
    "muck": "fold",
    "check": "check",
    "call": "call",
    "raise": "raise",
    "bet": "raise",
    "all-in": "raise",
    "allin": "raise",
}


@dataclass
class OllamaBotConfig:
    model_name: str = "llama3.1:8b"
    base_url: str = "http://127.0.0.1:11434"
    timeout_sec: float = 8.0
    style_name: str = "balanced_reg"
    game_type: str = "cash"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_action(value: Any) -> Optional[str]:
    key = str(value or "").strip().lower()
    return ACTION_ALIASES.get(key)


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_stats_context(**kwargs) -> Dict[str, Any]:
    return dict(kwargs)


def _card_rank(card: Any) -> str:
    text = str(card or "").strip().upper()
    if len(text) < 2:
        return ""
    rank = text[:-1]
    if rank == "10":
        rank = "T"
    return rank


def _is_premium_preflop(cards: list[Any]) -> bool:
    if len(cards) != 2:
        return False
    left = _card_rank(cards[0])
    right = _card_rank(cards[1])
    if not left or not right:
        return False
    if left == right and left in {"A", "K", "Q", "J"}:
        return True
    ranks = {left, right}
    return ranks == {"A", "K"}


class BotOllama:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        timeout_sec: float = 8.0,
        style_name: str = "balanced_reg",
    ):
        self.config = OllamaBotConfig(
            model_name=model_name,
            base_url=base_url.rstrip("/"),
            timeout_sec=max(1.0, float(timeout_sec or 8.0)),
            style_name=style_name or "balanced_reg",
            game_type="tournament" if IS_TOURNEI else "cash",
        )
        self.fallback_bot = BotNegreanu_V2(profile_name=self.config.style_name)
        self.name = f"ollama_{self.config.style_name}"
        self.stats_tracker = self.fallback_bot.stats_tracker

    def start_stats_hand(
        self,
        hand_id: int,
        position: str,
        stack_bb: float,
        players_in_hand: int,
    ) -> None:
        self.fallback_bot.start_stats_hand(hand_id, position, stack_bb, players_in_hand)

    def note_stats_saw_flop(self) -> None:
        self.fallback_bot.note_stats_saw_flop()

    def note_stats_showdown(self) -> None:
        self.fallback_bot.note_stats_showdown()

    def get_stats_snapshot(self) -> Dict[str, Any]:
        return self.fallback_bot.get_stats_snapshot()

    def _legal_actions(self, state) -> list[str]:
        call_amount = _safe_int(getattr(state, "checking_or_calling_amount", 0), 0)
        min_raise = _safe_int(getattr(state, "min_completion_betting_or_raising_to_amount", 0), 0)
        max_raise = _safe_int(getattr(state, "max_completion_betting_or_raising_to_amount", 0), 0)

        if call_amount > 0:
            actions = ["fold", "call"]
        else:
            actions = ["check"]

        if min_raise > 0 and max_raise >= min_raise:
            actions.append("raise")
        return actions

    def _build_prompt(self, state, player_index: int, stats_context: Optional[Dict[str, Any]]) -> str:
        hero_cards = [str(card).upper() for card in list(state.hole_cards[player_index])]
        board_cards = [str(card).upper() for card in list(state.board_cards)]
        opponents = list((stats_context or {}).get("opponents", []) or [])
        action_log = list((stats_context or {}).get("action_log", []) or [])
        compact_opponents = []
        for opp in opponents[:5]:
            compact_opponents.append(
                {
                    "position": opp.get("position", ""),
                    "vpip": round(_safe_float(opp.get("vpip"), 0.0), 2),
                    "pfr": round(_safe_float(opp.get("pfr"), 0.0), 2),
                    "af": round(_safe_float(opp.get("af"), 0.0), 2),
                    "stack_bb": round(_safe_float(opp.get("stack_bb"), 0.0), 1),
                    "hands_played": _safe_int(opp.get("hands_played"), 0),
                }
            )

        payload = {
            "game_type": self.config.game_type,
            "style": self.config.style_name,
            "street": (stats_context or {}).get("street", "preflop"),
            "position": (stats_context or {}).get("position", ""),
            "hero_name": (stats_context or {}).get("hero_name", "hero"),
            "hero_seat": _safe_int((stats_context or {}).get("hero_seat", player_index), player_index),
            "hero_cards": hero_cards,
            "board_cards": board_cards,
            "hero_stack": _safe_int(state.stacks[player_index], 0),
            "call_amount": _safe_int(getattr(state, "checking_or_calling_amount", 0), 0),
            "min_raise_to": _safe_int(getattr(state, "min_completion_betting_or_raising_to_amount", 0), 0),
            "max_raise_to": _safe_int(getattr(state, "max_completion_betting_or_raising_to_amount", 0), 0),
            "pot": _safe_int(getattr(state, "total_pot_amount", 0), 0),
            "players_in_hand": _safe_int((stats_context or {}).get("players_in_hand", 0), 0),
            "players_yet_to_act": _safe_int((stats_context or {}).get("players_yet_to_act", 0), 0),
            "raise_count_before_action": _safe_int((stats_context or {}).get("raise_count_before_action", 0), 0),
            "hero_has_initiative": bool((stats_context or {}).get("hero_has_initiative", False)),
            "last_action_kind": (stats_context or {}).get("last_action_kind", ""),
            "last_action_position": (stats_context or {}).get("last_action_position", ""),
            "legal_actions": self._legal_actions(state),
            "opponents": compact_opponents,
            "action_log": action_log[-24:],
        }

        return (
            "You are a poker decision engine. Respond with JSON only.\n"
            "Adapt your strategy to the game_type field. In tournament mode value survival, stack preservation, and ICM-like caution more. In cash mode maximize chip EV.\n"
            "Choose exactly one legal poker action for the hero.\n"
            "Allowed JSON schema:\n"
            '{"action":"fold|check|call|raise","amount":integer|null}\n'
            "Rules:\n"
            "- Use only one action.\n"
            "- If action is not raise, amount must be null.\n"
            "- If action is raise, amount must be an integer raise-to amount between min_raise_to and max_raise_to.\n"
            "- Avoid all-in or near all-in raises unless hero is short stacked or in a clearly premium commitment spot.\n"
            "- Prefer standard poker sizings; avoid oversized raises without strong justification.\n"
            "- Never include explanations.\n"
            f"State:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _call_ollama(self, prompt: str) -> Optional[Dict[str, Any]]:
        body = {
            "model": self.config.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
            },
        }
        req = request.Request(
            f"{self.config.base_url}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"Ollama bot fallback | request failed: {exc}")
            return None

        response_text = str(payload.get("response", "") or "").strip()
        if not response_text:
            print("Ollama bot fallback | empty response")
            return None
        parsed = _extract_json_object(response_text)
        if parsed is None:
            print(f"Ollama bot fallback | invalid JSON response: {response_text}")
        return parsed

    def _coerce_action(self, raw: Dict[str, Any], state) -> Optional[BotAction]:
        action = _normalize_action(raw.get("action"))
        if action is None:
            return None

        call_amount = _safe_int(getattr(state, "checking_or_calling_amount", 0), 0)
        min_raise = _safe_int(getattr(state, "min_completion_betting_or_raising_to_amount", 0), 0)
        max_raise = _safe_int(getattr(state, "max_completion_betting_or_raising_to_amount", 0), 0)

        if action == "check":
            return BotAction("check")
        if action == "fold":
            return BotAction("fold")
        if action == "call":
            return BotAction("call", call_amount if call_amount > 0 else None)
        if action != "raise":
            return None
        if min_raise <= 0 or max_raise < min_raise:
            return None

        amount = _safe_int(raw.get("amount"), min_raise)
        amount = max(min_raise, min(amount, max_raise))
        return BotAction("raise", amount)

    def _reject_unsafe_raise(
        self,
        action: BotAction,
        state,
        player_index: int,
        stats_context: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if action.kind != "raise" or action.amount is None:
            return None

        stack = _safe_int(state.stacks[player_index], 0)
        if stack <= 0:
            return "empty_stack"

        amount = _safe_int(action.amount, 0)
        if amount <= 0:
            return "invalid_amount"

        board_cards = list(getattr(state, "board_cards", []) or [])
        is_preflop = len(board_cards) == 0
        raise_count = _safe_int((stats_context or {}).get("raise_count_before_action", 0), 0)
        hero_stack_bb = _safe_float((stats_context or {}).get("hero_stack_bb", 0.0), 0.0)
        pot = _safe_int(getattr(state, "total_pot_amount", 0), 0)
        amount_fraction = amount / max(stack, 1)
        premium_preflop = _is_premium_preflop(list(state.hole_cards[player_index]))
        short_stack = 0 < hero_stack_bb <= 12.0

        if amount >= stack and not short_stack:
            return "all_in_without_short_stack"
        if amount_fraction >= 0.85 and not short_stack and not (is_preflop and premium_preflop and raise_count >= 1):
            return "near_all_in_without_clear_spot"
        if is_preflop and raise_count == 0 and amount_fraction > 0.35:
            return "open_too_large"
        if is_preflop and raise_count >= 1 and amount_fraction > 0.55 and not premium_preflop and not short_stack:
            return "reraise_too_large"
        if not is_preflop and amount_fraction > 0.70 and not short_stack:
            return "postflop_raise_too_large"
        if pot > 0 and amount > int(round(pot * 2.2)) and not short_stack:
            return "oversized_vs_pot"
        return None

    def act(self, state, player_index: int, stats_context: Optional[Dict[str, Any]] = None) -> BotAction:
        if _safe_int(state.stacks[player_index], 0) <= 0:
            return BotAction("fold")

        prompt = self._build_prompt(state, player_index, stats_context)
        parsed = self._call_ollama(prompt)
        if parsed is None:
            return self.fallback_bot.act(state, player_index, stats_context=stats_context)

        action = self._coerce_action(parsed, state)
        if action is None:
            print(f"Ollama bot fallback | unsupported action payload: {parsed}")
            return self.fallback_bot.act(state, player_index, stats_context=stats_context)
        reject_reason = self._reject_unsafe_raise(action, state, player_index, stats_context)
        if reject_reason is not None:
            print(f"Ollama bot fallback | rejected aggressive raise: {reject_reason} payload={parsed}")
            return self.fallback_bot.act(state, player_index, stats_context=stats_context)
        return action
