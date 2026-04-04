import os

# PaddleOCR può fare controlli remoti e inizializzare plugin Qt non adatti ad ambienti headless.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Evita il path oneDNN/PIR che in alcune build CPU di Paddle genera NotImplementedError.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

import subprocess
import inspect
import numpy as np
import cv2
import time
import threading
from collections import deque

from Impostazioni import  *



class OCRReader:
    def __init__(self, scale=0.5, gray=False, min_score=0.5, buffer_size=5, engine_name=None):
        self.scale = scale
        self.gray = gray
        self.min_score = min_score
        self.engine_name = (engine_name or OCR_ENGINE).strip().lower()
        self._paddle_debug_dumped = False
        self.engine = self._create_engine()

        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        # buffer circolare dei frame
        self.frames = deque(maxlen=buffer_size)

        self.frame_id = 0

    def _is_paddle_gpu_available(self):
        try:
            import paddle
        except ImportError:
            return False

        try:
            return bool(
                paddle.device.is_compiled_with_cuda()
                and paddle.device.cuda.device_count() > 0
            )
        except Exception:
            return False

    def _build_paddleocr_kwargs(self, paddle_ocr_class):
        use_gpu = self._is_paddle_gpu_available()
        device = "gpu" if use_gpu else "cpu"
        kwargs = {}

        try:
            parameters = inspect.signature(paddle_ocr_class.__init__).parameters
        except (TypeError, ValueError):
            parameters = {}

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        defaults = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "lang": "en",
            "device": device,
            "enable_mkldnn": False,
        }

        for key, value in defaults.items():
            if key in parameters or accepts_var_kwargs:
                kwargs[key] = value

        if "device" not in kwargs:
            if "use_gpu" in parameters:
                kwargs["use_gpu"] = use_gpu
            if "lang" in parameters and "lang" not in kwargs:
                kwargs["lang"] = "en"
            if "use_angle_cls" in parameters:
                kwargs["use_angle_cls"] = False

        print(f"PaddleOCR avviato con {'CUDA' if use_gpu else 'CPU'}")
        return kwargs

    def _create_engine(self):
        if self.engine_name == "rapidocr":
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "RapidOCR non installato. Installa il pacchetto 'rapidocr-onnxruntime' oppure cambia OCR_ENGINE."
                ) from exc
            return RapidOCR()

        if self.engine_name == "paddleocr":
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise RuntimeError(
                    "PaddleOCR non installato. Installa il pacchetto 'paddleocr' oppure cambia OCR_ENGINE."
                ) from exc

            kwargs = self._build_paddleocr_kwargs(PaddleOCR)
            return PaddleOCR(**kwargs)

        raise ValueError(f"OCR engine non supportato: {self.engine_name}")


    def _grab_loop(self):
        import subprocess
        import time
        import cv2
        import numpy as np

        remote_file = "/data/local/tmp/__cap.png"
        consecutive_errors = 0
        next_capture_time = time.monotonic()

        while self.running:
            now = time.monotonic()
            if now < next_capture_time:
                time.sleep(next_capture_time - now)

            capture_started = time.monotonic()

            try:
                # 1) screenshot sul telefono
                r1 = subprocess.run(
                    ["adb", "shell", "screencap", "-p", remote_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=8.0
                )

                if r1.returncode != 0:
                    err = r1.stderr.decode(errors="ignore").strip()
                    raise RuntimeError(f"screencap failed: {err or r1.returncode}")

                # 2) lettura del file dal telefono
                r2 = subprocess.run(
                    ["adb", "exec-out", "cat", remote_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=8.0
                )

                if r2.returncode != 0:
                    err = r2.stderr.decode(errors="ignore").strip()
                    raise RuntimeError(f"cat failed: {err or r2.returncode}")

                data = r2.stdout
                if not data:
                    raise RuntimeError("empty image data")

                # fix newline, utile in alcuni casi
                data = data.replace(b"\r\r\n", b"\n")

                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise RuntimeError("invalid PNG header")

                img_full = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img_full is None:
                    raise RuntimeError("cv2.imdecode failed")

                img = img_full

                real_scale = self.scale
                if real_scale != 1:
                    img = cv2.resize(
                        img,
                        None,
                        fx=real_scale,
                        fy=real_scale,
                        interpolation=cv2.INTER_AREA
                    )

                if self.gray:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                with self.lock:
                    # Tiene TUTTI i frame
                    self.frames.append((img_full, img, self.frame_id, capture_started))
                    self.frame_id += 1

                consecutive_errors = 0

            except subprocess.TimeoutExpired:
                consecutive_errors += 1
                print(f"Screenshot timeout ({consecutive_errors})")

            except Exception as e:
                consecutive_errors += 1
                print(f"Screenshot thread error ({consecutive_errors}):", e)

            if consecutive_errors >= 3:
                print("ADB recovery...")
                try:
                    subprocess.run(
                        ["adb", "reconnect"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0
                    )
                except Exception:
                    pass

                time.sleep(1.0)

                try:
                    subprocess.run(
                        ["adb", "kill-server"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0
                    )
                except Exception:
                    pass

                time.sleep(1.0)

                try:
                    subprocess.run(
                        ["adb", "start-server"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0
                    )
                except Exception:
                    pass

                time.sleep(1.0)
                consecutive_errors = 0

            # programma il prossimo scatto ogni 1 secondo "ideale"
            next_capture_time += 1.0

            # se siamo troppo indietro, non facciamo recuperi multipli inutili
            now = time.monotonic()
            if next_capture_time < now - 1.0:
                next_capture_time = now


    def start_capture(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._grab_loop, daemon=True)
        self.thread.start()

    def stop_capture(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None

    def get_latest_frame(self):
        with self.lock:
            if not self.frames:
                return None, None, -1

            frame = self.frames[-1]
            img_full, img, fid = frame[:3]
            return img_full.copy(), img.copy(), fid

    def get_next_frame(self):
        with self.lock:
            if not self.frames:
                return None, None, -1

            frame = self.frames.popleft()
            img_full, img, fid = frame[:3]
            return img_full, img, fid

    def fast_screenshot(self):
        _, img, _ = self.get_next_frame()

        return img

    def buffer_size(self):
        with self.lock:
            return len(self.frames)

    def _score_points_against_image(self, points, image_shape):
        img_h, img_w = image_shape[:2]
        penalty = 0.0
        for x, y in points:
            if x < 0:
                penalty += -x
            elif x > img_w:
                penalty += x - img_w

            if y < 0:
                penalty += -y
            elif y > img_h:
                penalty += y - img_h

        return penalty

    def _order_box_points(self, points):
        if len(points) != 4:
            return []

        pts = np.array(points, dtype=np.float32)
        ordered = np.zeros((4, 2), dtype=np.float32)

        sums = pts.sum(axis=1)
        diffs = np.diff(pts, axis=1).reshape(-1)

        ordered[0] = pts[np.argmin(sums)]
        ordered[2] = pts[np.argmax(sums)]
        ordered[1] = pts[np.argmin(diffs)]
        ordered[3] = pts[np.argmax(diffs)]

        return ordered.tolist()

    def _normalize_box(self, box, image_shape=None):
        if box is None:
            return []

        points = []
        for point in box:
            if point is None:
                continue

            if hasattr(point, "tolist"):
                point = point.tolist()

            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue

            x = float(point[0])
            y = float(point[1])
            points.append([x, y])

        if len(points) != 4:
            return []

        if image_shape is not None:
            img_h, img_w = image_shape[:2]

            max_x = max(point[0] for point in points)
            max_y = max(point[1] for point in points)
            if max_x <= 1.5 and max_y <= 1.5:
                points = [[point[0] * img_w, point[1] * img_h] for point in points]

            swapped_points = [[point[1], point[0]] for point in points]
            direct_penalty = self._score_points_against_image(points, image_shape)
            swapped_penalty = self._score_points_against_image(swapped_points, image_shape)
            if swapped_penalty + 1e-6 < direct_penalty:
                points = swapped_points

            points = [
                [min(max(point[0], 0.0), float(img_w - 1)), min(max(point[1], 0.0), float(img_h - 1))]
                for point in points
            ]

        ordered_points = self._order_box_points(points)
        if len(ordered_points) != 4:
            return []

        return ordered_points

    def _normalize_ocr_item(self, box, text, score, image_shape=None):
        normalized_box = self._normalize_box(box, image_shape=image_shape)
        if len(normalized_box) < 4:
            return None

        return {
            "text": str(text).strip(),
            "score": float(score),
            "box": normalized_box,
        }

    def _run_rapidocr(self, img):
        result, elapse = self.engine(img)

        if elapse is None:
            ocr_time = 0.0
        elif isinstance(elapse, list):
            ocr_time = sum(elapse)
        else:
            ocr_time = float(elapse)

        texts = []
        if result:
            for box, text, score in result:
                normalized_item = self._normalize_ocr_item(box, text, score, image_shape=img.shape)
                if normalized_item is None or normalized_item["score"] < self.min_score:
                    continue
                texts.append(normalized_item)

        return texts, ocr_time

    def _extract_paddle_lines(self, result):
        if result is None:
            return []

        if isinstance(result, dict):
            return [result]

        if isinstance(result, list) and result:
            first_item = result[0]
            if isinstance(first_item, dict):
                return [first_item]
            if isinstance(first_item, list):
                return first_item
            return [first_item]

        return []

    def _iter_paddle_items(self, result):
        for item in self._extract_paddle_lines(result):
            if item is None:
                continue

            if isinstance(item, dict):
                boxes = item.get("dt_polys") or item.get("boxes") or item.get("polys") or []
                texts = item.get("rec_texts") or item.get("texts") or []
                scores = item.get("rec_scores") or item.get("scores") or []

                max_len = max(len(boxes), len(texts), len(scores), 0)
                for idx in range(max_len):
                    box = boxes[idx] if idx < len(boxes) else None
                    text = texts[idx] if idx < len(texts) else ""
                    score = scores[idx] if idx < len(scores) else 0.0
                    yield box, text, score
                continue

            if isinstance(item, (list, tuple)) and len(item) >= 2:
                box = item[0]
                text_info = item[1]
                if not text_info or len(text_info) < 2:
                    continue
                yield box, text_info[0], text_info[1]

    def _debug_paddle_result_once(self, result, image_shape):
        if self._paddle_debug_dumped:
            return

        self._paddle_debug_dumped = True
        print(f"Paddle debug image_shape={image_shape}")
        print(f"Paddle debug result_type={type(result).__name__}")

        if isinstance(result, list) and result:
            first_item = result[0]
            print(f"Paddle debug first_item_type={type(first_item).__name__}")
            if isinstance(first_item, dict):
                print(f"Paddle debug first_item_keys={list(first_item.keys())}")
                boxes = first_item.get("dt_polys") or first_item.get("boxes") or first_item.get("polys") or []
                if len(boxes) > 0:
                    print(f"Paddle debug first_box={boxes[0]}")
            else:
                print(f"Paddle debug first_item={first_item}")
        elif isinstance(result, dict):
            print(f"Paddle debug result_keys={list(result.keys())}")
            boxes = result.get("dt_polys") or result.get("boxes") or result.get("polys") or []
            if len(boxes) > 0:
                print(f"Paddle debug first_box={boxes[0]}")
        else:
            print(f"Paddle debug result={result}")

    def _call_paddleocr(self, img):
        predict_method = getattr(self.engine, "predict", None)
        ocr_method = getattr(self.engine, "ocr", None)
        predict_failed_with_pir = False

        if callable(predict_method):
            try:
                return predict_method(img)
            except NotImplementedError as exc:
                message = str(exc)
                predict_failed_with_pir = "ConvertPirAttribute2RuntimeAttribute" in message
                if not predict_failed_with_pir or not callable(ocr_method):
                    raise

                print("PaddleOCR predict() ha fallito sul runtime oneDNN/PIR; provo fallback su ocr().")

        if callable(ocr_method):
            try:
                return ocr_method(img)
            except TypeError:
                return ocr_method(img, cls=False)
            except NotImplementedError as exc:
                message = str(exc)
                unsupported_pir = "ConvertPirAttribute2RuntimeAttribute" in message
                if not unsupported_pir:
                    raise
                if predict_failed_with_pir:
                    raise RuntimeError(
                        "PaddleOCR fallisce sul runtime oneDNN/PIR anche nel fallback ocr(). "
                        "Prova a usare RapidOCR oppure una versione diversa di Paddle/PaddleOCR."
                    ) from exc
                raise

        raise RuntimeError("PaddleOCR non espone un metodo OCR compatibile.")

    def _run_paddleocr(self, img, fallback_time):
        result = self._call_paddleocr(img)
        self._debug_paddle_result_once(result, img.shape)
        texts = []

        for box, text, score in self._iter_paddle_items(result):
            normalized_item = self._normalize_ocr_item(box, text, score, image_shape=img.shape)
            if normalized_item is None or normalized_item["score"] < self.min_score:
                continue

            texts.append(normalized_item)

        return texts, fallback_time

    def run_ocr(self, img):
        t0 = time.perf_counter()

        if self.engine_name == "rapidocr":
            texts, ocr_time = self._run_rapidocr(img)
        elif self.engine_name == "paddleocr":
            texts, ocr_time = self._run_paddleocr(img, time.perf_counter() - t0)
        else:
            raise ValueError(f"OCR engine non supportato: {self.engine_name}")

        if ocr_time <= 0:
            ocr_time = time.perf_counter() - t0

        return texts, ocr_time

    def draw_results(self, img, texts, ocr_time):
        out = img.copy()
        img_h, img_w = out.shape[:2]

        for item in texts:
            box = item["box"]
            text = item["text"]
            score = item["score"]

            pts = np.array([
                [
                    int(min(max(round(point[0]), 0), img_w - 1)),
                    int(min(max(round(point[1]), 0), img_h - 1)),
                ]
                for point in box
            ], dtype=np.int32)
            if len(pts) != 4:
                continue

            cv2.polylines(out, [pts], True, (0, 255, 0), 2)

            x, y = pts[0]

            cv2.putText(
                out,
                f"{text} {score:.2f}",
                (x, max(20, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA
            )

        cv2.putText(
            out,
            f"OCR {ocr_time:.3f}s",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA
        )

        return out
