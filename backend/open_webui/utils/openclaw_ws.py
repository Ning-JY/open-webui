"""OpenClaw Gateway WebSocket client with device authentication."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from typing import Callable

import websockets

log = logging.getLogger(__name__)

OPENCLAW_WS_URL = os.getenv('OPENCLAW_WS_URL', 'ws://localhost:18789')
OPENCLAW_TOKEN = os.getenv('OPENCLAW_TOKEN', '')


def _generate_device_identity():
    """Generate Ed25519 keypair and device identity."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Derive device ID from public key fingerprint
        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        device_id = hashlib.sha256(pub_bytes).hexdigest()[:32]

        return {
            'private_key': private_key,
            'public_key_b64': base64.b64encode(pub_bytes).decode(),
            'device_id': device_id,
        }
    except ImportError:
        log.warning('cryptography package not installed, device auth disabled')
        return None


def _sign_challenge(device_info: dict, nonce: str, token: str) -> dict:
    """Sign the challenge nonce with Ed25519 private key."""
    from cryptography.hazmat.primitives import serialization

    private_key = device_info['private_key']
    signed_at = int(time.time() * 1000)

    # v3 signature payload: platform + deviceFamily + device + client + role + scopes + token + nonce
    # Using a canonical JSON format for signing
    payload = json.dumps({
        'platform': 'linux',
        'deviceFamily': 'server',
        'deviceId': device_info['device_id'],
        'clientId': 'open-webui',
        'clientVersion': '1.0.0',
        'role': 'operator',
        'scopes': ['operator.read', 'operator.write'],
        'token': token,
        'nonce': nonce,
        'signedAt': signed_at,
    }, sort_keys=True, separators=(',', ':'))

    signature = private_key.sign(payload.encode())

    return {
        'id': device_info['device_id'],
        'publicKey': device_info['public_key_b64'],
        'signature': base64.b64encode(signature).decode(),
        'signedAt': signed_at,
        'nonce': nonce,
    }


class OpenClawWSClient:
    """WebSocket client with device authentication for OpenClaw Gateway."""

    def __init__(self):
        self.ws = None
        self._running = False
        self._callbacks: list[Callable] = []
        self._session_user_map: dict[str, str] = {}
        self._device_info = _generate_device_identity()
        self._device_token: str | None = None

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
        """Connect to OpenClaw Gateway with device authentication."""
        self._running = True

        while self._running:
            try:
                headers = {}
                if OPENCLAW_TOKEN:
                    headers['Authorization'] = f'Bearer {OPENCLAW_TOKEN}'

                async with websockets.connect(OPENCLAW_WS_URL, additional_headers=headers) as ws:
                    self.ws = ws
                    log.info(f'Connected to OpenClaw Gateway: {OPENCLAW_WS_URL}')

                    # Step 1: Wait for connect.challenge
                    nonce = None
                    first_msg = json.loads(await ws.recv())
                    if first_msg.get('type') == 'event' and first_msg.get('event') == 'connect.challenge':
                        nonce = first_msg.get('payload', {}).get('nonce')
                        log.info(f'Received connect.challenge with nonce: {nonce[:16]}...')

                    if not nonce:
                        log.error('No connect.challenge received')
                        await asyncio.sleep(5)
                        continue

                    # Step 2: Build connect params with device identity
                    connect_params = {
                        'minProtocol': 3,
                        'maxProtocol': 4,
                        'client': {
                            'id': 'open-webui',
                            'version': '1.0.0',
                            'platform': 'linux',
                            'mode': 'operator'
                        },
                        'role': 'operator',
                        'scopes': ['operator.read', 'operator.write'],
                        'auth': {},
                    }

                    # Use device token if we have one, otherwise use shared token
                    if self._device_token:
                        connect_params['auth']['token'] = self._device_token
                    elif OPENCLAW_TOKEN:
                        connect_params['auth']['token'] = OPENCLAW_TOKEN

                    # Step 3: Add device identity with signature
                    if self._device_info:
                        device_sig = _sign_challenge(self._device_info, nonce, connect_params['auth'].get('token', ''))
                        connect_params['device'] = device_sig
                    else:
                        log.warning('No device identity, connect may fail')

                    # Step 4: Send connect
                    connect_msg = {
                        'type': 'req',
                        'id': 'connect-1',
                        'method': 'connect',
                        'params': connect_params,
                    }
                    await ws.send(json.dumps(connect_msg))

                    # Step 5: Read responses until we get connect response
                    connect_ok = False
                    resp = None
                    for _ in range(10):
                        resp = json.loads(await ws.recv())
                        if resp.get('id') == 'connect-1':
                            if resp.get('ok'):
                                connect_ok = True
                                # Save device token for reconnection
                                auth = resp.get('payload', {}).get('auth', {})
                                if auth.get('deviceToken'):
                                    self._device_token = auth['deviceToken']
                                    log.info('Received device token for reconnection')
                            break

                    if not connect_ok:
                        error = resp.get('error', {}) if resp else {}
                        log.error(f'Connect failed: {error}')
                        await asyncio.sleep(5)
                        continue

                    log.info('OpenClaw handshake successful')

                    # Step 6: Subscribe to sessions
                    await self._subscribe_sessions(ws)

                    # Step 7: Listen for events
                    await self._listen_for_events(ws)

            except websockets.exceptions.ConnectionClosed:
                log.warning('OpenClaw WebSocket disconnected, reconnecting in 5s...')
            except Exception as e:
                log.error(f'OpenClaw WebSocket error: {e}')

            if self._running:
                await asyncio.sleep(5)

    async def _subscribe_sessions(self, ws):
        """Subscribe to all active sessions."""
        try:
            await ws.send(json.dumps({
                'type': 'req',
                'id': 'sessions-list-1',
                'method': 'sessions.list',
                'params': {}
            }))

            # Read until we get the sessions list response
            for _ in range(20):
                resp = json.loads(await ws.recv())
                if resp.get('id') == 'sessions-list-1':
                    sessions = resp.get('payload', {}).get('sessions', [])
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
                    break
        except Exception as e:
            log.error(f'Failed to subscribe sessions: {e}')

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
