from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    from Impostazioni import PLAYER_STATS_DB_PATH
except ModuleNotFoundError:
    PLAYER_STATS_DB_PATH = Path(__file__).resolve().parent.parent / "player_stats.db"

DEFAULT_DB_PATH = Path(PLAYER_STATS_DB_PATH)

UNKNOWN_PLAYER_PRIORS = {
    "vpip": 0.28,
    "pfr": 0.18,
    "af": 1.50,
    "fold_to_raise": 0.35,
    "fold_to_cbet": 0.35,
    "cbet": 0.55,
    "three_bet": 0.10,
    "fold_to_3bet": 0.45,
    "wtsd": 0.30,
}

PRIOR_WEIGHTS = {
    "hands": 24,
    "fold_to_raise": 12,
    "fold_to_cbet": 10,
    "cbet": 10,
    "three_bet": 12,
    "fold_to_3bet": 10,
    "wtsd": 12,
    "af": 10,
}


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _blend_rate(observed_value: float, sample_size: int, prior_value: float, prior_weight: int) -> float:
    total_weight = max(0, sample_size) + max(0, prior_weight)
    if total_weight <= 0:
        return round(prior_value, 4)
    return round(
        ((observed_value * max(0, sample_size)) + (prior_value * max(0, prior_weight))) / total_weight,
        4,
    )


def _confidence(sample_size: int, target_sample: int) -> float:
    if target_sample <= 0:
        return 1.0
    return round(min(1.0, max(0, sample_size) / target_sample), 4)


@dataclass
class PlayerStats:
    vpip: float = 0.0
    pfr: float = 0.0
    af: float = 0.0
    fold_to_raise: float = 0.0
    fold_to_cbet: float = 0.0
    cbet: float = 0.0
    three_bet: float = 0.0
    fold_to_3bet: float = 0.0
    wtsd: float = 0.0
    position: str = ""
    stack_bb: float = 0.0
    players_in_hand: int = 0
    hands_played: int = 0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, float | str | int]:
        return {
            "vpip": self.vpip,
            "pfr": self.pfr,
            "af": self.af,
            "fold_to_raise": self.fold_to_raise,
            "fold_to_cbet": self.fold_to_cbet,
            "cbet": self.cbet,
            "3bet": self.three_bet,
            "fold_to_3bet": self.fold_to_3bet,
            "wtsd": self.wtsd,
            "position": self.position,
            "stack_bb": self.stack_bb,
            "players_in_hand": self.players_in_hand,
            "hands_played": self.hands_played,
            "confidence": self.confidence,
        }


