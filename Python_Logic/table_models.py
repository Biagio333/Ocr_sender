from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from config import IS_TOURNEI

ACTION_WORDS = [
    "chiama",  "ochiama",
    "check",   "ocheck", 
    "fold",    "ofold",
    "puntata", "opuntata", 
    "mettibb", "omettibb",
    "mettisb", "omettisb", 
    "muck",    "omuck",
    "tempo",   "otempo",
    "vinto" ,  "ovinto" ,
    "rilancia","orilancia",
]

ACTION_WORD_SET = set(ACTION_WORDS)




from collections import Counter

def _norm_name(s: str) -> str:
    return "".join((s or "").strip().lower().split())

def _is_truncated_version(a: str, b: str, min_prefix_ratio=0.75) -> bool:
    """
    True se uno dei due sembra una versione troncata dell'altro.
    Esempi:
      MaVai  <-> MaVaiCavall
      biagio <-> biagioBau1976
    """
    a = _norm_name(a)
    b = _norm_name(b)

    if not a or not b:
        return False

    short_name, long_name = (a, b) if len(a) <= len(b) else (b, a)

    if short_name == long_name:
        return True

    if long_name.startswith(short_name):
        return True

    common_prefix = 0
    for ca, cb in zip(short_name, long_name):
        if ca == cb:
            common_prefix += 1
        else:
            break

    return (common_prefix / max(1, len(short_name))) >= min_prefix_ratio

def _choose_best_name(group):
    """
    Sceglie il nome migliore nel gruppo:
    - preferisce quello più lungo
    - a parità, quello più frequente
    """
    freq = Counter(group)
    return max(group, key=lambda x: (len(_norm_name(x)), freq[x]))


