from enum import Enum
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCREENSHOT_DIR = PROJECT_ROOT / "immage"


class SCR_TYPE(Enum):
    ADB = 0
    IMMAGE_SAVED = 2


SCRENSHOT_TYPE = SCR_TYPE.ADB
AUTO_PRESS_BUTTON = False 
SAVE_SCREENSHOT = True
SAVE_SCREENSHOT_DIR = SCREENSHOT_DIR
DEBUG_START_FRAME_NUMBER = 0
DISPLAY_SCALE = 0.8
DISPLAY_PREVIEW = False
PLAYER_STATS_DB_PATH = DATA_DIR / "player_stats.db"
RED_TEXT = "\033[91m"
RESET_TEXT = "\033[0m"
OCR_ENGINE = "rapidocr"  # "rapidocr" oppure "paddleocr"


COUNTER_PRESS_BUTTON = 3

table_name = "Poker_star_oppo_1080x2400"
HALTEZZA_FOLD = 36  # oppo
#HALTEZZA_FOLD = 30  # A53

game_type_set = "tournament"  # "tournament"  "cash"

play_style_set = "aggressive"    #"mixed"   "conservative" "aggressive"
