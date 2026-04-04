import re
import Impostazioni


def point_in_rect(x, y, rect):
    """
    Controlla se un punto è dentro un rettangolo.
    rect = {"x":..., "y":..., "w":..., "h":...}
    """
    rx = rect["x"]
    ry = rect["y"]
    rw = rect["w"]
    rh = rect["h"]

    return rx <= x <= rx + rw and ry <= y <= ry + rh


def ocr_in_roi(ocr_results, roi, min_score=0.5):
    """
    Restituisce i risultati OCR il cui punto alto-sinistra del box
    cade dentro la ROI.
    """
    found = []

    if roi is None:
        return found

    for item in ocr_results:
        text = item["text"]
        score = item["score"]
        box = item["box"]

        if score < min_score:
            continue

        x = box[0][0]
        y = box[0][1]

        if point_in_rect(x, y, roi):
            found.append(item)

    return found


def sort_ocr_left_to_right(results):
    """
    Ordina i risultati OCR da sinistra a destra.
    """
    return sorted(results, key=lambda r: r["box"][0][0])

def sort_ocr_top_to_down(results):
    """
    Ordina i risultati OCR dall'alto verso il basso.
    """
    return sorted(results, key=lambda r: r["box"][0][1])

def ocr_results_to_text(results):
    """
    Concatena i testi OCR trovati dentro una ROI.
    """
    ordered = sort_ocr_top_to_down(results)
    return ordered[0]["text"] if ordered else ""


def parse_amount(text: str) -> float:
    """
    Converte stringhe OCR in float.
    Esempi:
    '2,10' -> 2.10
    '0,62' -> 0.62
    'Piatto: 0,28' -> 0.28
    """
    if not text:
        return 0.0

    text = text.replace(",", ".")
    # per tornei 
       # se True, considera che i numeri OCR siano formattati senza separatore decimale e con eventuali migliaia separati da punti (es. 1.234 per mille e 2,10 per due euro e dieci centesimi)
    if poker.Impostazioni.IS_TORNEY == True:
        text = text.replace(",", "")
        text = text.replace(".", "")
    text = text.replace(" ", "")

    filtered = ""
    dot_seen = False

    for ch in text:
        if ch.isdigit():
            filtered += ch
        elif ch == "." and not dot_seen:
            filtered += ch
            dot_seen = True

    

    try:
        return float(filtered)
    except ValueError:
        return parse_ocr_number(filtered)
    

    
import os
from typing import Optional, Union


def extract_frame_number(path):
    name = os.path.splitext(os.path.basename(path))[0]
    match = re.search(r"(\d+)$", name)
    return int(match.group(1)) if match else None


def list_images(folder="immage", min_frame_number=None):

    valid_ext = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

    files = []

    if not os.path.isdir(folder):
        return []

    for f in os.listdir(folder):

        if f.lower().endswith(valid_ext):
            file_path = os.path.join(folder, f)
            frame_number = extract_frame_number(file_path)

            if min_frame_number is not None and frame_number is not None and frame_number < min_frame_number:
                continue

            files.append(file_path)

    files.sort(key=lambda path: (extract_frame_number(path) is None, extract_frame_number(path) or 0, os.path.getmtime(path)))

    return files

Number = Union[int, float]

_OCR_MAP = str.maketrans({
    "O": "0", "o": "0",
    "I": "1", "l": "1", "|": "1", "¡": "1",
    "S": "5", "s": "5",
    "B": "8",
    "Z": "2",
    "D": "0",  # a volte OCR scambia 0 con D
})

def parse_ocr_number(text: str, *, allow_negative: bool = True) -> Optional[Number]:
    if not text:
        return 0.0

    t = text.strip().translate(_OCR_MAP)

    # Tieni solo caratteri utili
    keep = re.sub(r"[^0-9\-\+\.,\s€$£]", " ", t)

    # Token numerici SENZA attraversare spazi
    candidates = re.findall(r"[-+]?(?:\d+[.,]\d+|\d+)", keep)

    if not candidates:
        return 0.0

    if not allow_negative:
        candidates = [c.lstrip("+-") for c in candidates]

    # Preferisci:
    # 1) numeri con parte decimale
    # 2) più cifre
    def score(c: str):
        has_decimal = 1 if ("," in c or "." in c) else 0
        digits = len(re.sub(r"\D", "", c))
        return (has_decimal, digits)

    c = max(candidates, key=score)

    # Normalizza separatori
    if "." in c and "," in c:
        last_dot = c.rfind(".")
        last_com = c.rfind(",")
        dec = "." if last_dot > last_com else ","
        thou = "," if dec == "." else "."
        c = c.replace(thou, "")
        c = c.replace(dec, ".")
    elif "," in c:
        c = c.replace(",", ".")
    # se c'è solo '.' lo lasciamo così

    c = re.sub(r"[^0-9\-\+\.]", "", c)

    if c.count(".") > 1:
        parts = c.split(".")
        c = "".join(parts[:-1]) + "." + parts[-1]

    try:
        v = float(c)
    except ValueError:
        return 0.0

    if v.is_integer():
        return int(v)
    return v
