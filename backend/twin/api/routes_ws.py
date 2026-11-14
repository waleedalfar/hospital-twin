"""WebSocket streams (§6.1): `/ws?hospital=<id>` and `/ws/network`."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from twin.api.hub import NETWORK, Client
from twin.api.runtime import SimRuntime
from twin.common.ws import ErrorMessage

logger = logging.getLogger(__name__)
router = APIRouter()
CLOSE_POLICY = 1008
CLOSE_TRY_AGAIN = 1013


async def pump(websocket: WebSocket, client: Client) -> None:
    while True:
        text = await client.queue.get()
        if text is None:
            await websocket.close(code=CLOSE_TRY_AGAIN, reason="too slow; reconnect for a fresh snapshot")
            return
        await websocket.send_text(text)


async def serve(websocket: WebSocket, channel: str, first: str, rt: SimRuntime) -> None:
    client = rt.hub.subscribe(channel)
    try:
        await websocket.send_text(first)
        await pump(websocket, client)
    except WebSocketDisconnect:
        logger.info("WebSocket client left %s", channel)
    finally:
        rt.hub.unsubscribe(client)


async def refuse(websocket: WebSocket, message: str) -> None:
    await websocket.accept()
    await websocket.send_text(ErrorMessage(message=message).model_dump_json())
    await websocket.close(code=CLOSE_POLICY, reason=message[:120])


@router.websocket("/ws")
async def hospital_stream(websocket: WebSocket, hospital: str = "") -> None:
    rt: SimRuntime | None = getattr(websocket.app.state, "runtime", None)
    if rt is None or not rt.ready:
        await refuse(websocket, "The simulation is not running yet")
        return
    if hospital not in rt.sim.world.hospitals:
        await refuse(websocket, f"Unknown hospital {hospital!r}; use ?hospital=<id>")
        return
    await websocket.accept()
    # Built and subscribed in the same step of the event loop, so no tick falls between them.
    await serve(websocket, hospital, rt.snapshot_json(hospital), rt)


@router.websocket("/ws/network")
async def network_stream(websocket: WebSocket) -> None:
    rt: SimRuntime | None = getattr(websocket.app.state, "runtime", None)
    if rt is None or not rt.ready:
        await refuse(websocket, "The simulation is not running yet")
        return
    await websocket.accept()
    await serve(websocket, NETWORK, rt.network_json(), rt)
