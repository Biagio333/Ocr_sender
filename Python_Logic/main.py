# cd C:\Users\cristiano.piacenti\AppData\Local\Android\Sdk\platform-tools
# adb devices
# adb reverse tcp:5000 tcp:5000

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
    ADB_TAP_DELAY_SEC,
    DATA_SOURCE,
    ENABLE_ADB_AUTOCLICK,
    ENABLE_JSON_VIEWER,
    ENABLE_HERO_BOT,
    HERO_BOT_KIND,
    HERO_BOT_PROFILE,
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
from data_store import PacketStore
from hero_bot_bridge import HeroBotBridge
from payload_utils import payload_summary, pretty_payload
from table_mapper import TableStateMapper

HERO_BLUE = "\033[94m"
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


def _fmt_amount(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


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
        left = int(rect.get("left"))
        top = int(rect.get("top"))
        right = int(rect.get("right"))
        bottom = int(rect.get("bottom"))
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

    def maybe_execute(self, table_state, hero_decision) -> None:
        execution_key = (
            hero_decision.hand_id,
            hero_decision.street,
            hero_decision.action_kind,
            hero_decision.action_amount,
            _tap_point_signature(hero_decision.selected_action_button),
            _tap_point_signature(hero_decision.selected_amount_button),
        )
        now = time.monotonic()
        if execution_key != self._last_execution_key:
            self._last_execution_key = execution_key
            self._attempt_count = 0
            self._last_attempt_at = 0.0
        elif self._attempt_count >= self.max_retries:
            self._log("skip: max retries reached")
            return
        elif now - self._last_attempt_at < self.retry_delay_sec:
            self._log("skip: waiting retry delay")
            return

        action_point = _click_point(hero_decision.selected_action_button)
        amount_point = _click_point(hero_decision.selected_amount_button)

        if hero_decision.action_kind in {"fold", "call", "check"}:
            if action_point is None:
                self._log(
                    f"skip: no action target for {hero_decision.action_kind} "
                    f"button={hero_decision.selected_action_button and hero_decision.selected_action_button.get('label')}"
                )
                return
            self._log(f"execute {hero_decision.action_kind} target={action_point}")
            self._tap(*action_point)
            self._attempt_count += 1
            self._last_attempt_at = time.monotonic()
            return

        if hero_decision.action_kind != "raise":
            self._log(f"skip: unsupported action {hero_decision.action_kind}")
            return

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
            return
        self._sleep_with_jitter(self.tap_delay_sec)
        self._log(f"final raise tap target={final_point}")
        self._tap(*final_point)
        self._attempt_count += 1
        self._last_attempt_at = time.monotonic()


def _print_hero_bot_snapshot(table_state, hero_decision, hero_bot) -> None:
    columns = (
        ("Seat", 4),
        ("Player", 28),
        ("Pos", 3),
        ("Stack", 5),
        ("Cards", 7),
        ("Hand", 14),
        ("Actions", 31),
        ("Status", 14),
    )

    separator = "+" + "+".join("-" * (width + 2) for _, width in columns) + "+"

    def row(cells):
        return "|" + "|".join(f" {cell} " for cell in cells) + "|"

    print()
    print(f"{ACCENT}{'=' * len(separator)}{RESET}")
    print("SITUAZIONE DOPO L'AZIONE")
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
                f"{_clip(status, columns[7][1]):<{columns[7][1]}}",
            ]
        )
        if player.player_index == 0:
            print(f"{HERO_BLUE}{line}{RESET}")
        else:
            print(line)

    print(separator)
    print("-" * 80)
    print("Action log")
    action_log = hero_bot.get_action_log()
    if not action_log:
        print("  - nessuna azione ancora")
    else:
        for action_line in action_log:
            print(f"  - {action_line}")
    print(f"{HERO_BLUE}{hero_decision.summary()}{RESET}")
    print(
        "Click target : "
        f"action={_click_point_text(hero_decision.selected_action_button)} "
        f"amount={_click_point_text(hero_decision.selected_amount_button)}"
    )
    print(f"{ACCENT}{'=' * len(separator)}{RESET}")


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
    table_mapper = TableStateMapper()
    hero_bot = None
    adb_auto_clicker = None
    if ENABLE_HERO_BOT:
        hero_bot = HeroBotBridge(bot_kind=HERO_BOT_KIND, profile_name=HERO_BOT_PROFILE)
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

            if hero_bot is not None:
                hero_decision = hero_bot.process_table(table_state)
                if hero_decision is not None:
                    _print_hero_bot_snapshot(table_state, hero_decision, hero_bot)
                    if adb_auto_clicker is not None:
                        try:
                            adb_auto_clicker.maybe_execute(table_state, hero_decision)
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
