from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

from player_stats import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grafica l'andamento dello stack di un player mano per mano."
    )
    parser.add_argument("--player", required=True, help="Nome del player da analizzare.")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path del database SQLite con gli snapshot.",
    )
    parser.add_argument(
        "--tournament",
        type=int,
        help="Se valorizzato, mostra solo quel torneo.",
    )
    parser.add_argument(
        "--output",
        help="Salva il grafico su file invece di aprirlo a schermo.",
    )
    return parser.parse_args()


def fetch_snapshots(
    db_path: Path,
    player_name: str,
    tournament_id: int | None = None,
) -> list[tuple[int, int, int, float, float, int]]:
    query = """
        SELECT
            tournament_id,
            hand_no,
            stack,
            big_blind,
            stack_bb,
            players_remaining
        FROM stack_snapshots
        WHERE player_name = ?
    """
    params: list[object] = [player_name]

    if tournament_id is not None:
        query += " AND tournament_id = ?"
        params.append(tournament_id)

    query += " ORDER BY tournament_id, hand_no"

    with sqlite3.connect(db_path) as conn:
        return conn.execute(query, params).fetchall()


def group_by_tournament(
    rows: list[tuple[int, int, int, float, float, int]]
) -> dict[int, list[tuple[int, int, float, int]]]:
    grouped: dict[int, list[tuple[int, int, float, int]]] = defaultdict(list)
    for tournament_id, hand_no, stack, _big_blind, stack_bb, players_remaining in rows:
        grouped[tournament_id].append((hand_no, stack, stack_bb, players_remaining))
    return dict(grouped)


def plot_single_tournament(
    player_name: str,
    tournament_id: int,
    history: list[tuple[int, int, float, int]],
) -> None:
    hands = [hand_no for hand_no, _stack, _stack_bb, _players_remaining in history]
    stacks = [stack for _hand_no, stack, _stack_bb, _players_remaining in history]
    stacks_bb = [stack_bb for _hand_no, _stack, stack_bb, _players_remaining in history]

    fig, (ax_stack, ax_bb) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    ax_stack.plot(hands, stacks, color="#0f766e", linewidth=2)
    ax_stack.set_ylabel("Stack chips")
    ax_stack.set_title(f"{player_name} - Tournament {tournament_id}")
    ax_stack.grid(True, alpha=0.25)

    ax_bb.plot(hands, stacks_bb, color="#b45309", linewidth=2)
    ax_bb.set_xlabel("Hand number")
    ax_bb.set_ylabel("Stack BB")
    ax_bb.grid(True, alpha=0.25)

    fig.tight_layout()


def plot_all_tournaments(
    player_name: str,
    grouped_history: dict[int, list[tuple[int, int, float, int]]],
) -> None:
    fig, (ax_stack, ax_bb) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    avg_stack_by_hand: dict[int, list[int]] = defaultdict(list)
    avg_stack_bb_by_hand: dict[int, list[float]] = defaultdict(list)

    for tournament_id, history in grouped_history.items():
        hands = [hand_no for hand_no, _stack, _stack_bb, _players_remaining in history]
        stacks = [stack for _hand_no, stack, _stack_bb, _players_remaining in history]
        stacks_bb = [stack_bb for _hand_no, _stack, stack_bb, _players_remaining in history]

        ax_stack.plot(hands, stacks, alpha=0.20, linewidth=1)
        ax_bb.plot(hands, stacks_bb, alpha=0.20, linewidth=1)

        for hand_no, stack, stack_bb, _players_remaining in history:
            avg_stack_by_hand[hand_no].append(stack)
            avg_stack_bb_by_hand[hand_no].append(stack_bb)

    avg_hands = sorted(avg_stack_by_hand)
    avg_stacks = [
        sum(avg_stack_by_hand[hand_no]) / len(avg_stack_by_hand[hand_no])
        for hand_no in avg_hands
    ]
    avg_stacks_bb = [
        sum(avg_stack_bb_by_hand[hand_no]) / len(avg_stack_bb_by_hand[hand_no])
        for hand_no in avg_hands
    ]

    ax_stack.plot(avg_hands, avg_stacks, color="#111827", linewidth=3, label="Media")
    ax_stack.set_ylabel("Stack chips")
    ax_stack.set_title(
        f"{player_name} - {len(grouped_history)} tournaments (linee singole + media)"
    )
    ax_stack.grid(True, alpha=0.25)
    ax_stack.legend()

    ax_bb.plot(avg_hands, avg_stacks_bb, color="#7c2d12", linewidth=3, label="Media BB")
    ax_bb.set_xlabel("Hand number")
    ax_bb.set_ylabel("Stack BB")
    ax_bb.grid(True, alpha=0.25)
    ax_bb.legend()

    fig.tight_layout()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    rows = fetch_snapshots(db_path=db_path, player_name=args.player, tournament_id=args.tournament)

    if not rows:
        raise SystemExit(
            f"Nessuno snapshot trovato per player={args.player!r}"
            + (
                f" tournament_id={args.tournament}"
                if args.tournament is not None
                else ""
            )
        )

    grouped_history = group_by_tournament(rows)

    if args.tournament is not None:
        plot_single_tournament(args.player, args.tournament, grouped_history[args.tournament])
    else:
        plot_all_tournaments(args.player, grouped_history)

    if args.output:
        plt.savefig(args.output, dpi=150, bbox_inches="tight")
        print(f"Grafico salvato in: {args.output}")
        return

    plt.show()


if __name__ == "__main__":
    main()
