from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional, Dict, Any


class ParadexWSFills:
    """
    Minimal Paradex WebSocket fills listener.

    This implementation attempts JSON-RPC auth using a bearer token exposed by the SDK
    (if available), subscribes to a private fills/orders channel, and forwards any fills
    to the provided callback.

    If the connection/auth fails, callers should fall back to polling.
    """

    def __init__(
        self,
        ws_url: str,
        get_bearer: Callable[[], Optional[str]],
        on_fill: Callable[[Dict[str, Any]], asyncio.Future],
    ):
        self.ws_url = ws_url
        self.get_bearer = get_bearer
        self.on_fill = on_fill
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                pass

    async def _run(self) -> None:
        try:
            import websockets
        except Exception:
            self.logger.warning("websockets package not available; WS fills disabled")
            return

        retry_delay = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.logger.info("Paradex WS connected")

                    # Authenticate if bearer token is available
                    bearer = None
                    try:
                        bearer = self.get_bearer()
                    except Exception:
                        bearer = None

                    if bearer:
                        auth_msg = {
                            "jsonrpc": "2.0",
                            "method": "auth",
                            "params": {"bearer": bearer},
                            "id": 1,
                        }
                        await ws.send(json.dumps(auth_msg))
                        auth_resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        self.logger.debug(f"WS auth response: {auth_resp}")

                    # Subscribe to fills channel as per Paradex documentation
                    # https://docs.paradex.trade/ws/web-socket-channels/fills/fills
                    # The correct format is just "fills" channel, no market_symbol parameter
                    subs = [
                        # Subscribe to fills channel (no market_symbol parameter needed)
                        {"jsonrpc": "2.0", "method": "subscribe", "params": {"channel": "fills"}, "id": 1},
                        # Also try orders channel
                        {"jsonrpc": "2.0", "method": "subscribe", "params": {"channel": "orders"}, "id": 2},
                    ]
                    for msg in subs:
                        try:
                            await ws.send(json.dumps(msg))
                            resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            resp_data = json.loads(resp)
                            if resp_data.get("error"):
                                self.logger.warning(f"WS subscription failed for {msg['params']['channel']}: {resp_data['error']}")
                            else:
                                self.logger.info(f"WS subscription successful for {msg['params']['channel']}")
                        except Exception as e:
                            self.logger.warning(f"WS subscription error for {msg['params']['channel']}: {e}")
                            continue

                    retry_delay = 1.0
                    while not self._stop.is_set():
                        raw = await ws.recv()
                        data = json.loads(raw)
                        
                        # DEBUG: Log only fill-related messages
                        if "fills" in str(data).lower() or "order" in str(data).lower():
                            self.logger.info(f"🔍 WS Fill Message: {data}")
                        
                        # Heuristic parsing for fills
                        params = data.get("params") if isinstance(data, dict) else None
                        if not params:
                            continue
                        event = params.get("data") or params
                        if not isinstance(event, dict):
                            continue

                        # Parse fills according to Paradex WebSocket format
                        # https://docs.paradex.trade/ws/web-socket-channels/fills/fills
                        side = event.get("side", "").upper()
                        filled = event.get("size", 0)  # Paradex uses "size" for filled amount
                        price = event.get("price", 0)
                        order_id = event.get("order_id", "")

                        try:
                            if side and filled:
                                await self.on_fill({
                                    "side": side,
                                    "filled": float(filled),
                                    "price": float(price) if price is not None else 0.0,
                                    "order_id": order_id,
                                })
                        except Exception:
                            continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning(f"Paradex WS error: {e}; reconnecting in {retry_delay:.1f}s")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)


