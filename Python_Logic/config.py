from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

# Modalita disponibili: "socket" oppure "replay"
DATA_SOURCE = "replay"
IS_TOURNEI = True

# Config sorgente live socket
SOCKET_HOST = "127.0.0.1"
SOCKET_PORT = 5000

# Config replay: file singolo oppure cartella con tanti .json
REPLAY_INPUT_PATH = BASE_DIR / "packets.db"

# Salvataggio pacchetti ricevuti in live
SAVE_INCOMING_PACKETS = False
PACKET_SAVE_DIR = BASE_DIR / "packets.db"

# Visualizzazioni
ENABLE_JSON_VIEWER = True
ENABLE_TABLE_VIEWER = True
