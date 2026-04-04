import json
from pathlib import Path


class ROIMap:
    """
    Gestisce le ROI del tavolo.
    Supporta:
    - JSON già convertito: {"nome": {"x":..,"y":..,"w":..,"h":..}}
    - JSON originale di Labelme con "shapes"
    """

    def __init__(self, json_path: str | Path):
        self.json_path = Path(json_path)
        self.data = {}

    @staticmethod
    def _scale_roi(roi: dict, scale_factor: float):
        return {
            "x": int(round(roi["x"] * scale_factor)),
            "y": int(round(roi["y"] * scale_factor)),
            "w": int(round(roi["w"] * scale_factor)),
            "h": int(round(roi["h"] * scale_factor)),
        }

    def load(self, scale_factor: float = 1.0):
        with self.json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        # Caso 1: file già convertito
        if "shapes" not in raw:
            self.data = {
                name: self._scale_roi(roi, scale_factor)
                for name, roi in raw.items()
            }
            return

        # Caso 2: file Labelme
        converted = {}

        for shape in raw.get("shapes", []):
            label = shape.get("label")
            points = shape.get("points", [])

            if not label or len(points) < 2:
                continue

            x1, y1 = points[0]
            x2, y2 = points[1]

            x = int(round(min(x1, x2) * scale_factor))
            y = int(round(min(y1, y2) * scale_factor))
            w = int(round(abs(x2 - x1) * scale_factor))
            h = int(round(abs(y2 - y1) * scale_factor))

            converted[label] = {
                "x": x,
                "y": y,
                "w": w,
                "h": h
            }

        self.data = converted

    def get(self, name: str):
        return self.data.get(name)

    def get_by_prefix(self, prefix: str):
        return {
            name: roi
            for name, roi in self.data.items()
            if name == prefix or name.startswith(prefix)
        }

    def all(self):
        return self.data