@dataclass
class PlayerStatsTracker:
    player_name: str
    db_path: Path = DEFAULT_DB_PATH
    save_stack_snapshots: bool = False
    hands_played: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0
    postflop_aggressive_actions: int = 0
    postflop_calls: int = 0
    fold_to_raise_folds: int = 0
    fold_to_raise_opportunities: int = 0
    fold_to_cbet_folds: int = 0
    fold_to_cbet_opportunities: int = 0
    cbet_made: int = 0
    cbet_opportunities: int = 0
    three_bet_made: int = 0
    three_bet_opportunities: int = 0
    fold_to_3bet_folds: int = 0
    fold_to_3bet_opportunities: int = 0
    showdowns: int = 0
    saw_flop: int = 0
    current_position: str = ""
    current_stack_bb: float = 0.0
    current_players_in_hand: int = 0
    _active_hand_id: Optional[int] = field(default=None, init=False, repr=False)
    _hand_state: Dict[str, bool] = field(default_factory=dict, init=False, repr=False)
    _pending_stack_snapshots: list[tuple[int, int, int, float, float, int]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self._ensure_db()
        self._load_existing()

    def _ensure_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS player_stats (
                    player_name TEXT PRIMARY KEY,
                    hands_played INTEGER NOT NULL,
                    vpip_hands INTEGER NOT NULL,
                    pfr_hands INTEGER NOT NULL,
                    postflop_aggressive_actions INTEGER NOT NULL,
                    postflop_calls INTEGER NOT NULL,
                    fold_to_raise_folds INTEGER NOT NULL,
                    fold_to_raise_opportunities INTEGER NOT NULL,
                    fold_to_cbet_folds INTEGER NOT NULL,
                    fold_to_cbet_opportunities INTEGER NOT NULL,
                    cbet_made INTEGER NOT NULL,
                    cbet_opportunities INTEGER NOT NULL,
                    three_bet_made INTEGER NOT NULL,
                    three_bet_opportunities INTEGER NOT NULL,
                    fold_to_3bet_folds INTEGER NOT NULL DEFAULT 0,
                    fold_to_3bet_opportunities INTEGER NOT NULL DEFAULT 0,
                    showdowns INTEGER NOT NULL,
                    saw_flop INTEGER NOT NULL,
                    position TEXT NOT NULL,
                    stack_bb REAL NOT NULL,
                    players_in_hand INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "fold_to_3bet_folds", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "fold_to_3bet_opportunities", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stack_snapshots (
                    player_name TEXT NOT NULL,
                    tournament_id INTEGER NOT NULL,
                    hand_no INTEGER NOT NULL,
                    stack INTEGER NOT NULL,
                    big_blind REAL NOT NULL,
                    stack_bb REAL NOT NULL,
                    players_remaining INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (player_name, tournament_id, hand_no)
                )
                """
            )

    def _ensure_column(self, conn: sqlite3.Connection, column_name: str, column_type: str) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(player_stats)").fetchall()
        }
        if column_name in columns:
            return
        conn.execute(
            f"ALTER TABLE player_stats ADD COLUMN {column_name} {column_type}"
        )

    def _load_existing(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    hands_played,
                    vpip_hands,
                    pfr_hands,
                    postflop_aggressive_actions,
                    postflop_calls,
                    fold_to_raise_folds,
                    fold_to_raise_opportunities,
                    fold_to_cbet_folds,
                    fold_to_cbet_opportunities,
                    cbet_made,
                    cbet_opportunities,
                    three_bet_made,
                    three_bet_opportunities,
                    fold_to_3bet_folds,
                    fold_to_3bet_opportunities,
                    showdowns,
                    saw_flop,
                    position,
                    stack_bb,
                    players_in_hand
                FROM player_stats
                WHERE player_name = ?
                """,
                (self.player_name,),
            ).fetchone()

        if row is None:
            return

        (
            self.hands_played,
            self.vpip_hands,
            self.pfr_hands,
            self.postflop_aggressive_actions,
            self.postflop_calls,
            self.fold_to_raise_folds,
            self.fold_to_raise_opportunities,
            self.fold_to_cbet_folds,
            self.fold_to_cbet_opportunities,
            self.cbet_made,
            self.cbet_opportunities,
            self.three_bet_made,
            self.three_bet_opportunities,
            self.fold_to_3bet_folds,
            self.fold_to_3bet_opportunities,
            self.showdowns,
            self.saw_flop,
            self.current_position,
            self.current_stack_bb,
            self.current_players_in_hand,
        ) = row

    def start_hand(self, hand_id: int, position: str, stack_bb: float, players_in_hand: int) -> None:
        if self._active_hand_id == hand_id:
            self.current_position = position
            self.current_stack_bb = round(stack_bb, 2)
            self.current_players_in_hand = players_in_hand
            return

        self._active_hand_id = hand_id
        self.hands_played += 1
        self.current_position = position
        self.current_stack_bb = round(stack_bb, 2)
        self.current_players_in_hand = players_in_hand
        self._hand_state = {
            "vpip_recorded": False,
            "pfr_recorded": False,
            "opened_preflop": False,
            "fold_to_3bet_recorded": False,
            "cbet_opportunity_recorded": False,
            "faced_cbet_recorded": False,
            "saw_flop_recorded": False,
            "showdown_recorded": False,
        }

    def note_saw_flop(self) -> None:
        if self._hand_state.get("saw_flop_recorded"):
            return
        self.saw_flop += 1
        self._hand_state["saw_flop_recorded"] = True

    def note_showdown(self) -> None:
        if self._hand_state.get("showdown_recorded"):
            return
        self.showdowns += 1
        self._hand_state["showdown_recorded"] = True

    def record_decision(
        self,
        street: str,
        action_kind: str,
        call_amount: int,
        raise_count_before_action: int,
        is_cbet_opportunity: bool = False,
        is_facing_cbet: bool = False,
    ) -> None:
        if street == "preflop":
            voluntarily_put_money = action_kind == "raise" or (
                action_kind == "call" and call_amount > 0
            )
            if voluntarily_put_money and not self._hand_state.get("vpip_recorded"):
                self.vpip_hands += 1
                self._hand_state["vpip_recorded"] = True

            if action_kind == "raise" and not self._hand_state.get("pfr_recorded"):
                self.pfr_hands += 1
                self._hand_state["pfr_recorded"] = True

            if action_kind == "raise" and raise_count_before_action == 0:
                self._hand_state["opened_preflop"] = True

            if action_kind == "raise" and raise_count_before_action == 1:
                self.three_bet_opportunities += 1
                self.three_bet_made += 1

            elif raise_count_before_action == 1:
                self.three_bet_opportunities += 1

            if (
                self._hand_state.get("opened_preflop")
                and raise_count_before_action >= 2
                and not self._hand_state.get("fold_to_3bet_recorded")
            ):
                self.fold_to_3bet_opportunities += 1
                if action_kind == "fold":
                    self.fold_to_3bet_folds += 1
                self._hand_state["fold_to_3bet_recorded"] = True

        if street != "preflop":
            if action_kind == "raise":
                self.postflop_aggressive_actions += 1
            elif action_kind == "call" and call_amount > 0:
                self.postflop_calls += 1

        if raise_count_before_action > 0 and call_amount > 0:
            self.fold_to_raise_opportunities += 1
            if action_kind == "fold":
                self.fold_to_raise_folds += 1

        if is_cbet_opportunity and not self._hand_state.get("cbet_opportunity_recorded"):
            self.cbet_opportunities += 1
            if action_kind == "raise":
                self.cbet_made += 1
            self._hand_state["cbet_opportunity_recorded"] = True

        if is_facing_cbet and not self._hand_state.get("faced_cbet_recorded"):
            self.fold_to_cbet_opportunities += 1
            if action_kind == "fold":
                self.fold_to_cbet_folds += 1
            self._hand_state["faced_cbet_recorded"] = True

    def build_stats(self) -> PlayerStats:
        observed_vpip = _safe_ratio(self.vpip_hands, self.hands_played)
        observed_pfr = _safe_ratio(self.pfr_hands, self.hands_played)
        af = (
            round(self.postflop_aggressive_actions / self.postflop_calls, 4)
            if self.postflop_calls
            else float(self.postflop_aggressive_actions)
        )
        af_samples = self.postflop_aggressive_actions + self.postflop_calls
        observed_fold_to_raise = _safe_ratio(self.fold_to_raise_folds, self.fold_to_raise_opportunities)
        observed_fold_to_cbet = _safe_ratio(self.fold_to_cbet_folds, self.fold_to_cbet_opportunities)
        observed_cbet = _safe_ratio(self.cbet_made, self.cbet_opportunities)
        observed_three_bet = _safe_ratio(self.three_bet_made, self.three_bet_opportunities)
        observed_fold_to_3bet = _safe_ratio(self.fold_to_3bet_folds, self.fold_to_3bet_opportunities)
        observed_wtsd = _safe_ratio(self.showdowns, self.saw_flop)

        return PlayerStats(
            vpip=_blend_rate(observed_vpip, self.hands_played, UNKNOWN_PLAYER_PRIORS["vpip"], PRIOR_WEIGHTS["hands"]),
            pfr=_blend_rate(observed_pfr, self.hands_played, UNKNOWN_PLAYER_PRIORS["pfr"], PRIOR_WEIGHTS["hands"]),
            af=_blend_rate(af, af_samples, UNKNOWN_PLAYER_PRIORS["af"], PRIOR_WEIGHTS["af"]),
            fold_to_raise=_blend_rate(
                observed_fold_to_raise,
                self.fold_to_raise_opportunities,
                UNKNOWN_PLAYER_PRIORS["fold_to_raise"],
                PRIOR_WEIGHTS["fold_to_raise"],
            ),
            fold_to_cbet=_blend_rate(
                observed_fold_to_cbet,
                self.fold_to_cbet_opportunities,
                UNKNOWN_PLAYER_PRIORS["fold_to_cbet"],
                PRIOR_WEIGHTS["fold_to_cbet"],
            ),
            cbet=_blend_rate(
                observed_cbet,
                self.cbet_opportunities,
                UNKNOWN_PLAYER_PRIORS["cbet"],
                PRIOR_WEIGHTS["cbet"],
            ),
            three_bet=_blend_rate(
                observed_three_bet,
                self.three_bet_opportunities,
                UNKNOWN_PLAYER_PRIORS["three_bet"],
                PRIOR_WEIGHTS["three_bet"],
            ),
            fold_to_3bet=_blend_rate(
                observed_fold_to_3bet,
                self.fold_to_3bet_opportunities,
                UNKNOWN_PLAYER_PRIORS["fold_to_3bet"],
                PRIOR_WEIGHTS["fold_to_3bet"],
            ),
            wtsd=_blend_rate(
                observed_wtsd,
                self.saw_flop,
                UNKNOWN_PLAYER_PRIORS["wtsd"],
                PRIOR_WEIGHTS["wtsd"],
            ),
            position=self.current_position,
            stack_bb=self.current_stack_bb,
            players_in_hand=self.current_players_in_hand,
            hands_played=self.hands_played,
            confidence=_confidence(self.hands_played, PRIOR_WEIGHTS["hands"]),
        )

    def record_stack_snapshot(
        self,
        tournament_id: int,
        hand_no: int,
        stack: int,
        big_blind: float,
        players_remaining: int,
    ) -> None:
        if not self.save_stack_snapshots:
            return
        safe_big_blind = float(big_blind) if big_blind else 0.0
        stack_bb = round(stack / safe_big_blind, 2) if safe_big_blind > 0 else 0.0
        self._pending_stack_snapshots.append(
            (
                tournament_id,
                hand_no,
                int(stack),
                safe_big_blind,
                stack_bb,
                int(players_remaining),
            )
        )

    def save_to_db(self) -> None:
        stats = self.build_stats()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO player_stats (
                    player_name,
                    hands_played,
                    vpip_hands,
                    pfr_hands,
                    postflop_aggressive_actions,
                    postflop_calls,
                    fold_to_raise_folds,
                    fold_to_raise_opportunities,
                    fold_to_cbet_folds,
                    fold_to_cbet_opportunities,
                    cbet_made,
                    cbet_opportunities,
                    three_bet_made,
                    three_bet_opportunities,
                    fold_to_3bet_folds,
                    fold_to_3bet_opportunities,
                    showdowns,
                    saw_flop,
                    position,
                    stack_bb,
                    players_in_hand,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_name) DO UPDATE SET
                    hands_played=excluded.hands_played,
                    vpip_hands=excluded.vpip_hands,
                    pfr_hands=excluded.pfr_hands,
                    postflop_aggressive_actions=excluded.postflop_aggressive_actions,
                    postflop_calls=excluded.postflop_calls,
                    fold_to_raise_folds=excluded.fold_to_raise_folds,
                    fold_to_raise_opportunities=excluded.fold_to_raise_opportunities,
                    fold_to_cbet_folds=excluded.fold_to_cbet_folds,
                    fold_to_cbet_opportunities=excluded.fold_to_cbet_opportunities,
                    cbet_made=excluded.cbet_made,
                    cbet_opportunities=excluded.cbet_opportunities,
                    three_bet_made=excluded.three_bet_made,
                    three_bet_opportunities=excluded.three_bet_opportunities,
                    fold_to_3bet_folds=excluded.fold_to_3bet_folds,
                    fold_to_3bet_opportunities=excluded.fold_to_3bet_opportunities,
                    showdowns=excluded.showdowns,
                    saw_flop=excluded.saw_flop,
                    position=excluded.position,
                    stack_bb=excluded.stack_bb,
                    players_in_hand=excluded.players_in_hand,
                    updated_at=excluded.updated_at
                """,
                (
                    self.player_name,
                    self.hands_played,
                    self.vpip_hands,
                    self.pfr_hands,
                    self.postflop_aggressive_actions,
                    self.postflop_calls,
                    self.fold_to_raise_folds,
                    self.fold_to_raise_opportunities,
                    self.fold_to_cbet_folds,
                    self.fold_to_cbet_opportunities,
                    self.cbet_made,
                    self.cbet_opportunities,
                    self.three_bet_made,
                    self.three_bet_opportunities,
                    self.fold_to_3bet_folds,
                    self.fold_to_3bet_opportunities,
                    self.showdowns,
                    self.saw_flop,
                    stats.position,
                    stats.stack_bb,
                    stats.players_in_hand,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if self._pending_stack_snapshots:
                timestamp = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    """
                    INSERT INTO stack_snapshots (
                        player_name,
                        tournament_id,
                        hand_no,
                        stack,
                        big_blind,
                        stack_bb,
                        players_remaining,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_name, tournament_id, hand_no) DO UPDATE SET
                        stack=excluded.stack,
                        big_blind=excluded.big_blind,
                        stack_bb=excluded.stack_bb,
                        players_remaining=excluded.players_remaining,
                        updated_at=excluded.updated_at
                    """,
                    [
                        (
                            self.player_name,
                            tournament_id,
                            hand_no,
                            stack,
                            big_blind,
                            stack_bb,
                            players_remaining,
                            timestamp,
                        )
                        for (
                            tournament_id,
                            hand_no,
                            stack,
                            big_blind,
                            stack_bb,
                            players_remaining,
                        ) in self._pending_stack_snapshots
                    ],
                )
                self._pending_stack_snapshots.clear()
