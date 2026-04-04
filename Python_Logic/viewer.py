import cv2
import numpy as np

from payload_utils import (
    TYPE_COLORS,
    get_players,
    get_table,
    get_table_cards,
    get_table_covered_cards,
    get_table_dealer_buttons,
    sanitize_text,
)


IMG_W = 1080
IMG_H = 2400
PREVIEW_SCALE = 0.45
SIDEBAR_WIDTH = 520


def draw_rect_item(img: np.ndarray, item: dict, color, label_key: str = "name"):
    text = sanitize_text(item.get(label_key, ""))
    rect = item.get("rect", {})

    left = int(rect.get("left", 0))
    top = int(rect.get("top", 0))
    right = int(rect.get("right", 0))
    bottom = int(rect.get("bottom", 0))

    cv2.rectangle(img, (left, top), (right, bottom), color, 2)

    text_y = top - 8
    if text_y < 20:
        text_y = bottom + 20

    if text:
        cv2.putText(
            img,
            text,
            (left, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )


def draw_results(data: dict) -> np.ndarray:
    table_img = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)

    for item in get_table_cards(data):
        draw_rect_item(table_img, item, TYPE_COLORS["card"])

    for item in get_table_covered_cards(data):
        draw_rect_item(table_img, item, TYPE_COLORS["covered_card"])

    for item in get_table_dealer_buttons(data):
        draw_rect_item(table_img, item, TYPE_COLORS["dealer_button"])

    processing_ms = data.get("processing_elapsed_ms")
    if processing_ms is not None:
        cv2.putText(
            table_img,
            f"Table: {processing_ms} ms",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    sidebar = np.zeros((IMG_H, SIDEBAR_WIDTH, 3), dtype=np.uint8)
    draw_sidebar(sidebar, data)

    return np.hstack([table_img, sidebar])


def show_image(img: np.ndarray):
    if PREVIEW_SCALE != 1.0:
        img = cv2.resize(
            img,
            None,
            fx=PREVIEW_SCALE,
            fy=PREVIEW_SCALE,
            interpolation=cv2.INTER_AREA,
        )

    cv2.imshow("OCR Rectangles", img)
    cv2.waitKey(1)


def draw_sidebar(sidebar: np.ndarray, data: dict):
    y = 40
    line_h = 30
    left = 20

    def put(line: str, color=(255, 255, 255), scale=0.75, thickness=2):
        nonlocal y
        cv2.putText(
            sidebar,
            line,
            (left, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
        y += line_h

    put("Socket summary", (0, 200, 255), 0.9, 2)
    put(f"timestamp: {data.get('timestamp', '-')}", (180, 180, 180), 0.55, 1)

    processing_ms = data.get("processing_elapsed_ms")
    if processing_ms is not None:
        put(f"table ms: {processing_ms}", (255, 255, 255), 0.8, 2)

    put(f"players: {len(get_players(data))}", (180, 220, 255))
    put(f"cards: {len(get_table_cards(data))}", TYPE_COLORS["card"])
    put(f"covered: {len(get_table_covered_cards(data))}", TYPE_COLORS["covered_card"])
    put(f"dealer: {len(get_table_dealer_buttons(data))}", TYPE_COLORS["dealer_button"])

    y += 10
    put("Cards", (0, 200, 255), 0.9, 2)
    for item in get_table_cards(data):
        put(f"- {item.get('name', '')}", TYPE_COLORS["card"], 0.7, 2)

    y += 10
    put("Pot", (0, 200, 255), 0.9, 2)
    pot_text = sanitize_text(get_table(data).get("pot", "")).strip() or "-"
    put(f"- {pot_text}", (200, 200, 255), 0.7, 2 if pot_text != "-" else 1)

    y += 10
    put("Covered", (0, 200, 255), 0.9, 2)
    covered = get_table_covered_cards(data)
    if covered:
        for idx, item in enumerate(covered, start=1):
            put(f"- {idx}: {item.get('name', '')}", TYPE_COLORS["covered_card"], 0.7, 2)
    else:
        put("- none", (180, 180, 180), 0.7, 1)

    y += 10
    put("Dealer", (0, 200, 255), 0.9, 2)
    dealer = get_table_dealer_buttons(data)
    if dealer:
        for item in dealer:
            src = item.get("source_label", "")
            put(f"- {item.get('name', '')} {src}".strip(), TYPE_COLORS["dealer_button"], 0.7, 2)
    else:
        put("- none", (180, 180, 180), 0.7, 1)

    y += 10
    put("Players", (0, 200, 255), 0.9, 2)
    players = get_players(data)
    if players:
        for player in players:
            idx = player.get("player_index", "?")
            name = sanitize_text(player.get("name", "")).strip() or "-"
            stack = sanitize_text(player.get("stack", "")).strip() or "-"
            bet = sanitize_text(player.get("bet", "")).strip() or "-"
            covered_count = 1 if isinstance(player.get("covered_card"), dict) and player.get("covered_card") else 0
            dealer_count = 1 if isinstance(player.get("dealer_button"), dict) and player.get("dealer_button") else 0
            put(f"P{idx} {name}", (255, 255, 255), 0.68, 2)
            put(f"  stack:{stack} bet:{bet}", (200, 200, 200), 0.58, 1)
            put(f"  covered:{covered_count} dealer:{dealer_count}", (170, 170, 170), 0.58, 1)
    else:
        put("- none", (180, 180, 180), 0.7, 1)