class NameStabilizer:
    def __init__(self, window_size=3, threshold=0.7):
        self.window_size = window_size
        self.threshold = threshold
        self.names = []       # buffer ultimi nomi
        self.current = None   # nome stabile

    def update(self, new_name: str):

        if not new_name or not new_name.strip():
            return self.current

        # aggiungi nuovo nome
        self.names.append(new_name)

        # mantieni dimensione finestra
        if len(self.names) > self.window_size:
            self.names.pop(0)

        # raggruppa nomi simili
        groups = []

        for name in self.names:
            found = False
            for group in groups:
                ref = group[0]
                if names_are_similar(name, ref, self.threshold) or _is_truncated_version(name, ref):
                    group.append(name)
                    found = True
                    break
            if not found:
                groups.append([name])

        if not groups:
            return self.current

        # trova gruppo più grande
        best_group = max(groups, key=len)

        # se abbastanza stabile → aggiorna
        if len(best_group) >= max(2, self.window_size // 2):
            best_name = _choose_best_name(best_group)

            # se current è simile al best_name, tieni il migliore tra i due
            if self.current and (
                names_are_similar(self.current, best_name, self.threshold)
                or _is_truncated_version(self.current, best_name)
            ):
                self.current = _choose_best_name([self.current, best_name])
            else:
                self.current = best_name

        return self.current


def normalize(text: str) -> str:
    text = text.replace(" ", "").lower()
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _looks_like_non_name_label(text: str) -> bool:
    value = normalize(text)
    if not value:
        return True

    if value in ACTION_WORD_SET:
        return True

    if value.startswith("vin") or value.startswith("ovin"):
        return True

    if value.startswith("metti") or value.startswith("ometti"):
        return True

    if value.startswith("chiama") or value.startswith("ochiama"):
        return True

    if value.startswith("check") or value.startswith("ocheck"):
        return True

    if value.startswith("fold") or value.startswith("ofold"):
        return True

    if value.startswith("puntata") or value.startswith("opuntata"):
        return True

    if value.startswith("rilancia") or value.startswith("orilancia"):
        return True

    if value.startswith("tempo") or value.startswith("otempo"):
        return True

    return False

def extract_amount_candidates(text: str) -> list[float]:
    if not text:
        return []

    cleaned = str(text)
    if IS_TOURNEI:
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", "")

    else:
        cleaned = cleaned.replace(",", ".")

    matches = re.findall(r"\d+(?:\.\d+)*", cleaned)
    amounts: list[float] = []

    for match in matches:
        normalized = match
        if normalized.count(".") > 1:
            normalized = normalized.replace(".", "")
        try:
            amounts.append(float(normalized))
        except ValueError:
            continue

    return amounts


def parse_amount_with_action(text: str, prefer: str = "last") -> tuple[float, str]:

    text = normalize(text)  # normalizza caratteri unicode simili

    #pre aggiusto 
    try:
        if text != "" and not text.startswith("pia") and not text.startswith("pla"):
            float(text)
            a=0
    except ValueError:
            text = normalize(text)
            if names_are_similar(text, "All-in", threshold=0.5) :

                return float(0) ,"all-in"



    amounts = extract_amount_candidates(text)

    if len(amounts) > 1 :
        if text [0] in ["P","p"]:
            return -amounts[0] , ""

    if not amounts:
        return 0.0, ""
    if prefer == "first":
        return amounts[0], ""
    if prefer == "max":
        return max(amounts), ""
    return amounts[-1], ""


def parse_amount_from_text(text: str, prefer: str = "last") -> float:
    amount, _ = parse_amount_with_action(text, prefer=prefer)
    return amount


def infer_street(board_cards: list[dict]) -> str:
    count = len(board_cards)
    if count == 0:
        return "preflop"
    if count == 3:
        return "flop"
    if count == 4:
        return "turn"
    if count >= 5:
        return "river"
    return "unknown"


def names_are_similar(name_a: str, name_b: str, threshold: float = 0.90) -> bool:
    left = (name_a or "").strip().lower()
    right = (name_b or "").strip().lower()

    if not left or not right:
        return left == right

    return SequenceMatcher(None, left, right).ratio() >= threshold


#-----------------------------------------------------------------------
#------------------------------ MODELS ---------------------------------
#-----------------------------------------------------------------------


@dataclass
class PlayerBase:
    player_index: int
    
    name: str = ""

    stack_text: str = ""
    bet_text: str = ""
    stack_amount: float = 0.0
    stack_amount_prev:  float = None 
    bet_amount: float = 0.0
    has_covered_card: bool = False
    has_dealer_button: bool = False
    inferred_action: str = "waiting"
    inferred_action_old: str = "waiting"
    name_stabilizer: NameStabilizer = field(
        default_factory=lambda: NameStabilizer(window_size=3)
    )
    raw: dict = field(default_factory=dict)

    

    def update_from_packet(self, player_data: dict):

        name = player_data.get("name", "") or ""
    
        #controllo nome se e giusto cambiare
        #if not names_are_similar(name, self.name,0.7): # and player_data.get("player_index") == 0:
        n = normalize(name)
        
        set_new_name = True
        if _looks_like_non_name_label(n):
            set_new_name = False
            self.inferred_action = n[1:] if n.startswith("o") else n

        if set_new_name:  
            self.name_stabilizer.update(n)
            if self.name_stabilizer.current is not None:
                if not names_are_similar(self.name_stabilizer.current, self.name, 0.9):
                    print(
                        f"Player index {self.player_index} name changed from "
                        f"'{self.name}' to '{self.name_stabilizer.current}'"
                    )
                    self.name = self.name_stabilizer.current
                else:
                    self.inferred_action = "waiting"

        self.stack_text = player_data.get("stack", "") or ""
        self.bet_text = player_data.get("bet", "") or ""
        
        # metto a posto lo stack
        if self.stack_amount_prev is not None :
            self.stack_amount_prev = self.stack_amount

        self.stack_amount, act = parse_amount_with_action(self.stack_text, prefer="max")
        if act == "all-in":
            self.inferred_action = "all-in"

        if self.stack_amount_prev is  None :
            self.stack_amount_prev = self.stack_amount


        #self.bet_amount = parse_amount_from_text(self.bet_text, prefer="last")
        self.has_covered_card = isinstance(player_data.get("covered_card"), dict)
        self.has_dealer_button = isinstance(player_data.get("dealer_button"), dict)
        self.raw = player_data

    def reset_for_missing_packet(self):
        self.name = ""
        self.name_stabilizer = NameStabilizer(window_size=3)
        self.stack_text = ""
        self.bet_text = ""
        self.stack_amount = 0.0
        self.bet_amount = 0.0
        self.has_covered_card = False
        self.has_dealer_button = False
        self.inferred_action = "waiting"
        self.raw = {}


@dataclass
class TableBase:

    hands_number: int = 0
    timestamp: int | None = None
    processing_elapsed_ms: int | None = None
    pot_text: str = ""
    pot_amount: float = 0.0
    street_pot_amount: list[float] = field(default_factory=list)
    board_cards: list[dict] = field(default_factory=list)
    hero_cards: list[dict] = field(default_factory=list)
    available_actions: list[dict] = field(default_factory=list)
    amount_buttons: list[dict] = field(default_factory=list)
    amount_value_text: str = ""
    buttons_visible: bool = False
    hero_to_act: bool = False
    players: list[PlayerBase] = field(default_factory=list)
    street: str = "unknown"
    BB_amount: float = 0.0
    raw: dict = field(default_factory=dict)

    def get_player(self, player_index: int) -> PlayerBase | None:
        for player in self.players:
            if player.player_index == player_index:
                return player
        return None

    def get_or_create_player(self, player_index: int) -> PlayerBase:
        player = self.get_player(player_index)
        if player is not None:
            return player

        player = PlayerBase(player_index=player_index)
        self.players.append(player)
        self.players.sort(key=lambda item: item.player_index)
        return player
