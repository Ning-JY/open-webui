"""File Space API - files grouped by conversation/session."""

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from open_webui.internal.db import Base, get_async_db_context
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from open_webui.internal.db import get_async_session

log = logging.getLogger(__name__)

router = APIRouter()


@router.on_event('startup')
async def file_space_startup():
    if os.getenv('OPENCLAW_WS_URL'):
        start_openclaw_poll()

    from open_webui.utils.openclaw_ws import openclaw_ws_client

    async def _track_openclaw_file(session_key, tool_name, file_path, tool_result, user_id=None):
        try:
            from open_webui.internal.db import get_async_db_context

            filename = file_path.split('/')[-1] if file_path else None
            if not filename:
                return

            file_type = detect_file_type(filename)
            file_size = tool_result.get('size', 0) or len(tool_result.get('content', ''))

            owner = user_id or 'openclaw'

            async with get_async_db_context() as db:
                existing = await FileSpace.get_files(
                    user_id=owner,
                    session_id=session_key,
                    db=db,
                )
                if not any(f.filename == filename for f in existing):
                    form = FileSpaceForm(
                        session_id=session_key,
                        conversation_title=f'OpenClaw Agent - {session_key}',
                        filename=filename,
                        file_path=f'openclaw://workspace/{file_path}',
                        file_size=file_size,
                        mime_type=None,
                        file_type=file_type,
                    )
                    await FileSpace.insert(owner, form, db=db)
                    log.info(f'Tracked OpenClaw file: {filename} (session: {session_key}, user: {owner})')
        except Exception as e:
            log.error(f'Error tracking OpenClaw file: {e}')

    openclaw_ws_client.on_tool_event(_track_openclaw_file)
    asyncio.create_task(openclaw_ws_client.connect())
    log.info('OpenClaw WebSocket subscriber started')


# --- Database Model ---

class FileSpaceEntry(Base):
    __tablename__ = 'file_space_entry'

    id = Column(Text, primary_key=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True, nullable=True)
    conversation_id = Column(String, index=True, nullable=True)
    conversation_title = Column(Text, nullable=True)
    filename = Column(Text, nullable=False)
    file_path = Column(Text, nullable=True)
    file_size = Column(BigInteger, default=0)
    mime_type = Column(Text, nullable=True)
    file_type = Column(String(20), default='other')
    created_at = Column(BigInteger, index=True)


class FileSpaceEntryModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    session_id: str | None = None
    conversation_id: str | None = None
    conversation_title: str | None = None
    filename: str
    file_path: str | None = None
    file_size: int | None = 0
    mime_type: str | None = None
    file_type: str | None = 'other'
    created_at: int


class FileSpaceForm(BaseModel):
    session_id: str | None = None
    conversation_id: str | None = None
    conversation_title: str | None = None
    filename: str
    file_path: str | None = None
    file_size: int = 0
    mime_type: str | None = None
    file_type: str | None = None


# --- File Type Detection ---

EXTENSION_MAP = {
    # Documents
    '.md': 'document', '.txt': 'document', '.doc': 'document', '.docx': 'document',
    '.pdf': 'document', '.rtf': 'document', '.odt': 'document',
    # Spreadsheets
    '.xls': 'spreadsheet', '.xlsx': 'spreadsheet', '.csv': 'spreadsheet',
    '.ods': 'spreadsheet',
    # Images
    '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image',
    '.svg': 'image', '.webp': 'image', '.bmp': 'image', '.ico': 'image',
    # Code
    '.py': 'code', '.js': 'code', '.ts': 'code', '.jsx': 'code', '.tsx': 'code',
    '.html': 'code', '.css': 'code', '.json': 'code', '.yaml': 'code', '.yml': 'code',
    '.xml': 'code', '.sql': 'code', '.sh': 'code', '.bash': 'code',
    '.c': 'code', '.cpp': 'code', '.h': 'code', '.java': 'code', '.go': 'code',
    '.rs': 'code', '.rb': 'code', '.php': 'code', '.swift': 'code',
    # PPT
    '.ppt': 'ppt', '.pptx': 'ppt', '.odp': 'ppt',
}


