# cd C:\Users\cristiano.piacenti\AppData\Local\Android\Sdk\platform-tools
# adb devices
# adb reverse tcp:5000 tcp:5000

from typing import Optional

from config import (
    DATA_SOURCE,
    ENABLE_JSON_VIEWER,
    ENABLE_TABLE_VIEWER,
    PACKET_SAVE_DIR,
    REPLAY_INPUT_PATH,
    SAVE_INCOMING_PACKETS,
    SOCKET_HOST,
    SOCKET_PORT,
)

from data_source import (
    PayloadBuffer,
    SocketPayloadReceiver,
    create_replay_buffer,
)
from data_store import PacketStore
from payload_utils import payload_summary, pretty_payload
from table_mapper import TableStateMapper


def _load_viewers():
    try:
        import cv2
        from viewer import draw_results, show_image
        from viewer_table import show_table_view
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "unknown"
        print(
            "Viewer support disabled because the current Python interpreter is missing "
            f"`{missing_module}`. Install dependencies with "
            "`python3 -m pip install -r requirements.txt` to re-enable the viewers."
        )
        return None, None, None, None

    return cv2, draw_results, show_image, show_table_view


def build_payload_buffer() -> tuple[PayloadBuffer, Optional[SocketPayloadReceiver]]:
    if DATA_SOURCE == "socket":
        payload_buffer = PayloadBuffer()
        receiver = SocketPayloadReceiver(SOCKET_HOST, SOCKET_PORT, payload_buffer)
        receiver.start()
        return payload_buffer, receiver

    if DATA_SOURCE == "replay":
        return create_replay_buffer(REPLAY_INPUT_PATH), None

    raise ValueError(f"DATA_SOURCE non valida: {DATA_SOURCE}")


def get_next_payload(payload_buffer: PayloadBuffer) -> dict | None:
    return payload_buffer.pop_packet()


def main():
    cv2 = None
    draw_results = None
    show_image = None
    show_table_view = None
    json_viewer_enabled = ENABLE_JSON_VIEWER
    table_viewer_enabled = ENABLE_TABLE_VIEWER
    if ENABLE_JSON_VIEWER or ENABLE_TABLE_VIEWER:
        cv2, draw_results, show_image, show_table_view = _load_viewers()
        if cv2 is None:
            json_viewer_enabled = False
            table_viewer_enabled = False

    payload_buffer, receiver = build_payload_buffer()
    packet_store = None
    table_mapper = TableStateMapper()
    if DATA_SOURCE == "socket" and SAVE_INCOMING_PACKETS:
        packet_store = PacketStore(PACKET_SAVE_DIR)

    index = 0
    try:
        while True:
            payload = get_next_payload(payload_buffer)

            if payload is None:
                if DATA_SOURCE == "replay":
                    break

                if receiver is not None and receiver.is_closed() and payload_buffer.pending_count == 0:
                    break

                payload = payload_buffer.wait_packet()

            index += 1
            table_state = table_mapper.build_table(payload)

            #---------------------------------------------------
            #-- aspetto inizio mano per fare giocare il boot ---
            #---------------------------------------------------

            if False:
                print(f"[{index}] {payload_summary(payload)}")
                print(
                    "TableBase:",
                    f"street={table_state.street},",
                    f"pot={table_state.pot_amount},",
                    f"players={len(table_state.players)}"
                )
                for player in table_state.players:
                    print(
                        f"  P{player.player_index} "
                        f"name={player.name or '-'} "
                        f"stack={player.stack_amount} "
                        f"bet={player.bet_amount} "
                        f"action={player.inferred_action}"
                    )
                print(pretty_payload(payload))

            if packet_store is not None:
                saved_path = packet_store.save_payload(payload)
                print(f"Pacchetto salvato in: {saved_path}")

            if json_viewer_enabled:
                img = draw_results(payload)
                show_image(img)

            if table_viewer_enabled:
                show_table_view(table_state)
    finally:
        if cv2 is not None:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
