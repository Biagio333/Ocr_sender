import threading
import cv2
from flask import Flask, Response


class MJPEGDebugServer:
    """
    Server MJPEG semplice per mostrare un frame aggiornato dal programma principale.

    Uso:
        server = MJPEGDebugServer(host="0.0.0.0", port=5000)
        server.start()

        # nel loop:
        server.update_frame(img)
    """

    def __init__(self, host="127.0.0.1", port=5000, jpeg_quality=80):
        self.host = host
        self.port = port
        self.jpeg_quality = jpeg_quality

        self._app = Flask(__name__)
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread = None

        self._setup_routes()

    def _setup_routes(self):
        @self._app.route("/")
        def index():
            return """
            <html>
                <head><title>MJPEG Debug</title></head>
                <body style="background:#111;color:#eee;font-family:sans-serif">
                    <h3>Debug Stream</h3>
                    <img src="/video" style="max-width:100%;height:auto;border:1px solid #444;" />
                </body>
            </html>
            """

        @self._app.route("/video")
        def video():
            return Response(
                self._generate(),
                mimetype="multipart/x-mixed-replace; boundary=frame"
            )

    def _generate(self):
        while True:
            with self._lock:
                frame = None if self._frame is None else self._frame.copy()

            if frame is None:
                continue

            ok, jpg = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
            )

            if not ok:
                continue

            data = jpg.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                data +
                b"\r\n"
            )

    def update_frame(self, frame):
        with self._lock:
            self._frame = frame.copy()

    def start(self):
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._app.run,
            kwargs={
                "host": self.host,
                "port": self.port,
                "debug": False,
                "threaded": True,
                "use_reloader": False,
            },
            daemon=True,
        )
        self._thread.start()