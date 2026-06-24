"""OpenClaw Gateway WebSocket client for real-time file tracking."""

import asyncio
import json
import logging
import os
from typing import Callable

import websockets

log = logging.getLogger(__name__)

OPENCLAW_WS_URL = os.getenv('OPENCLAW_WS_URL', 'ws://localhost:18789')
OPENCLAW_TOKEN = os.getenv('OPENCLAW_TOKEN', '')


class OpenClawWSClient:
    """WebSocket client that subscribes to OpenClaw session events."""

    def __init__(self):
        self.ws = None
        self._running = False
        self._callbacks: list[Callable] = []
        self._session_user_map: dict[str, str] = {}

    def on_tool_event(self, callback: Callable):
        """Register callback: callback(session_key, tool_name, file_path, tool_result, user_id)"""
        self._callbacks.append(callback)

    def register_session_user(self, session_key: str, user_id: str):
        """Map an OpenClaw session key to an Open WebUI user ID."""
        if session_key:
            self._session_user_map[session_key] = user_id

    def get_user_for_session(self, session_key: str) -> str | None:
        """Look up the user ID for a given session key."""
        return self._session_user_map.get(session_key)

    async def connect(self):
        """Connect to OpenClaw Gateway and subscribe to session events."""
        self._running = True

        while self._running:
            try:
                headers = {}
                if OPENCLAW_TOKEN:
                    headers['Authorization'] = f'Bearer {OPENCLAW_TOKEN}'

                async with websockets.connect(OPENCLAW_WS_URL, additional_headers=headers) as ws:
                    self.ws = ws
                    log.info(f'Connected to OpenClaw Gateway: {OPENCLAW_WS_URL}')

                    # Wait for optional connect.challenge event
                    first_msg = json.loads(await ws.recv())
                    if first_msg.get('type') == 'event' and first_msg.get('event') == 'connect.challenge':
                        pass  # challenge received, proceed with connect

                    connect_msg = {
                        'type': 'req',
                        'id': 'connect-1',
                        'method': 'connect',
                        'params': {
                            'minProtocol': 3,
                            'maxProtocol': 4,
                            'client': {
                                'id': 'open-webui',
                                'version': '1.0.0',
                                'platform': 'linux',
                                'mode': 'operator'
                            },
                            'role': 'operator',
                            'scopes': ['operator.read'],
                            'auth': {'token': OPENCLAW_TOKEN} if OPENCLAW_TOKEN else {}
                        }
                    }
                    await ws.send(json.dumps(connect_msg))

                    # Read responses until we get the connect response
                    connect_ok = False
                    for _ in range(10):
                        resp = json.loads(await ws.recv())
                        if resp.get('id') == 'connect-1':
                            if resp.get('ok'):
                                connect_ok = True
                            break

                    if not connect_ok:
                        log.error(f'Connect failed: {resp}')
                        await asyncio.sleep(5)
                        continue

                    log.info('OpenClaw handshake successful')

                    await ws.send(json.dumps({
                        'type': 'req',
                        'id': 'sessions-list-1',
                        'method': 'sessions.list',
                        'params': {}
                    }))
                    sessions_resp = json.loads(await ws.recv())
                    sessions = sessions_resp.get('payload', {}).get('sessions', [])

                    for session in sessions:
                        session_key = session.get('key')
                        if session_key:
                            await ws.send(json.dumps({
                                'type': 'req',
                                'id': f'sub-{session_key}',
                                'method': 'sessions.messages.subscribe',
                                'params': {'sessionKey': session_key}
                            }))
                            log.info(f'Subscribed to session: {session_key}')

                    await self._listen_for_events(ws)

            except websockets.exceptions.ConnectionClosed:
                log.warning('OpenClaw WebSocket disconnected, reconnecting in 5s...')
            except Exception as e:
                log.error(f'OpenClaw WebSocket error: {e}')

            if self._running:
                await asyncio.sleep(5)

    async def _listen_for_events(self, ws):
        """Listen for incoming events and dispatch to callbacks."""
        async for message in ws:
            try:
                msg = json.loads(message)

                if msg.get('type') == 'event' and msg.get('event') == 'session.tool':
                    payload = msg.get('payload', {})
                    session_key = payload.get('sessionKey')
                    tool_name = payload.get('toolName')
                    tool_result = payload.get('result', {})

                    if tool_name in ('write', 'edit'):
                        file_path = tool_result.get('path') or tool_result.get('file_path')
                        if file_path:
                            user_id = self._session_user_map.get(session_key)
                            for cb in self._callbacks:
                                try:
                                    await cb(session_key, tool_name, file_path, tool_result, user_id)
                                except Exception as e:
                                    log.error(f'Callback error: {e}')

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log.error(f'Event processing error: {e}')

    async def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self.ws:
            await self.ws.close()


openclaw_ws_client = OpenClawWSClient()
