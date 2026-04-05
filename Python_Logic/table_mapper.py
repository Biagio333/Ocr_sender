from difflib import SequenceMatcher

from payload_utils import get_players, get_table
from table_models import PlayerBase, TableBase, infer_street, parse_amount_from_text


def names_are_similar(name_a: str, name_b: str, threshold: float = 0.90) -> bool:
    left = (name_a or "").strip().lower()
    right = (name_b or "").strip().lower()

    if not left or not right:
        return left == right

    return SequenceMatcher(None, left, right).ratio() >= threshold

class TableStateMapper:
    def __init__(self):
        self.table = TableBase()
        self._previous_player_states: dict[int, dict] = {}
        self._previous_hero_cards: list[dict] = []
        self._previous_hands_number: int | None = None
        self._previous_street = "unknown"
        self._previous_max_bet = 0.0
        

    def build_table(self, payload: dict) -> TableBase:
        self._save_previous_state()

        table_data = get_table(payload)
        self.table.timestamp = payload.get("timestamp")
        self.table.processing_elapsed_ms = payload.get("processing_elapsed_ms")
        self.table.pot_text = table_data.get("pot", "") or ""
        #self.table.pot_amount = parse_amount_from_text(table_data.get("pot", ""), prefer="last")

        self.table.board_cards = list(table_data.get("board_cards", []) or [])
        self.table.hero_cards = list(table_data.get("hero_cards", []) or [])
        self.table.available_actions = list(table_data.get("available_actions", []) or [])
        self.table.amount_buttons = list(table_data.get("amount_buttons", []) or [])
        self.table.amount_value_text = table_data.get("amount_value_text", "") or ""
        self.table.hero_to_act = bool(table_data.get("hero_to_act", False))
        self.table.buttons_visible = bool(
            self.table.hero_to_act
            or self.table.available_actions
            or self.table.amount_buttons
            or self.table.amount_value_text
        )
        self.table.street = infer_street(self.table.board_cards)
        self.table.raw = payload

        
        seen_indexes: set[int] = set()
        for player_data in get_players(payload):
            player_index = player_data.get("player_index", -1)
            player = self.table.get_or_create_player(player_index)
            player.update_from_packet(player_data)
            seen_indexes.add(player_index)

        hero_has_cards = len(self.table.hero_cards) == 2
        hero_player = self.table.get_player(0)
        if hero_player is not None:
            hero_player.has_covered_card = hero_has_cards

#        for player in self.table.players:
#            if player.player_index not in seen_indexes:
#                player.reset_for_missing_packet()
        self._infer_player_actions()

        #calcolo pot amount 
        #new hand hands_number
        if self.table.street == "preflop" and self.table.hero_cards != self._previous_hero_cards and len(self.table.hero_cards) == 2:
            self.table.hands_number += 1
            self.table.street_pot_amount.clear()  #nuova mano resetto pot street

        if self.table.street == "preflop" :
            if len(self.table.street_pot_amount) == 0:
                self.table.street_pot_amount.append(0.0)  #inizializzo pot street preflop se non presente


        try:
            self.table.street_pot_amount[-1]=0.0
            for player in self.table.players:
                #aggiungo nellultimo
                self.table.street_pot_amount[-1] += player.bet_amount
        except IndexError:
            pass
        #calcolo il pot amount come somma dei bet dei player 
        self.table.pot_amount = sum(self.table.street_pot_amount)

        #resetto se cambio street o nuova partita
        if self.table.street != self._previous_street  and self.table.street != "preflop":
            self.table.street_pot_amount.append(0.0)  #aggiungo nuovo street pot
            for player in self.table.players:
                player.bet_amount = 0.0

        return self.table

    def _save_previous_state(self):
        self._previous_hero_cards = list(self.table.hero_cards)
        self._previous_hands_number = getattr(self.table, "hands_number", None)
        self._previous_street = self.table.street
        self._previous_max_bet = max((player.bet_amount for player in self.table.players), default=0.0)
        self._previous_player_states = {
            player.player_index: {
                "bet_amount": player.bet_amount,
                "has_covered_card": player.has_covered_card,
            }
            for player in self.table.players
        }

    def _infer_player_actions(self):
        current_max_bet = max((player.bet_amount for player in self.table.players), default=0.0)
        previous_max_bet = self._previous_max_bet if self._previous_street == self.table.street else 0.0

        reset_table = False
        for player in self.table.players:
            previous_player = self._previous_player_states.get(player.player_index)
            player.inferred_action = self._infer_player_action(
                player=player,
                previous_player=previous_player,
                current_max_bet=current_max_bet,
                previous_max_bet=previous_max_bet,
                street=self.table.street,
            )
            if player.inferred_action == "vinto":
                reset_table = True
        if reset_table:
            for player in self.table.players:   #resetto bet se qualcuno vince
                player.bet_amount = 0.0

    def _infer_player_action(
        self,
        player: PlayerBase,
        previous_player: dict | None,
        current_max_bet: float,
        previous_max_bet: float,
        street: str,
    ) -> str:
        
        #fronte salita azione precedente
        if player.inferred_action != "waiting" and not names_are_similar(player.inferred_action, player.inferred_action_old,0.6) and player.inferred_action is not None:

            player.inferred_action_old = player.inferred_action

            if player.inferred_action == "fold" :
                return "fold"

            if player.inferred_action == "mettisb" :
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount
                return "mettisb"
            
            if player.inferred_action == "mettibb":
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount
                self.table.BB_amount = player.bet_amount
                return "mettibb"
            
            if player.inferred_action == "check"  :
                return "check"
            
            if player.inferred_action == "chiama" or player.inferred_action == "call" :
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount
                return "chiama"
            
            if player.inferred_action == "puntata" or player.inferred_action == "bet" :
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount
                return "puntata"
            
            if player.inferred_action == "rilancia" or player.inferred_action == "raise" :
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount

                return "rilancia"
            
            if player.inferred_action == "all-in"  :
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                player.stack_amount_prev = player.stack_amount
                return "all-in"
            
            if player.inferred_action == "muck"  :
                return "muck"
            
            if player.inferred_action.startswith("vin"):
                
                return "vinto"
            
            if player.inferred_action.startswith("tem"):
                return "waiting"

            return player.inferred_action
        

        #per sicurezza se non riesco a inferire azione da testo confronto stack attuale con precedente e max bet per capire se ha chiamato o rilanciato o foldato
        if player.stack_amount != player.stack_amount_prev:
            if player.stack_amount_prev is not None and player.stack_amount < player.stack_amount_prev:
                player.bet_amount += player.stack_amount_prev - player.stack_amount
                if current_max_bet == 0.0 or player.bet_amount > previous_max_bet:
            
                    player.stack_amount_prev = player.stack_amount
                    return "raise"
                else:
                   
                    player.stack_amount_prev = player.stack_amount
                    return "call"
            elif player.stack_amount_prev is not None and player.stack_amount > player.stack_amount_prev:
                player.stack_amount_prev = player.stack_amount
                return "vinto"




        return "waiting"
    


#-------------------------------------------------------------------------------------------
        
