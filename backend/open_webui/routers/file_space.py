"""File Space API - files grouped by conversation/session."""

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

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
    from open_webui.utils.openclaw_ws import openclaw_ws_client

    async def _track_openclaw_file(session_key, tool_name, file_path, tool_result, user_id=None):
        try:
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
    log.info('OpenClaw WebSocket subscriber started (device auth enabled)')


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
# OpenClaw Integration (CLI-based)
# ---------------------------------------------------------------------------

OPENCLAW_STATE_DIR = os.getenv('OPENCLAW_STATE_DIR', os.path.expanduser('~/.openclaw'))
OPENCLAW_POLL_INTERVAL = int(os.getenv('OPENCLAW_POLL_INTERVAL', '60'))  # seconds


async def openclaw_cli(*args: str) -> dict | list | None:
    """Run an openclaw CLI command and return parsed JSON output."""
    import json as _json

    cmd = ['openclaw'] + list(args) + ['--json']
    log.debug(f'Running: {" ".join(cmd)}')

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace').strip()
            log.error(f'openclaw CLI error: {error_msg}')
            return {'error': error_msg}

        output = stdout.decode('utf-8', errors='replace').strip()
        if not output:
            return None

        return _json.loads(output)
    except FileNotFoundError:
        return {'error': 'openclaw CLI not found. Install OpenClaw first.'}
    except asyncio.TimeoutError:
        return {'error': 'openclaw CLI timed out'}
    except Exception as e:
        log.error(f'openclaw CLI error: {e}')
        return {'error': str(e)}





@router.post('/openclaw/sync')
async def sync_openclaw_artifacts(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Sync OpenClaw workspace files into file space.

    Scans:
    1. ~/.openclaw/workspace/ - agent workspace files
    2. ~/.openclaw/workspace/canvas/ - canvas-generated files
    """
    workspace_dir = Path(OPENCLAW_STATE_DIR) / 'workspace'
    canvas_dir = workspace_dir / 'canvas'

    synced = 0

    # Scan workspace directory (excluding canvas subfolder and dotfiles)
    if workspace_dir.exists():
        for item in workspace_dir.iterdir():
            if item.name.startswith('.'):
                continue
            if item.name == 'canvas':
                continue
            if item.is_file():
                synced += await _register_workspace_file(user.id, item, 'workspace', db)

    # Scan canvas directory
    if canvas_dir.exists():
        for item in canvas_dir.rglob('*'):
            if item.is_file() and not item.name.startswith('.'):
                synced += await _register_workspace_file(user.id, item, 'canvas', db)

    return {'synced': synced}


async def _register_workspace_file(
    user_id: str,
    file_path: Path,
    source: str,
    db: AsyncSession,
) -> int:
    """Register a single workspace file in file_space DB. Returns 1 if new, 0 if exists."""
    filename = file_path.name

    # Get file size
    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = 0

    # Build relative path for display
    if source == 'canvas':
        rel_path = f'canvas/{file_path.relative_to(Path(OPENCLAW_STATE_DIR) / "workspace" / "canvas")}'
    else:
        rel_path = filename

    # Check if already exists by filename + user
    existing = await FileSpace.get_files(user_id=user_id, db=db)
    if any(f.filename == filename and f.file_path and rel_path in f.file_path for f in existing):
        return 0

    file_type = detect_file_type(filename)
    form = FileSpaceForm(
        session_id=f'openclaw-{source}',
        conversation_title=f'OpenClaw {source.title()}',
        filename=filename,
        file_path=f'openclaw://{source}/{rel_path}',
        file_size=file_size,
        mime_type=None,
        file_type=file_type,
    )
    await FileSpace.insert(user_id, form, db=db)
    log.info(f'Synced workspace file: {filename} (source: {source}, size: {file_size})')
    return 1

