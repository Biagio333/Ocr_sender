from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

# Modalita disponibili: "socket" oppure "replay"
DATA_SOURCE = "socket"
IS_TOURNEI = False
# Salvataggio pacchetti ricevuti in live
SAVE_INCOMING_PACKETS = True
PACKET_SAVE_DIR = BASE_DIR / "packets_tourney.db"

# Config sorgente live socket
SOCKET_HOST = "127.0.0.1"
SOCKET_PORT = 5000

# Config replay: file singolo oppure cartella con tanti .json
REPLAY_INPUT_PATH = BASE_DIR / "packets_tourney.db"



# Visualizzazioni
ENABLE_JSON_VIEWER = False
ENABLE_TABLE_VIEWER = False
ENABLE_BUTTON_DEBUG_LOGS = False

# Hero bot live bridge
ENABLE_HERO_BOT = True
HERO_BOT_KIND = "negreanu_v2"

#HERO_BOT_PROFILE = "blind_stealer"
HERO_BOT_PROFILE = "nit_killer"

# Auto click ADB
ENABLE_ADB_AUTOCLICK = True
ADB_DEVICE_SERIAL = ""
ADB_TAP_DELAY_SEC = 0.07
ADB_AMOUNT_TAP_DELAY_SEC = 0.60
ADB_TAP_RANDOM_SEC = 0.13
ADB_MAX_AMOUNT_STEPS = 6
ADB_RETRY_DELAY_SEC = 2.50
ADB_MAX_RETRIES = 3
