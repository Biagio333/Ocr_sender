# cd C:\Users\cristiano.piacenti\AppData\Local\Android\Sdk\platform-tools
# adb devices
# adb reverse tcp:5000 tcp:5000

import json
import random
import re
import subprocess
import time
from typing import Optional

from config import (
    ADB_AMOUNT_TAP_DELAY_SEC,
    ADB_DEVICE_SERIAL,
    ADB_MAX_AMOUNT_STEPS,
    ADB_MAX_RETRIES,
    ADB_RETRY_DELAY_SEC,
    ADB_TAP_RANDOM_SEC,
    ANALYSIS_DB_PATH,
    ADB_TAP_DELAY_SEC,
    DATA_SOURCE,
    ENABLE_ADB_AUTOCLICK,
    ENABLE_BUTTON_DEBUG_LOGS,
    ENABLE_JSON_VIEWER,
    ENABLE_HERO_BOT,
    HERO_BOT_KIND,
    HERO_BOT_PROFILE,
    HERO_BOT_PROFILE_ROTATION_ENABLED,
    HERO_BOT_PROFILE_ROTATION_HANDS_BASE,
    HERO_BOT_PROFILE_ROTATION_MULTIPLIER_MAX,
    HERO_BOT_PROFILE_ROTATION_MULTIPLIER_MIN,
    HERO_BOT_PROFILE_ROTATION_PROFILES,
    HERO_BOT_ADAPTIVE_PROFILE_ENABLED,
    HERO_BOT_ADAPTIVE_PROFILE_MIN_HANDS,
    HERO_BOT_ADAPTIVE_PROFILE_MIN_OPPONENTS,
    HERO_BOT_ADAPTIVE_PROFILE_SWITCH_COOLDOWN_HANDS,
    ENABLE_TABLE_VIEWER,
    PACKET_SAVE_DIR,
    REPLAY_INPUT_PATH,
    SAVE_INCOMING_PACKETS,
    SOCKET_HOST,
    SOCKET_PORT,
)

from data_source import (
    PayloadBuffer,
    SocketPayloadReceiver,
    create_replay_buffer,
)
from data_store import HandHistoryStore, HeroDecisionStore, PacketStore
from hero_bot_bridge import HeroBotBridge
from payload_utils import payload_summary, pretty_payload
from table_mapper import TableStateMapper

HERO_BLUE = "\033[94m"
RED = "\033[91m"
ACCENT = "\033[96m"
RESET = "\033[0m"
RANK_ORDER = "23456789TJQKA"


def _load_viewers():
    try:
        import cv2
        from viewer import draw_results, show_image
        from viewer_table import show_table_view
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "unknown"
        print(
            "Viewer support disabled because the current Python interpreter is missing "
            f"`{missing_module}`. Install dependencies with "
            "`python3 -m pip install -r requirements.txt` to re-enable the viewers."
        )
        return None, None, None, None

    return cv2, draw_results, show_image, show_table_view


def build_payload_buffer() -> tuple[PayloadBuffer, Optional[SocketPayloadReceiver]]:
    if DATA_SOURCE == "socket":
        payload_buffer = PayloadBuffer()
        receiver = SocketPayloadReceiver(SOCKET_HOST, SOCKET_PORT, payload_buffer)
        receiver.start()
        return payload_buffer, receiver

    if DATA_SOURCE == "replay":
        return create_replay_buffer(REPLAY_INPUT_PATH), None

    raise ValueError(f"DATA_SOURCE non valida: {DATA_SOURCE}")


def get_next_payload(payload_buffer: PayloadBuffer) -> dict | None:
    return payload_buffer.pop_packet()


def _card_names(cards: list[dict]) -> str:
    names = [str(card.get("name", "")).upper() for card in cards if card.get("name")]
    return " ".join(names) if names else "-"


def _card_change_signature(cards: list[dict]) -> tuple[str, ...]:
    return tuple(str(card.get("name", "")).upper() for card in cards if card.get("name"))


