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
        params = (
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
        )
        sql = """
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
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(sql, params)
                return int(cursor.lastrowid)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            self._ensure_schema()
            with self._connect() as conn:
                cursor = conn.execute(sql, params)
                return int(cursor.lastrowid)


class HandHistoryStore:
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
                CREATE TABLE IF NOT EXISTS hand_history (
                    hand_id INTEGER PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    first_payload_timestamp INTEGER,
                    last_payload_timestamp INTEGER,
                    street TEXT,
                    hero_position TEXT,
                    hero_cards TEXT,
                    board_cards TEXT,
                    hero_stack INTEGER,
                    hero_bet INTEGER,
                    pot_amount REAL,
                    hero_action_kind TEXT,
                    hero_action_amount INTEGER,
                    source_action_player INTEGER,
                    source_action_kind TEXT,
                    winner_seat INTEGER,
                    winner_name TEXT,
                    payload_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hand_history_last_payload
                ON hand_history(last_payload_timestamp, hand_id)
                """
            )

    def upsert_hand(self, hand_row: dict) -> int:
        hand_id = hand_row.get("hand_id")
        if hand_id is None:
            raise ValueError("hand_id is required")

        params = (
            hand_id,
            hand_row.get("first_payload_timestamp"),
            hand_row.get("last_payload_timestamp"),
            hand_row.get("street"),
            hand_row.get("hero_position"),
            hand_row.get("hero_cards"),
            hand_row.get("board_cards"),
            hand_row.get("hero_stack"),
            hand_row.get("hero_bet"),
            hand_row.get("pot_amount"),
            hand_row.get("hero_action_kind"),
            hand_row.get("hero_action_amount"),
            hand_row.get("source_action_player"),
            hand_row.get("source_action_kind"),
            hand_row.get("winner_seat"),
            hand_row.get("winner_name"),
            json.dumps(hand_row.get("payload", {}), ensure_ascii=False),
        )
        sql = """
            INSERT INTO hand_history(
                hand_id,
                first_payload_timestamp,
                last_payload_timestamp,
                street,
                hero_position,
                hero_cards,
                board_cards,
                hero_stack,
                hero_bet,
                pot_amount,
                hero_action_kind,
                hero_action_amount,
                source_action_player,
                source_action_kind,
                winner_seat,
                winner_name,
                payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hand_id) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP,
                first_payload_timestamp = COALESCE(hand_history.first_payload_timestamp, excluded.first_payload_timestamp),
                last_payload_timestamp = COALESCE(excluded.last_payload_timestamp, hand_history.last_payload_timestamp),
                street = CASE
                    WHEN excluded.street IS NULL OR excluded.street = '' THEN hand_history.street
                    WHEN hand_history.street IS NULL OR hand_history.street = '' THEN excluded.street
                    WHEN excluded.street = 'river' THEN excluded.street
                    WHEN excluded.street = 'turn' AND hand_history.street IN ('preflop', 'flop', 'unknown') THEN excluded.street
                    WHEN excluded.street = 'flop' AND hand_history.street IN ('preflop', 'unknown') THEN excluded.street
                    WHEN excluded.street = 'preflop' AND hand_history.street = 'unknown' THEN excluded.street
                    ELSE hand_history.street
                END,
                hero_position = CASE
                    WHEN excluded.hero_position IS NOT NULL AND excluded.hero_position != '' THEN excluded.hero_position
                    ELSE hand_history.hero_position
                END,
                hero_cards = CASE
                    WHEN excluded.hero_cards IS NOT NULL AND excluded.hero_cards != '[]' THEN excluded.hero_cards
                    ELSE hand_history.hero_cards
                END,
                board_cards = CASE
                    WHEN excluded.board_cards IS NOT NULL AND excluded.board_cards != '[]' THEN excluded.board_cards
                    ELSE hand_history.board_cards
                END,
                hero_stack = COALESCE(excluded.hero_stack, hand_history.hero_stack),
                hero_bet = COALESCE(excluded.hero_bet, hand_history.hero_bet),
                pot_amount = COALESCE(excluded.pot_amount, hand_history.pot_amount),
                hero_action_kind = COALESCE(excluded.hero_action_kind, hand_history.hero_action_kind),
                hero_action_amount = COALESCE(excluded.hero_action_amount, hand_history.hero_action_amount),
                source_action_player = COALESCE(excluded.source_action_player, hand_history.source_action_player),
                source_action_kind = COALESCE(excluded.source_action_kind, hand_history.source_action_kind),
                winner_seat = COALESCE(excluded.winner_seat, hand_history.winner_seat),
                winner_name = CASE
                    WHEN excluded.winner_name IS NOT NULL AND excluded.winner_name != '' THEN excluded.winner_name
                    ELSE hand_history.winner_name
                END,
                payload_json = excluded.payload_json
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            self._ensure_schema()
            with self._connect() as conn:
                conn.execute(sql, params)
        return int(hand_id)


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
