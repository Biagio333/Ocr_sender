from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from player_stats import DEFAULT_DB_PATH, PlayerStatsTracker


def main() -> None:
    db_path = Path(DEFAULT_DB_PATH)

    if db_path.exists():
        db_path.unlink()
        print(f"Deleted stats database: {db_path}")
    else:
        print(f"Stats database not found, creating a new empty one: {db_path}")

    # Recreate an empty database with the expected schema.
    PlayerStatsTracker(player_name="__reset__")
    if db_path.exists():
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM player_stats WHERE player_name = ?", ("__reset__",))
            conn.commit()

    print("Player stats reset completed.")


if __name__ == "__main__":
    main()