def _log_cards_if_changed(
    table_state,
    previous_hero_cards: tuple[str, ...],
    previous_board_cards: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    current_hero_cards = _card_change_signature(getattr(table_state, "hero_cards", []) or [])
    current_board_cards = _card_change_signature(getattr(table_state, "board_cards", []) or [])

    if current_hero_cards != previous_hero_cards:
        print(f"Hero cards   : {' '.join(current_hero_cards) if current_hero_cards else '-'}")

    if current_board_cards != previous_board_cards:
        print(f"Board cards  : {' '.join(current_board_cards) if current_board_cards else '-'}")

    return current_hero_cards, current_board_cards


def _fmt_amount(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _hand_tag(table_state) -> str:
    hand_id = getattr(table_state, "hands_number", 0) or 0
    return f"[hand {hand_id}]"


def _parse_card_name(card_name: str) -> tuple[str, str] | None:
    text = (card_name or "").strip().upper()
    if len(text) < 2:
        return None
    rank = text[:-1]
    suit = text[-1]
    if rank == "10":
        rank = "T"
    if rank not in RANK_ORDER or suit not in {"C", "D", "H", "S"}:
        return None
    return rank, suit


def _is_straight(ranks: list[str]) -> bool:
    if len(ranks) < 5:
        return False
    values = sorted({RANK_ORDER.index(rank) for rank in ranks})
    if {12, 0, 1, 2, 3}.issubset(values):
        return True
    for start in range(len(values) - 4):
        window = values[start:start + 5]
        if window[-1] - window[0] == 4 and len(window) == 5:
            return True
    return False


def _hero_hand_label(table_state) -> str:
    if len(table_state.hero_cards) != 2:
        return "-"
    parsed_cards = []
    for card in [*table_state.hero_cards, *table_state.board_cards]:
        parsed = _parse_card_name(str(card.get("name", "")))
        if parsed is not None:
            parsed_cards.append(parsed)

    hero_parsed = [
        _parse_card_name(str(card.get("name", "")))
        for card in table_state.hero_cards
    ]
    hero_parsed = [card for card in hero_parsed if card is not None]
    if len(hero_parsed) != 2:
        return "-"

    if not table_state.board_cards:
        return "coppia servita" if hero_parsed[0][0] == hero_parsed[1][0] else "-"

    ranks = [rank for rank, _ in parsed_cards]
    suits = [suit for _, suit in parsed_cards]
    rank_counts: dict[str, int] = {}
    suit_counts: dict[str, int] = {}
    for rank in ranks:
        rank_counts[rank] = rank_counts.get(rank, 0) + 1
    for suit in suits:
        suit_counts[suit] = suit_counts.get(suit, 0) + 1

    counts = sorted(rank_counts.values(), reverse=True)
    board_rank_counts: dict[str, int] = {}
    for card in table_state.board_cards:
        parsed = _parse_card_name(str(card.get("name", "")))
        if parsed is None:
            continue
        board_rank = parsed[0]
        board_rank_counts[board_rank] = board_rank_counts.get(board_rank, 0) + 1
    board_is_paired = any(count >= 2 for count in board_rank_counts.values())
    flush = any(count >= 5 for count in suit_counts.values())
    straight = _is_straight(ranks)

    if flush and straight:
        return "scala colore"
    if counts and counts[0] == 4:
        return "poker"
    if len(counts) >= 2 and counts[0] == 3 and counts[1] >= 2:
        return "full"
    if flush:
        return "colore"
    if straight:
        return "scala"
    if counts and counts[0] == 3:
        return "tris"
    if len(counts) >= 2 and counts[0] == 2 and counts[1] == 2:
        if board_is_paired:
            return "coppia su board"
        return "doppia coppia"
    if counts and counts[0] == 2:
        return "coppia"
    return "carta alta"


def _clip(text: str, width: int) -> str:
    text = str(text)
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "."


def _button_labels(buttons: list[dict], fallback: str = "-") -> str:
    labels = [str(button.get("label", "")).strip() for button in buttons if str(button.get("label", "")).strip()]
    return " | ".join(labels) if labels else fallback


def _click_point_text(button: dict | None) -> str:
    if not button:
        return "-"
    click_point = button.get("click_point") or {}
    x = click_point.get("x")
    y = click_point.get("y")
    if x is None or y is None:
        return "-"
    return f"{x},{y}"


def _rect_tuple(rect: dict | None) -> tuple[int, int, int, int] | None:
    if not rect:
        return None
    try:
        if all(key in rect for key in ("left", "top", "right", "bottom")):
            left = int(rect.get("left"))
            top = int(rect.get("top"))
            right = int(rect.get("right"))
            bottom = int(rect.get("bottom"))
        elif all(key in rect for key in ("x", "y", "w", "h")):
            left = int(rect.get("x"))
            top = int(rect.get("y"))
            right = left + int(rect.get("w"))
            bottom = top + int(rect.get("h"))
        else:
            return None
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _expanded_ocr_tap_rect(button: dict | None) -> tuple[int, int, int, int] | None:
    if not button:
        return None
    ocr_rect = _rect_tuple(button.get("ocr_rect"))
    button_rect = _rect_tuple(button.get("button_rect"))
    if ocr_rect is None:
        return button_rect

    left, top, right, bottom = ocr_rect
    width = right - left
    height = bottom - top
    expand_x = max(1, int(round(width * 0.10)))
    expand_y = max(1, int(round(height * 0.10)))
    expanded = (
        left - expand_x,
        top - expand_y,
        right + expand_x,
        bottom + expand_y,
    )
    if button_rect is None:
        return expanded

    b_left, b_top, b_right, b_bottom = button_rect
    return (
        max(expanded[0], b_left),
        max(expanded[1], b_top),
        min(expanded[2], b_right),
        min(expanded[3], b_bottom),
    )


def _tap_point_signature(button: dict | None) -> tuple | None:
    if not button:
        return None
    return (
        tuple(sorted((button.get("button_rect") or {}).items())),
        tuple(sorted((button.get("click_rect") or {}).items())),
        tuple(sorted((button.get("ocr_rect") or {}).items())) if isinstance(button.get("ocr_rect"), dict) else (),
        str(button.get("label", "")),
    )


def _click_point(button: dict | None) -> tuple[int, int] | None:
    if not button:
        return None
    click_rect = _rect_tuple(button.get("click_rect"))
    if click_rect is not None:
        left, top, right, bottom = click_rect
        if right > left and bottom > top:
            return random.randint(left, right - 1), random.randint(top, bottom - 1)

    tap_rect = _expanded_ocr_tap_rect(button)
    if tap_rect is not None:
        left, top, right, bottom = tap_rect
        if right > left and bottom > top:
            return random.randint(left, right - 1), random.randint(top, bottom - 1)

    click_point = button.get("click_point") or {}
    x = click_point.get("x")
    y = click_point.get("y")
    if x is None or y is None:
        return None
    try:
        return int(x), int(y)
    except (TypeError, ValueError):
        return None


def _extract_first_int(text: str) -> int | None:
    digits = []
    started = False
    for ch in str(text or ""):
        if ch.isdigit():
            digits.append(ch)
            started = True
        elif started:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def _extract_first_amount_units(text: str, scale: int) -> int | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(text or ""))
    if match is None:
        return None
    try:
        return int(round(float(match.group(1).replace(",", ".")) * max(1, scale)))
    except ValueError:
        return None


def _normalized_button_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").strip().lower())


def _button_action_kind(button: dict | None, call_amount: int = 0) -> str:
    label = str((button or {}).get("label", "")).strip().lower()
    if not label:
        return ""
    if "fold" in label:
        return "fold"
    if "check" in label:
        return "check"
    if "call" in label or "chiama" in label:
        return "call" if call_amount > 0 else "check"
    if "raise" in label or "rilancia" in label or "bet" in label or "punta" in label:
        return "raise"
    return ""


def _find_live_action_button(table_state, hero_decision) -> dict | None:
    if hero_decision is None:
        return None
    wanted = str(getattr(hero_decision, "action_kind", "") or "").strip().lower()
    if not wanted:
        return None

    call_amount = int(getattr(hero_decision, "call_amount", 0) or 0)
    available_actions = list(getattr(table_state, "available_actions", []) or [])
    if not available_actions:
        return None

    selected_signature = _tap_point_signature(getattr(hero_decision, "selected_action_button", None))
    fallback = None
    for button in available_actions:
        mapped = _button_action_kind(button, call_amount)
        if mapped == wanted:
            if _tap_point_signature(button) == selected_signature:
                return button
            if fallback is None:
                fallback = button

    return fallback


def _find_live_amount_button(table_state, hero_decision) -> dict | None:
    if hero_decision is None:
        return None
    selected_amount_button = getattr(hero_decision, "selected_amount_button", None)
    if not selected_amount_button:
        return None

    wanted_label = str(selected_amount_button.get("label", "")).strip()
    if not wanted_label:
        return None

    selected_signature = _tap_point_signature(selected_amount_button)
    amount_buttons = list(getattr(table_state, "amount_buttons", []) or [])
    fallback = None
    for button in amount_buttons:
        label = str(button.get("label", "")).strip()
        if label != wanted_label:
            continue
        if _tap_point_signature(button) == selected_signature:
            return button
        if fallback is None:
            fallback = button

    return fallback


def _force_any_live_action_button(table_state) -> dict | None:
    available_actions = list(getattr(table_state, "available_actions", []) or [])
    for button in available_actions:
        label = str(button.get("label", "")).strip()
        if not label or _is_meta_control_label(label):
            continue
        if _button_action_kind(button):
            return button
    return None


def _refresh_live_hero_decision(table_state, hero_decision, current_available_actions) -> tuple[object | None, str | None]:
    if hero_decision is None:
        return None, None

    live_action_button = _find_live_action_button(table_state, hero_decision)
    if live_action_button is None:
        forced_button = _force_any_live_action_button(table_state)
        if forced_button is None:
            return None, (
                "ADB autoclick | skip stale decision: "
                f"wanted={hero_decision.action_kind} "
                f"buttons={_button_labels(current_available_actions)}"
            )
        print(
            "ADB autoclick | force visible action: "
            f"wanted={hero_decision.action_kind} "
            f"forced={forced_button.get('label', '')}"
        )
        live_action_button = forced_button

    hero_decision.selected_action_button = live_action_button
    live_amount_button = _find_live_amount_button(table_state, hero_decision)
    if live_amount_button is not None:
        hero_decision.selected_amount_button = live_amount_button
    return hero_decision, None


def _is_meta_control_label(text: str) -> bool:
    label = _normalized_button_label(text)
    if not label:
        return False
    return (
        label.startswith("tornaagiocare")
        or label.startswith("rientra")
        or label.startswith("sitout")
        or "sitoutalbuiogrande" in label
        or "sitoutlamano" in label
    )


def _looks_like_preaction_controls(buttons: list[dict] | None) -> bool:
    raw_buttons = list(buttons or [])
    if not raw_buttons or len(raw_buttons) > 2:
        return False

    raw_texts = [str(button.get("label", "")).strip() for button in raw_buttons]
    if any(re.search(r"\d", text) for text in raw_texts):
        return False

    labels = [_normalized_button_label(text) for text in raw_texts]
    labels = [label for label in labels if label]
    if not labels:
        return False

    if any("checkfold" in label for label in labels):
        return True

    if (
        len(labels) == 2
        and any("fold" in label for label in labels)
        and any("chiama" in label or "call" in label or label == "check" for label in labels)
    ):
        return True

    if (
        len(labels) == 2
        and any("aspetta" in label and "grande" in label for label in labels)
        and any("buio" in label for label in labels)
    ):
        return True

    return False


def _handle_no_red_action_area(table_state, ocr_items: list[dict] | None) -> None:
    _ = table_state
    _ = ocr_items or []
    return


class AdbAutoClicker:
    def __init__(
        self,
        *,
        device_serial: str = "",
        tap_delay_sec: float = 0.20,
        amount_tap_delay_sec: float = 0.12,
        tap_random_sec: float = 0.0,
        max_amount_steps: int = 6,
        retry_delay_sec: float = 2.5,
        max_retries: int = 3,
    ):
        self.device_serial = (device_serial or "").strip()
        self.tap_delay_sec = tap_delay_sec
        self.amount_tap_delay_sec = amount_tap_delay_sec
        self.tap_random_sec = max(0.0, float(tap_random_sec))
        self.max_amount_steps = max(0, int(max_amount_steps))
        self.retry_delay_sec = max(0.0, float(retry_delay_sec))
        self.max_retries = max(1, int(max_retries))
        self._last_execution_key: tuple | None = None
        self._last_attempt_at: float = 0.0
        self._attempt_count: int = 0
        self._last_execution_consumed: bool = False
        self._last_meta_execution_key: tuple | None = None
        self._last_meta_attempt_at: float = 0.0
        self._last_red_controls_key: tuple | None = None
        self._stable_red_controls_frames: int = 0
        self._retry_delay_skip_key: tuple | None = None
        self._retry_delay_skip_count: int = 0
        self._force_recalc_after_retry_skips: int = 3

    def _log(self, message: str) -> None:
        print(f"ADB autoclick | {message}")

    def _adb_base(self) -> list[str]:
        base = ["adb"]
        if self.device_serial:
            base.extend(["-s", self.device_serial])
        return base

    def _tap(self, x: int, y: int) -> None:
        self._log(f"tap {x},{y}")
        subprocess.run(
            [*self._adb_base(), "shell", "input", "tap", str(x), str(y)],
            check=True,
            capture_output=True,
            text=True,
        )

    def _sleep_with_jitter(self, base_delay: float) -> None:
        jitter = random.uniform(0.0, self.tap_random_sec) if self.tap_random_sec > 0 else 0.0
        time.sleep(base_delay + jitter)

    def _red_controls_key(self, table_state, hero_decision) -> tuple:
        return (
            getattr(table_state, "hands_number", None),
            getattr(table_state, "street", None),
            getattr(hero_decision, "action_kind", None),
            getattr(hero_decision, "action_amount", None),
            tuple(
                str(button.get("label", "")).strip()
                for button in (getattr(table_state, "available_actions", []) or [])
            ),
            tuple(
                str(button.get("label", "")).strip()
                for button in (getattr(table_state, "amount_buttons", []) or [])
            ),
            str(getattr(table_state, "amount_value_text", "") or "").strip(),
        )

    def maybe_execute_meta_button(self, table_state) -> bool:
        buttons = list(getattr(table_state, "available_actions", []) or [])
        meta_candidates = [
            button for button in buttons
            if _is_meta_control_label(button.get("label", ""))
        ]
        meta_button = None
        if meta_candidates:
            meta_button = max(
                meta_candidates,
                key=lambda button: (
                    len(str(button.get("label", ""))),
                    int(((button.get("button_rect") or {}).get("right") or 0)) - int(((button.get("button_rect") or {}).get("left") or 0)),
                ),
            )

        if meta_button is None:
            self._last_meta_execution_key = None
            self._last_meta_attempt_at = 0.0
            return False

        target = _click_point(meta_button)
        if target is None:
            self._log("skip: meta button found but no click target")
            return False

        execution_key = (
            getattr(table_state, "hands_number", None),
            getattr(table_state, "street", None),
            _normalized_button_label(meta_button.get("label", "")),
            _tap_point_signature(meta_button),
        )
        now = time.monotonic()
        if execution_key == self._last_meta_execution_key and now - self._last_meta_attempt_at < self.retry_delay_sec:
            self._log("skip: waiting retry delay for meta button")
            return False

        self._log(f"execute meta button label={meta_button.get('label', '')} target={target}")
        self._tap(*target)
        self._last_meta_execution_key = execution_key
        self._last_meta_attempt_at = time.monotonic()
        return True

    def maybe_execute(self, table_state, hero_decision, *, force: bool = False) -> str:
        execution_key = (
            hero_decision.hand_id,
            hero_decision.street,
            hero_decision.action_kind,
            hero_decision.action_amount,
        )
        now = time.monotonic()
        if execution_key != self._last_execution_key:
            self._last_execution_key = execution_key
            self._attempt_count = 0
            self._last_attempt_at = 0.0
            self._last_execution_consumed = False
            self._last_red_controls_key = None
            self._stable_red_controls_frames = 0
            self._retry_delay_skip_key = execution_key
            self._retry_delay_skip_count = 0
        elif self._last_execution_consumed:
            #self._log("skip: decision already executed")
            return "consumed"
        elif self._attempt_count >= self.max_retries:
            self._log("skip: max retries reached")
            return "max_retries"
        elif not force and now - self._last_attempt_at < self.retry_delay_sec:
            if execution_key != self._retry_delay_skip_key:
                self._retry_delay_skip_key = execution_key
                self._retry_delay_skip_count = 0
            self._retry_delay_skip_count += 1
            if self._retry_delay_skip_count >= self._force_recalc_after_retry_skips:
                self._log(
                    "force recalculation after repeated retry delay "
                    f"count={self._retry_delay_skip_count}"
                )
                self._retry_delay_skip_count = 0
                return "force_recalc"
            self._log("skip: waiting retry delay")
            return "retry_delay"
        else:
            self._retry_delay_skip_key = execution_key
            self._retry_delay_skip_count = 0

        red_controls_key = self._red_controls_key(table_state, hero_decision)
        if red_controls_key != self._last_red_controls_key:
            self._last_red_controls_key = red_controls_key
            self._stable_red_controls_frames = 1
        else:
            self._stable_red_controls_frames += 1

        if self._stable_red_controls_frames < 2:
            self._log(
                "wait: red controls confirmation "
                f"{self._stable_red_controls_frames}/2 "
                f"buttons={_button_labels(getattr(table_state, 'available_actions', []) or [])}"
            )
            return "wait_red_confirmation"

        action_point = _click_point(hero_decision.selected_action_button)
        amount_point = _click_point(hero_decision.selected_amount_button)

        if hero_decision.action_kind in {"fold", "call", "check"}:
            if action_point is None:
                self._log(
                    f"skip: no action target for {hero_decision.action_kind} "
                    f"button={hero_decision.selected_action_button and hero_decision.selected_action_button.get('label')}"
                )
                return "no_action_target"
            self._log(f"execute {hero_decision.action_kind} target={action_point}")
            self._tap(*action_point)
            self._attempt_count += 1
            self._last_attempt_at = time.monotonic()
            return "executed"

        if hero_decision.action_kind != "raise":
            self._log(f"skip: unsupported action {hero_decision.action_kind}")
            return "unsupported_action"

        current_amount = _extract_first_int(getattr(table_state, "amount_value_text", "") or "")
        money_scale = max(1, int(getattr(hero_decision, "money_scale", 1) or 1))
        current_amount = _extract_first_amount_units(getattr(table_state, "amount_value_text", "") or "", money_scale)
        target_amount = hero_decision.action_amount
        amount_buttons = getattr(table_state, "amount_buttons", []) or []
        plus_button = next((button for button in amount_buttons if str(button.get("label", "")).strip() == "+"), None)
        minus_button = next((button for button in amount_buttons if str(button.get("label", "")).strip() == "-"), None)
        plus_point = _click_point(plus_button)
        minus_point = _click_point(minus_button)

        if amount_point is not None:
            self._log(
                f"preset raise target={amount_point} "
                f"label={hero_decision.selected_amount_button and hero_decision.selected_amount_button.get('label')}"
            )
            self._tap(*amount_point)
            self._sleep_with_jitter(self.tap_delay_sec)
            preset_estimate = hero_decision.selected_amount_button.get("estimated_value") if hero_decision.selected_amount_button else None
            if preset_estimate is not None:
                try:
                    current_amount = int(preset_estimate)
                except (TypeError, ValueError):
                    pass

        if (
            target_amount is not None
            and current_amount is not None
            and target_amount != current_amount
            and self.max_amount_steps > 0
        ):
            step_guess = max(1, int(round(float(table_state.BB_amount or 0.0) * money_scale)))
            diff = target_amount - current_amount
            steps = min(self.max_amount_steps, max(1, int(abs(diff) // step_guess) + 1))
            point = plus_point if diff > 0 else minus_point
            if point is not None:
                estimate = current_amount
                for _ in range(steps):
                    if diff > 0 and estimate >= target_amount:
                        break
                    if diff < 0 and estimate <= target_amount:
                        break
                    self._log(f"step {'+' if diff > 0 else '-'} target={point} estimate={estimate} target_amount={target_amount}")
                    self._tap(*point)
                    self._sleep_with_jitter(self.amount_tap_delay_sec)
                    estimate += step_guess if diff > 0 else -step_guess

        final_point = action_point or amount_point
        if final_point is None:
            self._log("skip: no final tap target for raise")
            return "no_final_target"
        self._sleep_with_jitter(self.tap_delay_sec)
        self._log(f"final raise tap target={final_point}")
        self._tap(*final_point)
        self._attempt_count += 1
        self._last_attempt_at = time.monotonic()
        return "executed"


def _print_hero_bot_snapshot(table_state, hero_decision, hero_bot) -> None:
    columns = (
        ("Seat", 4),
        ("Player", 28),
        ("Pos", 3),
        ("Stack", 5),
        ("Cards", 7),
        ("Hand", 14),
        ("Actions", 31),
        ("Style", 13),
        ("Hands", 5),
        ("Status", 14),
    )

    separator = "+" + "+".join("-" * (width + 2) for _, width in columns) + "+"

    def row(cells):
        return "|" + "|".join(f" {cell} " for cell in cells) + "|"

    hand_tag = _hand_tag(table_state)
    print()
    print(f"{ACCENT}{'=' * len(separator)}{RESET}")
    print(f"{hand_tag} SITUAZIONE DOPO L'AZIONE")
    print(f"Hand         : {table_state.hands_number}")
    print(f"Street       : {table_state.street}")
    print(f"Board        : {_card_names(table_state.board_cards)}")
    print(f"Pot          : {_fmt_amount(table_state.pot_amount)}")
    print(f"Call amount  : {hero_decision.format_amount(hero_decision.call_amount)}")
    print(f"Min raise to : {hero_decision.format_amount(hero_decision.min_raise_to)}")
    print(f"Max raise to : {hero_decision.format_amount(hero_decision.max_raise_to)}")
    print(f"Button global: {hero_bot.get_button_player()}")
    print(f"Blind        : SB={_fmt_amount(table_state.BB_amount / 2 if table_state.BB_amount else 0)} BB={_fmt_amount(table_state.BB_amount)} Ante=0")
    print(f"Actions avail: {_button_labels(hero_bot.get_available_actions())}")
    print(f"Amount btns  : {_button_labels(hero_bot.get_amount_buttons())}")
    print(f"Amount value : {hero_bot.get_amount_value_text() or '-'}")
    print(f"Bot profile  : {hero_bot.get_bot_name() or '-'}")
    next_switch_at = hero_bot.get_next_profile_switch_after_hands()
    completed_hands = hero_bot.get_completed_hands_count()
    remaining_switch_hands = (
        max(0, next_switch_at - completed_hands)
        if next_switch_at is not None else None
    )
    print(
        "Profile rot. : "
        f"hands={completed_hands} "
        f"next={next_switch_at if next_switch_at is not None else '-'} "
        f"remaining={remaining_switch_hands if remaining_switch_hands is not None else '-'}"
    )
    print(f"Profile why  : {hero_bot.get_last_profile_switch_reason() or '-'}")
    print(separator)
    print(
        row(
            [
                f"{label:<{width}}"
                for label, width in columns
            ]
        )
    )
    print(separator)

    for player in table_state.players:
        position = hero_bot.get_position_for_seat(player.player_index)
        cards = _card_names(table_state.hero_cards) if player.player_index == 0 else "-"
        hand_label = _hero_hand_label(table_state) if player.player_index == 0 else "-"
        actions = hero_bot.get_player_street_actions_text(player.player_index)
        style = hero_bot.get_player_style_text(table_state, player.player_index)
        hands_played = str(hero_bot.get_player_hands_played(table_state, player.player_index))
        status = hero_bot.get_player_status_text(
            player.player_index,
            acting_seat=hero_bot.get_acting_seat(hero_decision),
        )
        line = row(
            [
                f"{player.player_index:>{columns[0][1]}}",
                f"{_clip(player.name or '-', columns[1][1]):<{columns[1][1]}}",
                f"{_clip(position, columns[2][1]):<{columns[2][1]}}",
                f"{_fmt_amount(player.stack_amount):>{columns[3][1]}}",
                f"{_clip(cards, columns[4][1]):<{columns[4][1]}}",
                f"{_clip(hand_label, columns[5][1]):<{columns[5][1]}}",
                f"{_clip(actions, columns[6][1]):<{columns[6][1]}}",
                f"{_clip(style, columns[7][1]):<{columns[7][1]}}",
                f"{hands_played:>{columns[8][1]}}",
                f"{_clip(status, columns[9][1]):<{columns[9][1]}}",
            ]
        )
        if player.player_index == 0:
            print(f"{HERO_BLUE}{line}{RESET}")
        else:
            print(line)

    print(separator)
    print("-" * 80)
    print(f"{hand_tag} Action log")
    action_log = hero_bot.get_action_log()
    if not action_log:
        print("  - nessuna azione ancora")
    else:
        for action_line in action_log:
            print(f"  - {action_line}")
    for debug_line in getattr(hero_decision, "debug_lines", []) or []:
        print(debug_line)
    print(f"{HERO_BLUE}{hero_decision.summary()}{RESET}")
    print(
        "Click target : "
        f"action={_click_point_text(hero_decision.selected_action_button)} "
        f"amount={_click_point_text(hero_decision.selected_amount_button)}"
    )
    print(f"{ACCENT}{'=' * len(separator)}{RESET}")


def _build_analysis_hand_id(session_hand_base: int, hand_id: int) -> int:
    return int(session_hand_base + max(0, int(hand_id or 0)))


def _save_hero_decision_snapshot(
    decision_store,
    payload,
    table_state,
    hero_decision,
    *,
    session_hand_base: int = 0,
) -> None:
    if decision_store is None or hero_decision is None:
        return

    raw_table = ((getattr(table_state, "raw", {}) or {}).get("table", {}) or {})
    row = {
        "payload_timestamp": payload.get("timestamp"),
        "hand_id": _build_analysis_hand_id(session_hand_base, hero_decision.hand_id),
        "street": hero_decision.street,
        "position": hero_decision.position,
        "hero_cards": json.dumps(list(getattr(table_state, "hero_cards", []) or []), ensure_ascii=False),
        "board_cards": json.dumps(list(getattr(table_state, "board_cards", []) or []), ensure_ascii=False),
        "hero_stack": hero_decision.hero_stack,
        "hero_bet": hero_decision.hero_bet,
        "call_amount": hero_decision.call_amount,
        "min_raise_to": hero_decision.min_raise_to,
        "max_raise_to": hero_decision.max_raise_to,
        "action_kind": hero_decision.action_kind,
        "action_amount": hero_decision.action_amount,
        "source_action_player": hero_decision.source_action_player,
        "source_action_kind": hero_decision.source_action_kind,
        "has_red_action_area": bool(raw_table.get("has_red_action_area", False)),
        "red_action_area_avg_red": raw_table.get("red_action_area_avg_red", 0.0),
        "available_actions": list(getattr(table_state, "available_actions", []) or []),
        "amount_buttons": list(getattr(table_state, "amount_buttons", []) or []),
        "selected_action_button": hero_decision.selected_action_button,
        "selected_amount_button": hero_decision.selected_amount_button,
        "payload": payload,
    }
    decision_store.save_decision(row)


def _hero_decision_signature(hero_decision) -> tuple:
    return (
        getattr(hero_decision, "hand_id", None),
        getattr(hero_decision, "street", None),
        getattr(hero_decision, "position", None),
        getattr(hero_decision, "action_kind", None),
        getattr(hero_decision, "action_amount", None),
        getattr(hero_decision, "hero_stack", None),
        getattr(hero_decision, "hero_bet", None),
        getattr(hero_decision, "call_amount", None),
        getattr(hero_decision, "min_raise_to", None),
        getattr(hero_decision, "max_raise_to", None),
        getattr(hero_decision, "source_action_player", None),
        getattr(hero_decision, "source_action_kind", None),
        json.dumps(getattr(hero_decision, "selected_action_button", None), ensure_ascii=False, sort_keys=True),
        json.dumps(getattr(hero_decision, "selected_amount_button", None), ensure_ascii=False, sort_keys=True),
    )


def _save_hand_history_snapshot(
    hand_store,
    payload,
    table_state,
    hero_decision=None,
    *,
    session_hand_base: int = 0,
) -> None:
    if hand_store is None:
        return

    hand_id = getattr(table_state, "hands_number", 0)
    if hand_id <= 0:
        return

    winner_seat = None
    winner_name = None
    for player in getattr(table_state, "players", []) or []:
        action = str(getattr(player, "inferred_action", "") or "").strip().lower()
        if action.startswith("vin"):
            winner_seat = player.player_index
            winner_name = player.name or f"Seat {player.player_index}"
            break

    hero_player = table_state.get_player(0) if hasattr(table_state, "get_player") else None
    row = {
        "hand_id": _build_analysis_hand_id(session_hand_base, hand_id),
        "first_payload_timestamp": payload.get("timestamp"),
        "last_payload_timestamp": payload.get("timestamp"),
        "street": getattr(table_state, "street", ""),
        "hero_position": getattr(hero_decision, "position", "") if hero_decision is not None else "",
        "hero_cards": json.dumps(list(getattr(table_state, "hero_cards", []) or []), ensure_ascii=False),
        "board_cards": json.dumps(list(getattr(table_state, "board_cards", []) or []), ensure_ascii=False),
        "hero_stack": getattr(hero_decision, "hero_stack", None) if hero_decision is not None else getattr(hero_player, "stack_amount", None),
        "hero_bet": getattr(hero_decision, "hero_bet", None) if hero_decision is not None else getattr(hero_player, "bet_amount", None),
        "pot_amount": getattr(table_state, "pot_amount", None),
        "hero_action_kind": getattr(hero_decision, "action_kind", None) if hero_decision is not None else None,
        "hero_action_amount": getattr(hero_decision, "action_amount", None) if hero_decision is not None else None,
        "source_action_player": getattr(hero_decision, "source_action_player", None) if hero_decision is not None else None,
        "source_action_kind": getattr(hero_decision, "source_action_kind", None) if hero_decision is not None else None,
        "winner_seat": winner_seat,
        "winner_name": winner_name,
        "payload": payload,
    }
    hand_store.upsert_hand(row)


def main():
    cv2 = None
    draw_results = None
    show_image = None
    show_table_view = None
    json_viewer_enabled = ENABLE_JSON_VIEWER
    table_viewer_enabled = ENABLE_TABLE_VIEWER
    if ENABLE_JSON_VIEWER or ENABLE_TABLE_VIEWER:
        cv2, draw_results, show_image, show_table_view = _load_viewers()
        if cv2 is None:
            json_viewer_enabled = False
            table_viewer_enabled = False

    payload_buffer, receiver = build_payload_buffer()
    packet_store = None
    hero_decision_store = None
    hand_history_store = None
    table_mapper = TableStateMapper()
    hero_bot = None
    adb_auto_clicker = None
    last_hero_decision = None
    last_saved_hero_decision_signature = None
    previous_logged_hero_cards: tuple[str, ...] = ()
    previous_logged_board_cards: tuple[str, ...] = ()
    analysis_session_hand_base = int(time.time() * 1_000_000)
    if ENABLE_HERO_BOT:
        hero_bot = HeroBotBridge(
            bot_kind=HERO_BOT_KIND,
            profile_name=HERO_BOT_PROFILE,
            rotation_enabled=HERO_BOT_PROFILE_ROTATION_ENABLED,
            rotation_profiles=HERO_BOT_PROFILE_ROTATION_PROFILES,
            rotation_hands_base=HERO_BOT_PROFILE_ROTATION_HANDS_BASE,
            rotation_multiplier_min=HERO_BOT_PROFILE_ROTATION_MULTIPLIER_MIN,
            rotation_multiplier_max=HERO_BOT_PROFILE_ROTATION_MULTIPLIER_MAX,
            adaptive_profile_enabled=HERO_BOT_ADAPTIVE_PROFILE_ENABLED,
            adaptive_profile_min_hands=HERO_BOT_ADAPTIVE_PROFILE_MIN_HANDS,
            adaptive_profile_min_opponents=HERO_BOT_ADAPTIVE_PROFILE_MIN_OPPONENTS,
            adaptive_profile_switch_cooldown_hands=HERO_BOT_ADAPTIVE_PROFILE_SWITCH_COOLDOWN_HANDS,
        )
    if ENABLE_ADB_AUTOCLICK and DATA_SOURCE == "socket":
        adb_auto_clicker = AdbAutoClicker(
            device_serial=ADB_DEVICE_SERIAL,
            tap_delay_sec=ADB_TAP_DELAY_SEC,
            amount_tap_delay_sec=ADB_AMOUNT_TAP_DELAY_SEC,
            tap_random_sec=ADB_TAP_RANDOM_SEC,
            max_amount_steps=ADB_MAX_AMOUNT_STEPS,
            retry_delay_sec=ADB_RETRY_DELAY_SEC,
            max_retries=ADB_MAX_RETRIES,
        )
    if DATA_SOURCE == "socket" and SAVE_INCOMING_PACKETS:
        packet_store = PacketStore(PACKET_SAVE_DIR)
    if ENABLE_HERO_BOT:
        hero_decision_store = HeroDecisionStore(ANALYSIS_DB_PATH)
        hand_history_store = HandHistoryStore(ANALYSIS_DB_PATH)

    index = 0
    try:
        while True:
            payload = get_next_payload(payload_buffer)

            if payload is None:
                if DATA_SOURCE == "replay":
                    break

                if receiver is not None and receiver.is_closed() and payload_buffer.pending_count == 0:
                    break

                payload = payload_buffer.wait_packet()

            index += 1
            table_state = table_mapper.build_table(payload)
            previous_logged_hero_cards, previous_logged_board_cards = _log_cards_if_changed(
                table_state,
                previous_logged_hero_cards,
                previous_logged_board_cards,
            )

            #---------------------------------------------------
            #-- aspetto inizio mano per fare giocare il boot ---
            #---------------------------------------------------

            if False:
                print(f"[{index}] {payload_summary(payload)}")
                print(
                    "TableBase:",
                    f"street={table_state.street},",
                    f"pot={table_state.pot_amount},",
                    f"players={len(table_state.players)}"
                )
                for player in table_state.players:
                    print(
                        f"  P{player.player_index} "
                        f"name={player.name or '-'} "
                        f"stack={player.stack_amount} "
                        f"bet={player.bet_amount} "
                        f"action={player.inferred_action}"
                    )
                print(pretty_payload(payload))

            if packet_store is not None:
                saved_path = packet_store.save_payload(payload)
                #print(f"Pacchetto salvato in: {saved_path}")

            _save_hand_history_snapshot(
                hand_history_store,
                payload,
                table_state,
                session_hand_base=analysis_session_hand_base,
            )

            
            if ENABLE_BUTTON_DEBUG_LOGS:
                table_debug = ((getattr(table_state, "raw", {}) or {}).get("table", {}) or {})
                debug_pulsanti0_raw = str(table_debug.get("debug_pulsanti0_ocr_raw", "") or "").strip()
                debug_pulsanti0_clusters = str(table_debug.get("debug_pulsanti0_ocr_clusters", "") or "").strip()
                debug_pulsanti0_parsed = str(table_debug.get("debug_pulsanti0_parsed_buttons", "") or "").strip()
                if debug_pulsanti0_raw or debug_pulsanti0_clusters or debug_pulsanti0_parsed:
                    print(f"pulsanti0 OCR raw: {debug_pulsanti0_raw or '-'}")
                    print(f"pulsanti0 OCR clusters: {debug_pulsanti0_clusters or '-'}")
                    print(f"pulsanti0 parsed button: {debug_pulsanti0_parsed or '-'}")

            current_available_actions = getattr(table_state, "available_actions", []) or []
            has_red_action_area = bool((((getattr(table_state, "raw", {}) or {}).get("table", {}) or {}).get("has_red_action_area", False)))
            red_action_area_avg_red = (((getattr(table_state, "raw", {}) or {}).get("table", {}) or {}).get("red_action_area_avg_red", 0.0))
            if has_red_action_area:
                print(
                    f"{RED}{_hand_tag(table_state)} pulsanti OCR con rosso: "
                    f"avgRed={red_action_area_avg_red} "
                    f"buttons={_button_labels(current_available_actions)}{RESET}"
                )
            ocr_items = list((getattr(table_state, "raw", {}) or {}).get("ocr_items", []) or [])
            if not has_red_action_area:
                _handle_no_red_action_area(table_state, ocr_items)
            if _looks_like_preaction_controls(current_available_actions) and not has_red_action_area:
                last_hero_decision = None
                continue

            if adb_auto_clicker is not None and has_red_action_area:
                try:
                    if adb_auto_clicker.maybe_execute_meta_button(table_state):
                        last_hero_decision = None
                        continue
                except Exception as exc:
                    print(f"ADB meta autoclick error: {exc}")

            if hero_bot is not None:
                hero_decision = hero_bot.process_table(table_state)
                if hero_decision is not None:
                    last_hero_decision = hero_decision
                    decision_signature = _hero_decision_signature(hero_decision)
                    if decision_signature != last_saved_hero_decision_signature:
                        _save_hero_decision_snapshot(
                            hero_decision_store,
                            payload,
                            table_state,
                            hero_decision,
                            session_hand_base=analysis_session_hand_base,
                        )
                        last_saved_hero_decision_signature = decision_signature
                    _save_hand_history_snapshot(
                        hand_history_store,
                        payload,
                        table_state,
                        hero_decision,
                        session_hand_base=analysis_session_hand_base,
                    )
                    _print_hero_bot_snapshot(table_state, hero_decision, hero_bot)
                elif last_hero_decision is not None:
                    if (
                        last_hero_decision.hand_id != table_state.hands_number
                        or last_hero_decision.street != table_state.street
                    ):
                        last_hero_decision = None
                        last_saved_hero_decision_signature = None
                    elif not (
                        table_state.hero_to_act
                        or getattr(table_state, "available_actions", [])
                        or getattr(table_state, "amount_buttons", [])
                        or getattr(table_state, "amount_value_text", "")
                    ):
                        last_hero_decision = None
                        last_saved_hero_decision_signature = None

                if adb_auto_clicker is not None and has_red_action_area and last_hero_decision is not None:
                    current_action_kinds = {
                        _button_action_kind(button, int(getattr(last_hero_decision, "call_amount", 0) or 0))
                        for button in current_available_actions
                    }
                    current_action_kinds.discard("")
                    if (
                        last_hero_decision.action_kind == "fold"
                        and "fold" not in current_action_kinds
                        and current_action_kinds.intersection({"check", "call", "raise"})
                    ):
                        print(
                            "ADB autoclick | invalidate stale fold: "
                            f"buttons={_button_labels(current_available_actions)}"
                        )
                        hero_bot.invalidate_hero_decision(
                            last_hero_decision.hand_id,
                            last_hero_decision.street,
                        )
                        last_hero_decision = None
                        continue

                    current_decision = last_hero_decision
                    last_hero_decision, stale_reason = _refresh_live_hero_decision(
                        table_state,
                        current_decision,
                        current_available_actions,
                    )
                    if last_hero_decision is None:
                        if stale_reason:
                            print(stale_reason)
                        hero_bot.invalidate_hero_decision(
                            current_decision.hand_id,
                            current_decision.street,
                        )
                        last_hero_decision = None
                        continue
                    try:
                        execute_status = adb_auto_clicker.maybe_execute(table_state, last_hero_decision)
                        if execute_status == "force_recalc":
                            print(
                                "ADB autoclick | force bot recalculation after repeated retry delay: "
                                f"hand={last_hero_decision.hand_id} "
                                f"street={last_hero_decision.street} "
                                f"action={last_hero_decision.action_kind}"
                            )
                            hero_bot.invalidate_hero_decision(
                                last_hero_decision.hand_id,
                                last_hero_decision.street,
                            )
                            refreshed_decision = hero_bot.process_table(table_state)
                            if refreshed_decision is None:
                                last_hero_decision = None
                                continue
                            last_hero_decision, stale_reason = _refresh_live_hero_decision(
                                table_state,
                                refreshed_decision,
                                current_available_actions,
                            )
                            if last_hero_decision is None:
                                if stale_reason:
                                    print(stale_reason)
                                continue
                            adb_auto_clicker.maybe_execute(
                                table_state,
                                last_hero_decision,
                                force=True,
                            )
                    except Exception as exc:
                        print(f"ADB autoclick error: {exc}")

            if json_viewer_enabled:
                img = draw_results(payload)
                show_image(img)

            if table_viewer_enabled:
                show_table_view(table_state)
    finally:
        if hero_bot is not None:
            hero_bot.flush()
        if cv2 is not None:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