def detect_file_type(filename: str, mime_type: str | None = None) -> str:
    ext = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return EXTENSION_MAP.get(ext, 'other')


# --- DB Operations ---

class FileSpaceTable:
    async def insert(self, user_id: str, form: FileSpaceForm, db: AsyncSession | None = None) -> FileSpaceEntryModel:
        async with get_async_db_context(db) as db:
            entry = FileSpaceEntry(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=form.session_id,
                conversation_id=form.conversation_id,
                conversation_title=form.conversation_title,
                filename=form.filename,
                file_path=form.file_path,
                file_size=form.file_size,
                mime_type=form.mime_type,
                file_type=form.file_type or detect_file_type(form.filename, form.mime_type),
                created_at=int(time.time()),
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            return FileSpaceEntryModel.model_validate(entry)

    async def get_files(
        self,
        user_id: str,
        file_type: str | None = None,
        session_id: str | None = None,
        search: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[FileSpaceEntryModel]:
        async with get_async_db_context(db) as db:
            stmt = select(FileSpaceEntry).where(FileSpaceEntry.user_id == user_id)
            if file_type and file_type != 'all':
                stmt = stmt.where(FileSpaceEntry.file_type == file_type)
            if session_id:
                stmt = stmt.where(FileSpaceEntry.session_id == session_id)
            if search:
                stmt = stmt.where(FileSpaceEntry.filename.ilike(f'%{search}%'))
            stmt = stmt.order_by(FileSpaceEntry.created_at.desc())
            result = await db.execute(stmt)
            return [FileSpaceEntryModel.model_validate(r) for r in result.scalars().all()]

    async def get_stats(self, user_id: str, db: AsyncSession | None = None) -> dict:
        async with get_async_db_context(db) as db:
            stmt = (
                select(FileSpaceEntry.file_type, func.count(FileSpaceEntry.id), func.coalesce(func.sum(FileSpaceEntry.file_size), 0))
                .where(FileSpaceEntry.user_id == user_id)
                .group_by(FileSpaceEntry.file_type)
            )
            result = await db.execute(stmt)
            rows = result.all()
            types = {}
            total_count = 0
            total_size = 0
            for row in rows:
                types[row[0]] = {'count': row[1], 'size': row[2]}
                total_count += row[1]
                total_size += row[2]
            return {
                'types': types,
                'total_count': total_count,
                'total_size': total_size,
            }

    async def delete(self, id: str, user_id: str, db: AsyncSession | None = None) -> bool:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(FileSpaceEntry).where(FileSpaceEntry.id == id, FileSpaceEntry.user_id == user_id)
            )
            entry = result.scalars().first()
            if entry:
                await db.delete(entry)
                await db.commit()
                return True
            return False

    async def delete_all(self, user_id: str, db: AsyncSession | None = None) -> bool:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(FileSpaceEntry).where(FileSpaceEntry.user_id == user_id))
            entries = result.scalars().all()
            for entry in entries:
                await db.delete(entry)
            await db.commit()
            return True


FileSpace = FileSpaceTable()


# --- API Routes ---

