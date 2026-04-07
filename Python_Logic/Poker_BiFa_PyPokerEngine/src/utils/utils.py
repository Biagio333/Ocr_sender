import math
import random
import time
from collections import Counter
from pathlib import Path
import sys

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

try:
    from bot.negreanu_bot_V2.negreanu_bot_V2 import  BotNegreanu_V2 as BotNegreanuV2
    from bot.bot_biagio.bot_biagio import BotBiagio
    from bot.manual_bot.manual_bot import ManualBot
    from bot.negreanu_bot.negreanu_bot import BotNegreanu as BotNegreanuV1
except ModuleNotFoundError:
    src_root = Path(__file__).resolve().parents[1]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from bot.negreanu_bot_V2.negreanu_bot_V2 import BotNegreanu_V2 as BotNegreanuV2
    from bot.bot_biagio.bot_biagio import BotBiagio
    from bot.manual_bot.manual_bot import ManualBot
    from bot.negreanu_bot.negreanu_bot import BotNegreanu as BotNegreanuV1


HAND_LABEL_TRANSLATIONS = {
    "High card": "carta alta",
    "One pair": "coppia",
    "Two pair": "doppia coppia",
    "Three of a kind": "tris",
    "Straight": "scala",
    "Flush": "colore",
    "Full house": "full",
    "Four of a kind": "poker",
    "Straight flush": "scala colore",
}

BLIND_STRUCTURE = [
    (10, 20),
    (15, 30),
    (25, 50),
    (50, 100),
    (75, 150),
    (100, 200),
    (150, 300),
    (200, 400),
    (300, 600),
    (400, 800),
    (600, 1200),
    (800, 1600),
    (1000, 2000),
]

LEVEL_DURATION_MINUTES = 500000000000000000
PLAYER_RESPONSE_TIME_SECONDS = 4

POSITION_NAMES_BY_PLAYER_COUNT = {
    2: ["BTN", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
}


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "No module named 'cv2'. Install it with "
            "`python3 -m pip install opencv-python` or "
            "`python3 -m pip install -r requirements.txt`."
        )
    return cv2


def _build_negreanu_v2_lineup():
    fixed_bots = [
        BotNegreanuV2(profile_name="tag_grinder"),
        BotNegreanuV2(profile_name="balanced_reg"),
        BotNegreanuV2(profile_name="live_exploiter"),
        BotNegreanuV2(profile_name="threebet_hunter"),
        BotNegreanuV2(profile_name="sticky_postflop"),
        BotNegreanuV2(profile_name="calling_station_punisher"),
    ]

    fixed_bots[0].name = "NV2 Tag Grinder"
    fixed_bots[1].name = "NV2 Balanced Reg"
    fixed_bots[2].name = "NV2 Live Exploiter"
    fixed_bots[3].name = "NV2 Threebet Hunter"
    fixed_bots[4].name = "NV2 Sticky Postflop"
    fixed_bots[5].name = "NV2 Station Punisher"
    return fixed_bots



def build_tournament_bots():
    bots = _build_negreanu_v2_lineup()

    return bots


def build_manual_tournament_bots():
    bots = [ManualBot()]
    bots.extend(_build_negreanu_v2_lineup()[:-1])
    return bots


def format_card(card):
    card_text = str(card)
    if "(" in card_text and ")" in card_text:
        return card_text.split("(")[-1].rstrip(")")
    return card_text


def format_cards(cards):
    return " ".join(format_card(card) for card in cards)


def translate_hand_label(hand_text):
    for english, italian in HAND_LABEL_TRANSLATIONS.items():
        if hand_text.startswith(english):
            return italian
    return hand_text


def describe_hand(state, local_index):
    if not state.board_cards:
        hole_cards = state.hole_cards[local_index]
        if len(hole_cards) == 2 and getattr(hole_cards[0], "rank", None) == getattr(hole_cards[1], "rank", None):
            return "coppia servita"
        return "-"

    try:
        hand = state.get_hand(local_index, 0, 0)
    except Exception:
        return "-"

    if hand is None:
        return "-"

    return translate_hand_label(str(hand).split(" (", 1)[0])


def street_name(state):
    board_len = len(state.board_cards)
    if board_len == 0:
        return "preflop"
    if board_len == 3:
        return "flop"
    if board_len == 4:
        return "turn"
    if board_len == 5:
        return "river"
    return f"board_{board_len}"


