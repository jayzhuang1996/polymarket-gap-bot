"""WebSocket endpoint and broadcast worker."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import engine.state as state
from engine.session import get_session_state

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state.connected_clients.add(ws)

    await ws.send_json({"type": "markets", "markets": state.market_list})
    await ws.send_json({"type": "quotes_all", "quotes": list(state.current_quotes.values())})
    await ws.send_json(get_session_state())

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.connected_clients.discard(ws)


async def broadcast_worker():
    """Drain broadcast_queue and send each message to all connected clients."""
    while True:
        msg  = await state.broadcast_queue.get()
        dead = []
        for ws in list(state.connected_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            state.connected_clients.discard(ws)
