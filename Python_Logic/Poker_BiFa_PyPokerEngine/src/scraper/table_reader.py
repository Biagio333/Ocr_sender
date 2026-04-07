import random

from scraper.ocr_utils import ocr_in_roi, ocr_results_to_text, parse_amount


class TableReader:
    """
    Legge le informazioni del tavolo partendo da:
    - ROI del tavolo
    - risultati OCR full-screen

    Popola:
    - nome player
    - stack player
    - pot
    """

    def __init__(self, roi_map, min_score=0.5):
        self.roi_map = roi_map
        self.min_score = min_score

    

    def read_text_from_roi(self, ocr_results, roi_name: str) -> str:
        roi = self.roi_map.get(roi_name)
        items = ocr_in_roi(ocr_results, roi, self.min_score)
        return ocr_results_to_text(items)

    def read_amount_from_roi(self, ocr_results, roi_name: str) -> float:
        text = self.read_text_from_roi(ocr_results, roi_name)
        text = text.lower().replace(" ", "")
        if text == "all-in" or text == "allin":
            return 9999999
        return parse_amount(text)

    def populate_player(self, player, ocr_results, can_record_action=True):
        """
        Popola name, stack e puntata corrente di un singolo player.
        Cerca:
        - player_{seat}_name
        - player_{seat}_stack
        - player_{seat}_bet
        """
        seat = player.seat


        name_roi_name = f"player_{seat}_name"
        stack_roi_name = f"player_{seat}_stack"
        bet_roi_name = f"player_{seat}_bet"



        name_text = self.read_text_from_roi(ocr_results, name_roi_name)

        bet_value = self.read_amount_from_roi(ocr_results, bet_roi_name)
        player.update_current_bet(bet_value if bet_value > 0 else 0.0)

        stack_value = self.read_amount_from_roi(ocr_results, stack_roi_name)
        if stack_value > 0:
            if stack_value == 9999999:
                stack_value = bet_value
                player.is_all_in = True
            player.update_stack(stack_value)



        if name_text:
            #player.set_name(name_text, can_record_action=can_record_action)
            player.set_name(name_text, can_record_action=True)


        if player.name or stack_value > 0 or bet_value > 0:
            player.observe_current_hand()



    def populate_all_players(self, table, ocr_results):
        """
        Popola tutti i player del tavolo.
        """
        copy_request = False
        for player in table.players:
            self.populate_player(
                player,
                ocr_results,
                can_record_action=not table.buttons_visible,
            )

            if player.request_reset_hand==True:
                copy_request = True
        
        if copy_request:
            for player in table.players:
                player.request_reset_hand = True

    def read_pot(self, ocr_results) -> float:
        """
        Legge il pot dalla ROI 'pot'.
        """
        return self.read_amount_from_roi(ocr_results, "pot")

    def _normalize_action_text(self, text: str) -> str:
        normalized = (text or "").strip().lower()
        normalized = normalized.replace("-", "")
        # qui va bene cosi non aggiungere la roba
        return normalized

    def _detect_action_name(self, text: str):
        normalized = self._normalize_action_text(text)
        # qui va bene cosi non aggiungere la roba

        return None

    def _item_metrics(self, item):
        box = item["box"]
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        return {
            "text": item["text"],
            "score": item["score"],
            "x": min_x,
            "y": min_y,
            "w": max_x - min_x,
            "h": max_y - min_y,
            "cx": (min_x + max_x) / 2,
            "cy": (min_y + max_y) / 2,
        }

    def _cluster_button_items(self, roi_items):
        measured_items = [self._item_metrics(item) for item in roi_items]
        measured_items.sort(key=lambda item: item["cx"])
        clusters = []

        for item in measured_items:
            nearest_cluster = None
            nearest_distance = None

            for cluster in clusters:
                distance = abs(item["cx"] - cluster["cx"])
                tolerance = max(45.0, (cluster["avg_w"] + item["w"]) / 1.5)
                if distance <= tolerance and (nearest_distance is None or distance < nearest_distance):
                    nearest_cluster = cluster
                    nearest_distance = distance

            if nearest_cluster is None:
                clusters.append({
                    "items": [item],
                    "cx": item["cx"],
                    "avg_w": item["w"],
                })
                continue

            nearest_cluster["items"].append(item)
            count = len(nearest_cluster["items"])
            nearest_cluster["cx"] = sum(entry["cx"] for entry in nearest_cluster["items"]) / count
            nearest_cluster["avg_w"] = sum(entry["w"] for entry in nearest_cluster["items"]) / count

        return [cluster["items"] for cluster in clusters]

    def _parse_action_cluster(self, items, roi_name):
        ordered = sorted(items, key=lambda item: (item["y"], item["x"]))
        full_text = " ".join(item["text"] for item in ordered).strip()
        if not full_text:
            return None

        amount = parse_amount(full_text)
        if amount <= 0:
            amount = None

        min_x = min(item["x"] for item in ordered)
        min_y = min(item["y"] for item in ordered)
        max_x = max(item["x"] + item["w"] for item in ordered)
        max_y = max(item["y"] + item["h"] for item in ordered)

        text_rect = {
            "left": int(min_x),
            "top": int(min_y),
            "right": int(max_x),
            "bottom": int(max_y),
        }
        text_width = max(1, text_rect["right"] - text_rect["left"])
        text_height = max(1, text_rect["bottom"] - text_rect["top"])
        has_amount = amount is not None
        expand_ratio = 0.10 if has_amount else 1.00

        pad_x = max(1, int(text_width * expand_ratio / 2))
        pad_y = max(1, int(text_height * expand_ratio / 2))

        button_rect = {
            "left": max(0, text_rect["left"] - pad_x),
            "top": max(0, text_rect["top"] - pad_y),
            "right": text_rect["right"] + pad_x,
            "bottom": text_rect["bottom"] + pad_y,
        }
        button_width = max(1, button_rect["right"] - button_rect["left"])
        button_height = max(1, button_rect["bottom"] - button_rect["top"])
        click_rect = {
            "left": button_rect["left"] + max(1, int(button_width * 0.15)),
            "top": button_rect["top"] + max(1, int(button_height * 0.20)),
            "right": button_rect["right"] - max(1, int(button_width * 0.15)),
            "bottom": button_rect["bottom"] - max(1, int(button_height * 0.20)),
        }
        if click_rect["right"] <= click_rect["left"] or click_rect["bottom"] <= click_rect["top"]:
            click_rect = dict(button_rect)
        click_point = {
            "x": random.randint(click_rect["left"], click_rect["right"] - 1),
            "y": random.randint(click_rect["top"], click_rect["bottom"] - 1),
        }

        return {
            "label": full_text,
            "roi_label": roi_name,
            "ocr_rect": text_rect,
            "button_rect": button_rect,
            "click_rect": click_rect,
            "ocr_rect_area": int(text_width * text_height),
            "click_point": click_point,
        }

    def read_action_buttons(self, ocr_results):
        action_buttons = []
        button_rois = self.roi_map.get_by_prefix("pulsanti")

        for roi_name, roi in sorted(button_rois.items()):
            roi_items = ocr_in_roi(ocr_results, roi, self.min_score)
            if not roi_items:
                continue

            for cluster in self._cluster_button_items(roi_items):
                parsed_button = self._parse_action_cluster(cluster, roi_name)
                if parsed_button is not None:
                    action_buttons.append(parsed_button)

        return action_buttons

    def read_amount_buttons(self, ocr_results):
        amount_buttons = []
        button_rois = self.roi_map.get_by_prefix("select_amount")

        for roi_name, roi in sorted(button_rois.items()):
            normalized_name = (roi_name or "").strip().lower()
            if normalized_name.endswith("value") or "amount_value" in normalized_name:
                continue

            roi_items = ocr_in_roi(ocr_results, roi, self.min_score)
            if not roi_items:
                continue

            for cluster in self._cluster_button_items(roi_items):
                parsed_button = self._parse_action_cluster(cluster, roi_name)
                if parsed_button is not None:
                    amount_buttons.append(parsed_button)

        return amount_buttons

    def populate_table(self, table, ocr_results):
        """
        Popola tutto il tavolo:
        - players
        - pot
        - pulsanti azione
        """
        # Aggiorna prima i pulsanti: i player usano questo stato per decidere
        # se registrare o meno azioni OCR nel frame corrente.
        table.set_available_actions(self.read_action_buttons(ocr_results))
        table.set_avaible_button(self.read_amount_buttons(ocr_results))

        self.populate_all_players(table, ocr_results)

        pot_value = self.read_pot(ocr_results)
        if pot_value > 0:
            table.set_pot(pot_value)

    def table_reset(self, table):

        # reset dati
        for p in table.players:
            #p.name = None
            p.stack = 0.0
            p.current_bet = 0.0
            p.new_hand()


        table.reset_hand_state()