def get_blind_level(
    elapsed_seconds: float,
    level_duration_minutes: float = LEVEL_DURATION_MINUTES,
):
    level_duration_seconds = max(60.0, level_duration_minutes * 60.0)
    level = int(max(0.0, elapsed_seconds) // level_duration_seconds)
    level = min(level, len(BLIND_STRUCTURE) - 1)
    return BLIND_STRUCTURE[level]


def position_names(num_players):
    if num_players <= 0:
        return []

    if num_players == 1:
        return ["BTN"]

    max_supported_players = max(POSITION_NAMES_BY_PLAYER_COUNT)
    capped_player_count = min(num_players, max_supported_players)
    return POSITION_NAMES_BY_PLAYER_COUNT[capped_player_count][:]


def build_positions_map(active_players, button_global_index):
    if not active_players or button_global_index not in active_players:
        return {}

    button_idx = active_players.index(button_global_index)
    ordered_from_button = active_players[button_idx:] + active_players[:button_idx]
    labels = position_names(len(active_players))
    return {
        player_index: labels[idx]
        for idx, player_index in enumerate(ordered_from_button)
        if idx < len(labels)
    }


def build_performance_report(
    bot_names,
    winner_names,
    runner_up_names,
    total_profit_by_name,
    total_profit_sq_by_name,
    tournaments_played,
):
    if tournaments_played <= 0:
        return []

    winner_counts = Counter(winner_names)
    runner_up_counts = Counter(runner_up_names)
    report_rows = []

    for name in bot_names:
        wins = winner_counts.get(name, 0)
        runner_ups = runner_up_counts.get(name, 0)
        itm_count = wins + runner_ups
        total_profit = float(total_profit_by_name.get(name, 0.0))
        avg_profit = total_profit / tournaments_played
        avg_sq_profit = float(total_profit_sq_by_name.get(name, 0.0)) / tournaments_played
        profit_variance = max(0.0, avg_sq_profit - (avg_profit ** 2))
        profit_stddev = math.sqrt(profit_variance)

        report_rows.append({
            "name": name,
            "wins": wins,
            "runner_ups": runner_ups,
            "itm_count": itm_count,
            "win_rate": wins / tournaments_played,
            "itm_rate": itm_count / tournaments_played,
            "avg_profit": avg_profit,
            "profit_stddev": profit_stddev,
            "total_profit": total_profit,
        })

    report_rows.sort(
        key=lambda row: (
            row["avg_profit"],
            row["win_rate"],
            row["itm_rate"],
            row["total_profit"],
        ),
        reverse=True,
    )
    return report_rows


def save_adb_screenshot(img_full, save_screenshot_dir, saved_screenshot_count):
    cv2_module = _require_cv2()
    if img_full is None:
        return saved_screenshot_count

    ts = int(time.time() * 1000)
    file_name = f"adb_{ts}_{saved_screenshot_count:06d}.png"
    file_path = str(Path(save_screenshot_dir) / file_name)

    if cv2_module.imwrite(file_path, img_full):
        saved_screenshot_count += 1
        print(f"Screenshot salvato: {file_path}")
    else:
        print(f"Errore salvataggio screenshot: {file_path}")

    return saved_screenshot_count


def load_scraper_frame(
    *,
    screenshot_type,
    ocr,
    display_scale,
    save_screenshot_dir,
    debug_start_frame_number,
    saved_screenshot_count,
    count,
):
    cv2_module = _require_cv2()
    screenshot_mode = getattr(screenshot_type, "name", str(screenshot_type))

    if screenshot_mode == "IMMAGE_SAVED":
        from scraper.ocr_utils import list_images

        list_img = list_images(
            folder=save_screenshot_dir,
            min_frame_number=debug_start_frame_number,
        )
        if not list_img:
            print(
                f"Nessuna immagine trovata in '{save_screenshot_dir}' "
                f"dal frame {debug_start_frame_number:06d} in poi"
            )
            time.sleep(0.5)
            return {
                "img": None,
                "img_full": None,
                "count": count,
                "saved_screenshot_count": saved_screenshot_count,
                "skipped": True,
            }

        count = (count + 1) % len(list_img)
        print(f"Processing image: {list_img[count]}")
        img = cv2_module.imread(list_img[count])
        if img is None:
            print(f"Errore lettura immagine: {list_img[count]}")
            return {
                "img": None,
                "img_full": None,
                "count": count,
                "saved_screenshot_count": saved_screenshot_count,
                "skipped": True,
            }

        img = cv2_module.resize(img, (0, 0), fx=display_scale, fy=display_scale)
        return {
            "img": img,
            "img_full": None,
            "count": count,
            "saved_screenshot_count": saved_screenshot_count,
            "skipped": False,
        }

    if screenshot_mode == "ADB":
        img_full, img, _ = ocr.get_next_frame()
        if img is None:
            time.sleep(0.1)
            return {
                "img": None,
                "img_full": img_full,
                "count": count,
                "saved_screenshot_count": saved_screenshot_count,
                "skipped": True,
            }

        print("Frames nel buffer:", ocr.buffer_size())

        return {
            "img": img,
            "img_full": img_full,
            "count": count,
            "saved_screenshot_count": saved_screenshot_count,
            "skipped": False,
        }

    raise ValueError(f"SCRENSHOT_TYPE non supportato: {screenshot_type}")
