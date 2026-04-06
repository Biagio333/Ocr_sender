import json
from pathlib import Path
import sqlite3


class PacketStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS packets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_packets_timestamp
                ON packets(timestamp, id)
                """
            )

    def save_payload(self, payload: dict) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False)
        payload_timestamp = payload.get("timestamp")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO packets(timestamp, payload_json)
                VALUES(?, ?)
                """,
                (payload_timestamp, payload_json),
            )
            packet_id = cursor.lastrowid

        return f"{self.db_path}#{packet_id}"


class HeroDecisionStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hero_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    payload_timestamp INTEGER,
                    hand_id INTEGER,
                    street TEXT,
                    position TEXT,
                    hero_cards TEXT,
                    board_cards TEXT,
                    hero_stack INTEGER,
                    hero_bet INTEGER,
                    call_amount INTEGER,
                    min_raise_to INTEGER,
                    max_raise_to INTEGER,
                    action_kind TEXT NOT NULL,
                    action_amount INTEGER,
                    source_action_player INTEGER,
                    source_action_kind TEXT,
                    has_red_action_area INTEGER,
                    red_action_area_avg_red REAL,
                    available_actions_json TEXT,
                    amount_buttons_json TEXT,
                    selected_action_button_json TEXT,
                    selected_amount_button_json TEXT,
                    payload_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hero_decisions_hand_street
                ON hero_decisions(hand_id, street, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hero_decisions_timestamp
                ON hero_decisions(payload_timestamp, id)
                """
            )

    def save_decision(self, decision_row: dict) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hero_decisions(
                    payload_timestamp,
                    hand_id,
                    street,
                    position,
                    hero_cards,
                    board_cards,
                    hero_stack,
                    hero_bet,
                    call_amount,
                    min_raise_to,
                    max_raise_to,
                    action_kind,
                    action_amount,
                    source_action_player,
                    source_action_kind,
                    has_red_action_area,
                    red_action_area_avg_red,
                    available_actions_json,
                    amount_buttons_json,
                    selected_action_button_json,
                    selected_amount_button_json,
                    payload_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_row.get("payload_timestamp"),
                    decision_row.get("hand_id"),
                    decision_row.get("street"),
                    decision_row.get("position"),
                    decision_row.get("hero_cards"),
                    decision_row.get("board_cards"),
                    decision_row.get("hero_stack"),
                    decision_row.get("hero_bet"),
                    decision_row.get("call_amount"),
                    decision_row.get("min_raise_to"),
                    decision_row.get("max_raise_to"),
                    decision_row.get("action_kind"),
                    decision_row.get("action_amount"),
                    decision_row.get("source_action_player"),
                    decision_row.get("source_action_kind"),
                    1 if decision_row.get("has_red_action_area") else 0,
                    decision_row.get("red_action_area_avg_red"),
                    json.dumps(decision_row.get("available_actions", []), ensure_ascii=False),
                    json.dumps(decision_row.get("amount_buttons", []), ensure_ascii=False),
                    json.dumps(decision_row.get("selected_action_button"), ensure_ascii=False),
                    json.dumps(decision_row.get("selected_amount_button"), ensure_ascii=False),
                    json.dumps(decision_row.get("payload", {}), ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)


def load_payloads_from_path(path: str | Path) -> list[dict]:
    source_path = Path(path)
    if source_path.suffix.lower() == ".db":
        return load_payloads_from_database(source_path)
    if source_path.is_dir():
        return load_payloads_from_directory(source_path)
    return _load_payloads_from_file(source_path)


def load_payloads_from_database(db_path: str | Path) -> list[dict]:
    source_path = Path(db_path)
    if not source_path.exists():
        return []

    with sqlite3.connect(source_path) as conn:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM packets
            ORDER BY
                CASE WHEN timestamp IS NULL THEN 1 ELSE 0 END,
                timestamp,
                id
            """
        ).fetchall()

    payloads: list[dict] = []
    for (payload_json,) in rows:
        parsed = json.loads(payload_json)
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def load_payloads_from_directory(directory: str | Path) -> list[dict]:
    base_dir = Path(directory)
    payloads: list[dict] = []
    for file_path in sorted(base_dir.glob("*.json")):
        payloads.extend(_load_payloads_from_file(file_path))
    return payloads


def _load_payloads_from_file(file_path: Path) -> list[dict]:
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        payloads = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            payloads.append(json.loads(line))
        return payloads

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []
