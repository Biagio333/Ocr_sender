import json


TYPE_COLORS = {
    "card": (0, 220, 0),
    "covered_card": (0, 140, 255),
    "dealer_button": (255, 220, 0),
    "ocr": (255, 255, 255),
}


def get_table(data: dict) -> dict:
    return data.get("table", {}) or {}


def get_players(data: dict) -> list[dict]:
    return data.get("players", []) or []


def get_table_cards(data: dict) -> list[dict]:
    table = get_table(data)
    return table.get("board_cards", data.get("cards", [])) or []


def get_table_available_actions(data: dict) -> list[dict]:
    table = get_table(data)
    return table.get("available_actions", []) or []


def get_table_amount_buttons(data: dict) -> list[dict]:
    table = get_table(data)
    return table.get("amount_buttons", []) or []


def get_table_covered_cards(data: dict) -> list[dict]:
    table = get_table(data)
    if "covered_cards" in table:
        return table.get("covered_cards", []) or []

    cards = []
    for player in get_players(data):
        card = player.get("covered_card")
        if isinstance(card, dict) and card:
            cards.append(card)
    if cards:
        return cards
    return data.get("covered_cards", []) or []


def get_table_dealer_buttons(data: dict) -> list[dict]:
    table = get_table(data)
    if "dealer_buttons" in table:
        return table.get("dealer_buttons", []) or []

    buttons = []
    for player in get_players(data):
        button = player.get("dealer_button")
        if isinstance(button, dict) and button:
            buttons.append(button)
    if buttons:
        return buttons
    return data.get("dealer_buttons", []) or []


def sanitize_text(text) -> str:
    return str(text).replace("â‚¬", "E")


def payload_summary(payload: dict) -> str:
    return (
        f"players={len(get_players(payload))}, "
        f"cards={len(get_table_cards(payload))}, "
        f"actions={len(get_table_available_actions(payload))}, "
        f"amount_btns={len(get_table_amount_buttons(payload))}, "
        f"covered={len(get_table_covered_cards(payload))}, "
        f"dealer={len(get_table_dealer_buttons(payload))}"
    )


def pretty_payload(payload: dict) -> str:
    return sanitize_text(json.dumps(payload, indent=2, ensure_ascii=False))