@router.get('/files')
async def list_files(
    file_type: str | None = Query(None),
    session_id: str | None = Query(None),
    search: str | None = Query(None),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    files = await FileSpace.get_files(user.id, file_type=file_type, session_id=session_id, search=search, db=db)
    return {'files': files}


@router.get('/files/grouped')
async def list_files_grouped(
    file_type: str | None = Query(None),
    search: str | None = Query(None),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    files = await FileSpace.get_files(user.id, file_type=file_type, search=search, db=db)

    grouped = defaultdict(list)
    for f in files:
        key = f.session_id or f.conversation_id or 'unknown'
        grouped[key].append(f)

    result = []
    for key, group_files in grouped.items():
        first = group_files[0]
        result.append({
            'session_id': key,
            'conversation_title': first.conversation_title or key,
            'files': group_files,
            'file_count': len(group_files),
        })

    return {'groups': result}


@router.get('/stats')
async def get_stats(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    return await FileSpace.get_stats(user.id, db=db)


@router.post('/files')
async def track_file(
    form: FileSpaceForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    entry = await FileSpace.insert(user.id, form, db=db)
    return entry


@router.delete('/files/{id}')
async def delete_file(
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    success = await FileSpace.delete(id, user.id, db=db)
    if success:
        return {'message': 'Deleted'}
    return {'error': 'Not found'}


@router.delete('/files')
async def delete_all_files(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await FileSpace.delete_all(user.id, db=db)
    return {'message': 'All deleted'}


# ---------------------------------------------------------------------------
# OpenClaw Integration
# ---------------------------------------------------------------------------

OPENCLAW_WS_URL = os.getenv('OPENCLAW_WS_URL', 'ws://localhost:18789')
OPENCLAW_TOKEN = os.getenv('OPENCLAW_TOKEN', '')
OPENCLAW_POLL_INTERVAL = int(os.getenv('OPENCLAW_POLL_INTERVAL', '60'))  # seconds
_openclaw_synced_ids: set[str] = set()
_openclaw_poll_task_started = False


async def _openclaw_poll_loop():
    """Background task: poll OpenClaw for new artifacts and sync them."""
    global _openclaw_synced_ids

    while True:
        try:
            from open_webui.utils.openclaw_ws import openclaw_ws_client

            result = await openclaw_rpc('artifacts.list', {})
            if 'error' not in result:
                artifacts = result if isinstance(result, list) else result.get('artifacts', [])
                for art in artifacts:
                    art_id = art.get('id', '')
                    if art_id and art_id not in _openclaw_synced_ids:
                        _openclaw_synced_ids.add(art_id)
                        filename = art.get('name', art.get('filename', art_id))
                        file_size = art.get('size', 0)
                        mime_type = art.get('mimeType', art.get('contentType'))
                        session_key = art.get('sessionKey', art.get('sessionId'))
                        file_type = detect_file_type(filename, mime_type)

                        owner = openclaw_ws_client.get_user_for_session(session_key) or 'openclaw'

                        from open_webui.internal.db import get_async_db_context
                        async with get_async_db_context() as db:
                            form = FileSpaceForm(
                                session_id=session_key,
                                conversation_title=f'OpenClaw - {session_key or "workspace"}',
                                filename=filename,
                                file_path=f'openclaw://{art_id}',
                                file_size=file_size,
                                mime_type=mime_type,
                                file_type=file_type,
                            )
                            existing = await FileSpace.get_files(
                                user_id=owner,
                                session_id=session_key,
                                db=db,
                            )
                            if not any(f.filename == filename for f in existing):
                                await FileSpace.insert(owner, form, db=db)
                                log.info(f'Synced new artifact: {filename} (user: {owner})')
        except Exception as e:
            log.debug(f'OpenClaw poll error: {e}')

        await asyncio.sleep(OPENCLAW_POLL_INTERVAL)


def start_openclaw_poll():
    """Start the background polling task (call once at startup)."""
    global _openclaw_poll_task_started
    if _openclaw_poll_task_started:
        return
    _openclaw_poll_task_started = True
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_openclaw_poll_loop())
        log.info(f'OpenClaw poll started (interval={OPENCLAW_POLL_INTERVAL}s)')
    except Exception as e:
        log.warning(f'Failed to start OpenClaw poll: {e}')


async def openclaw_rpc(method: str, params: dict = None) -> dict:
    """Send an RPC call to OpenClaw Gateway via WebSocket."""
    import json
    import uuid

    try:
        import websockets
    except ImportError:
        return {'error': 'websockets package not installed. Run: pip install websockets'}

    extra_headers = {}
    if OPENCLAW_TOKEN:
        extra_headers['Authorization'] = f'Bearer {OPENCLAW_TOKEN}'

    try:
        async with websockets.connect(OPENCLAW_WS_URL, additional_headers=extra_headers) as ws:
            # Wait for optional connect.challenge event
            first_msg = json.loads(await ws.recv())
            if first_msg.get('type') == 'event' and first_msg.get('event') == 'connect.challenge':
                pass  # challenge received, proceed with connect

            # Send connect handshake (OpenClaw Gateway protocol)
            connect_id = f'connect-{uuid.uuid4().hex[:8]}'
            connect_msg = {
                'type': 'req',
                'id': connect_id,
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
                if resp.get('id') == connect_id:
                    if resp.get('ok'):
                        connect_ok = True
                    break

            if not connect_ok:
                return {'error': 'OpenClaw connect failed'}

            # Send RPC request
            rpc_id = f'rpc-{uuid.uuid4().hex[:8]}'
            payload = {'type': 'req', 'id': rpc_id, 'method': method, 'params': params or {}}
            await ws.send(json.dumps(payload))

            # Read responses until we get our RPC response
            for _ in range(10):
                resp = json.loads(await ws.recv())
                if resp.get('id') == rpc_id:
                    if resp.get('ok'):
                        return resp.get('payload', {})
                    else:
                        return {'error': resp.get('error', 'Unknown error')}

            return {'error': 'No response from OpenClaw'}
    except Exception as e:
        log.error(f'OpenClaw RPC error: {e}')
        return {'error': str(e)}


@router.get('/openclaw/artifacts')
async def list_openclaw_artifacts(
    session_key: str | None = Query(None),
    user=Depends(get_verified_user),
):
    """List artifacts from OpenClaw Gateway."""
    params = {}
    if session_key:
        params['sessionKey'] = session_key
    return await openclaw_rpc('artifacts.list', params)


@router.get('/openclaw/artifacts/{artifact_id}')
async def get_openclaw_artifact(
    artifact_id: str,
    user=Depends(get_verified_user),
):
    """Get artifact details from OpenClaw Gateway."""
    return await openclaw_rpc('artifacts.get', {'id': artifact_id})


@router.get('/openclaw/artifacts/{artifact_id}/download')
async def download_openclaw_artifact(
    artifact_id: str,
    user=Depends(get_verified_user),
):
    """Download artifact content from OpenClaw Gateway."""
    result = await openclaw_rpc('artifacts.get', {'id': artifact_id})
    if 'error' in result:
        return result

    filename = result.get('name', result.get('filename', artifact_id))
    content = result.get('content', '')
    content_type = result.get('mimeType', result.get('contentType', 'application/octet-stream'))

    if isinstance(content, str) and content.startswith('data:'):
        import base64
        content_type, encoded = content.split(',', 1)
        content = base64.b64decode(encoded)
    elif isinstance(content, str):
        content = content.encode('utf-8')

    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=content_type,
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get('/openclaw/workspace')
async def list_openclaw_workspace(
    agent_id: str | None = Query(None),
    user=Depends(get_verified_user),
):
    """List files in OpenClaw agent workspace."""
    params = {}
    if agent_id:
        params['agentId'] = agent_id
    return await openclaw_rpc('agents.files.list', params)


@router.get('/openclaw/workspace/file')
async def get_openclaw_workspace_file(
    path: str = Query(...),
    agent_id: str | None = Query(None),
    user=Depends(get_verified_user),
):
    """Read a file from OpenClaw agent workspace."""
    params = {'path': path}
    if agent_id:
        params['agentId'] = agent_id
    return await openclaw_rpc('agents.files.get', params)


@router.post('/openclaw/sync')
async def sync_openclaw_artifacts(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Sync OpenClaw artifacts into file space."""
    from open_webui.utils.openclaw_ws import openclaw_ws_client

    result = await openclaw_rpc('artifacts.list', {})
    if 'error' in result:
        return result

    artifacts = result if isinstance(result, list) else result.get('artifacts', [])
    synced = 0

    for art in artifacts:
        art_id = art.get('id', '')
        filename = art.get('name', art.get('filename', art_id))
        file_size = art.get('size', 0)
        mime_type = art.get('mimeType', art.get('contentType'))
        session_key = art.get('sessionKey', art.get('sessionId'))

        if session_key:
            openclaw_ws_client.register_session_user(session_key, user.id)

        file_type = detect_file_type(filename, mime_type)

        form = FileSpaceForm(
            session_id=session_key,
            conversation_title=f'OpenClaw - {session_key or "workspace"}',
            filename=filename,
            file_path=f'openclaw://{art_id}',
            file_size=file_size,
            mime_type=mime_type,
            file_type=file_type,
        )
        await FileSpace.insert(user.id, form, db=db)
        synced += 1

    return {'synced': synced}

