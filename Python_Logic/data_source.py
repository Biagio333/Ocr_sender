import json
import socket
import threading
import time
from collections import deque
from pathlib import Path

from data_store import load_payloads_from_path


class PayloadBuffer:
    def __init__(self):
        self._items = deque()
        self._lock = threading.Lock()

    def push_packet(self, payload: dict):
        with self._lock:
            self._items.append(payload)

    def pop_packet(self) -> dict | None:
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def wait_packet(self, poll_interval_sec: float = 0.05) -> dict:
        while True:
            payload = self.pop_packet()
            if payload is not None:
                return payload
            time.sleep(poll_interval_sec)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._items)


class SocketPayloadReceiver:
    def __init__(self, host: str, port: int, payload_buffer: PayloadBuffer):
        self.host = host
        self.port = port
        self.payload_buffer = payload_buffer
        self._thread = None
        self._closed = False
        self._stop_requested = False

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_closed(self) -> bool:
        return self._closed

    def stop(self):
        self._stop_requested = True

    def _run(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(1)

        try:
            print(f"In attesa di dati dall'app su {self.host}:{self.port} ...")
            while not self._stop_requested:
                conn, addr = server.accept()
                print("Connesso da:", addr)
                buffer = ""

                try:
                    while not self._stop_requested:
                        data = conn.recv(1024 * 100)
                        if not data:
                            break

                        buffer += data.decode("utf-8")

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            self.payload_buffer.push_packet(json.loads(line))

                    trailing = buffer.strip()
                    if trailing:
                        self.payload_buffer.push_packet(json.loads(trailing))
                finally:
                    conn.close()
                    if not self._stop_requested:
                        print("Connessione socket chiusa, resto in attesa di una nuova connessione...")
        finally:
            self._closed = True
            server.close()


def create_replay_buffer(path: str | Path) -> PayloadBuffer:
    payload_buffer = PayloadBuffer()
    for payload in load_payloads_from_path(path):
        payload_buffer.push_packet(payload)
    return payload_buffer
