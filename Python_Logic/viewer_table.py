import cv2
import numpy as np

from payload_utils import sanitize_text
from table_models import TableBase
from viewer import IMG_H, IMG_W, PREVIEW_SCALE, SIDEBAR_WIDTH


TABLE_BG = (18, 50, 24)
PLAYER_BOX = (42, 42, 42)
PLAYER_BORDER = (90, 160, 255)
TEXT_MAIN = (255, 255, 255)
TEXT_DIM = (180, 180, 180)
TEXT_ACCENT = (0, 220, 255)
ACTION_COLORS = {
    "check": (80, 220, 255),
    "bet": (0, 200, 120),
    "call": (0, 170, 255),
    "raise": (0, 120, 255),
    "fold": (120, 120, 120),
    "waiting": (180, 180, 180),
}

PLAYER_LAYOUTS = {
    0: (390, 1880, 300, 150),
    1: (60, 1130, 280, 140),
    2: (80, 640, 280, 140),
    3: (390, 270, 300, 140),
    4: (710, 640, 280, 140),
    5: (730, 1130, 280, 140),
}


def _format_amount(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def draw_table_view(table: TableBase) -> np.ndarray:
    canvas = np.zeros((IMG_H, IMG_W + SIDEBAR_WIDTH, 3), dtype=np.uint8)
    canvas[:, :] = (8, 8, 8)

    table_area = canvas[:, :IMG_W]
    sidebar = canvas[:, IMG_W:]
    table_area[:, :] = TABLE_BG

    cv2.ellipse(
        table_area,
        (IMG_W // 2, IMG_H // 2),
        (330, 520),
        0,
        0,
        360,
        (32, 96, 40),
        -1,
    )
    cv2.ellipse(
        table_area,
        (IMG_W // 2, IMG_H // 2),
        (350, 540),
        0,
        0,
        360,
        (90, 140, 90),
        4,
    )

    _draw_board_cards(table_area, table)
    _draw_players(table_area, table)
    _draw_sidebar(sidebar, table)
    return canvas


def show_table_view(table: TableBase):
    img = draw_table_view(table)
    if PREVIEW_SCALE != 1.0:
        img = cv2.resize(
            img,
            None,
            fx=PREVIEW_SCALE,
            fy=PREVIEW_SCALE,
            interpolation=cv2.INTER_AREA,
        )

    cv2.imshow("Table Classes", img)
    cv2.waitKey(1)


def _draw_players(img: np.ndarray, table: TableBase):
    for player in table.players:
        x, y, w, h = PLAYER_LAYOUTS.get(player.player_index, (30, 30, 260, 120))
        cv2.rectangle(img, (x, y), (x + w, y + h), PLAYER_BOX, -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), PLAYER_BORDER, 2)

        action_color = ACTION_COLORS.get(player.inferred_action, TEXT_DIM)
        name = sanitize_text(player.name).strip() or f"P{player.player_index}"
        stack = player.stack_text.strip() or "-"
        bet = _format_amount(player.bet_amount)
        action = player.inferred_action.upper()
        badges = []
        if player.has_dealer_button:
            badges.append("D")
        if player.has_covered_card:
            badges.append("IN")
        badge_text = " ".join(badges) or "-"

        cv2.putText(img, f"P{player.player_index} {name}", (x + 12, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEXT_MAIN, 2, cv2.LINE_AA)
        cv2.putText(img, f"stack: {sanitize_text(stack)}", (x + 12, y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, TEXT_DIM, 1, cv2.LINE_AA)
        cv2.putText(img, f"bet: {bet}", (x + 12, y + 84), cv2.FONT_HERSHEY_SIMPLEX, 0.58, TEXT_DIM, 1, cv2.LINE_AA)
        cv2.putText(img, f"flags: {badge_text}", (x + 12, y + 110), cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT_DIM, 1, cv2.LINE_AA)
        cv2.putText(img, action, (x + 150, y + 112), cv2.FONT_HERSHEY_SIMPLEX, 0.65, action_color, 2, cv2.LINE_AA)


def _draw_board_cards(img: np.ndarray, table: TableBase):
    start_x = 310
    y = 1030
    card_w = 80
    card_h = 110
    gap = 18

    for index, card in enumerate(table.board_cards):
        x = start_x + index * (card_w + gap)
        cv2.rectangle(img, (x, y), (x + card_w, y + card_h), (245, 245, 245), -1)
        cv2.rectangle(img, (x, y), (x + card_w, y + card_h), (60, 60, 60), 2)
        label = sanitize_text(card.get("name", "")).upper() or "?"
        cv2.putText(img, label, (x + 12, y + 65), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (20, 20, 20), 2, cv2.LINE_AA)

    if table.hero_cards:
        hero_y = 1180
        for index, card in enumerate(table.hero_cards):
            x = 430 + index * (card_w + 24)
            cv2.rectangle(img, (x, hero_y), (x + card_w, hero_y + card_h), (220, 245, 255), -1)
            cv2.rectangle(img, (x, hero_y), (x + card_w, hero_y + card_h), (60, 60, 60), 2)
            label = sanitize_text(card.get("name", "")).upper() or "?"
            cv2.putText(img, label, (x + 12, hero_y + 65), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (20, 20, 20), 2, cv2.LINE_AA)


def _draw_sidebar(sidebar: np.ndarray, table: TableBase):
    sidebar[:, :] = (22, 22, 22)
    y = 42

    def put(line: str, color=TEXT_MAIN, scale=0.7, thickness=2):
        nonlocal y
        cv2.putText(sidebar, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)
        y += 30

    put("Table Classes", TEXT_ACCENT, 0.9, 2)
    put(f"timestamp: {table.timestamp}", TEXT_DIM, 0.5, 1)
    put(f"street: {table.street}", TEXT_MAIN, 0.7, 2)
    put(f"pot: {sanitize_text(table.pot_text) or '-'}", TEXT_MAIN, 0.65, 2)
    put(f"pot_amount: {table.pot_amount}", TEXT_DIM, 0.6, 1)
    put(f"players: {len(table.players)}", TEXT_MAIN, 0.65, 2)
    put(f"board: {len(table.board_cards)}", TEXT_MAIN, 0.65, 2)
    put(f"hero: {len(table.hero_cards)}", TEXT_MAIN, 0.65, 2)

    y += 12
    put("Actions", TEXT_ACCENT, 0.85, 2)
    for player in table.players:
        action_color = ACTION_COLORS.get(player.inferred_action, TEXT_DIM)
        name = sanitize_text(player.name).strip() or f"P{player.player_index}"
        put(f"P{player.player_index} {name}: {player.inferred_action}", action_color, 0.6, 2)
