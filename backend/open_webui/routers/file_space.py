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
    log.info('File space module loaded (CLI-based OpenClaw integration)')


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


def _extract_files_from_transcript(transcript: str) -> list[dict]:
    """Extract file paths from transcript text.

    Looks for:
    - canvas:// links
    - write/edit tool results with file paths
    - file paths in code blocks
    """
    import re

    files = []
    seen = set()

    # Pattern 1: canvas:// protocol links
    for match in re.finditer(r'canvas://([^\s\)"\']+)', transcript):
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            filename = path.split('/')[-1]
            files.append({
                'filename': filename,
                'file_path': f'openclaw://canvas/{path}',
            })

    # Pattern 2: workspace file paths (e.g., /workspace/agent/file.ext)
    for match in re.finditer(r'(?:/workspace/[^\s\)"\']+?\.\w{1,10})', transcript):
        path = match.group(0)
        if path not in seen:
            seen.add(path)
            filename = path.split('/')[-1]
            files.append({
                'filename': filename,
                'file_path': f'openclaw://{path}',
            })

    # Pattern 3: relative file paths after write/edit mentions
    for match in re.finditer(r'(?:wrote|created|saved|written to|edit(?:ed)?)\s+(?:file\s+)?[`"\']?([^\s`"\']+\.\w{1,10})', transcript, re.IGNORECASE):
        path = match.group(1)
        if path not in seen and not path.startswith('http'):
            seen.add(path)
            filename = path.split('/')[-1]
            files.append({
                'filename': filename,
                'file_path': f'openclaw://{path}',
            })

    return files


@router.get('/openclaw/sessions')
async def list_openclaw_sessions(
    user=Depends(get_verified_user),
):
    """List OpenClaw sessions via CLI."""
    result = await openclaw_cli('sessions', '--all-agents')
    if isinstance(result, dict) and 'error' in result:
        return result
    return result or {'sessions': []}


@router.get('/openclaw/transcripts/{session_selector:path}')
async def get_openclaw_transcript(
    session_selector: str,
    user=Depends(get_verified_user),
):
    """Get OpenClaw transcript via CLI."""
    result = await openclaw_cli('transcripts', 'show', session_selector)
    return result or {'error': 'Transcript not found'}


@router.post('/openclaw/sync')
async def sync_openclaw_artifacts(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Sync OpenClaw files into file space via CLI.

    Flow:
    1. List all sessions via `openclaw sessions --all-agents --json`
    2. For each session, get transcript via `openclaw transcripts show --json`
    3. Extract file paths from transcript content
    4. Register files in file_space DB
    """
    # Step 1: Get all sessions
    sessions_result = await openclaw_cli('sessions', '--all-agents')
    if isinstance(sessions_result, dict) and 'error' in sessions_result:
        return sessions_result

    sessions = sessions_result.get('sessions', []) if isinstance(sessions_result, dict) else []
    if not sessions:
        return {'synced': 0, 'message': 'No sessions found'}

    # Step 2: Get transcripts list
    transcripts_result = await openclaw_cli('transcripts', 'list')
    if isinstance(transcripts_result, dict) and 'error' in transcripts_result:
        return transcripts_result

    transcript_list = []
    if isinstance(transcripts_result, list):
        transcript_list = transcripts_result
    elif isinstance(transcripts_result, dict):
        transcript_list = transcripts_result.get('transcripts', [])

    # Step 3: Process each transcript to extract files
    synced = 0
    for entry in transcript_list:
        selector = entry.get('selector', '')
        title = entry.get('title', selector)

        if not selector:
            continue

        # Get transcript content
        transcript_result = await openclaw_cli('transcripts', 'show', selector)
        if isinstance(transcript_result, dict) and 'error' in transcript_result:
            continue

        summary = ''
        if isinstance(transcript_result, dict):
            summary = transcript_result.get('summary', '')

        if not summary:
            continue

        # Extract file paths from transcript
        extracted_files = _extract_files_from_transcript(summary)

        for file_info in extracted_files:
            filename = file_info['filename']
            file_path = file_info['file_path']

            # Check if already exists
            existing = await FileSpace.get_files(
                user_id=user.id,
                session_id=selector,
                db=db,
            )
            if any(f.filename == filename for f in existing):
                continue

            file_type = detect_file_type(filename)
            form = FileSpaceForm(
                session_id=selector,
                conversation_title=f'OpenClaw - {title}',
                filename=filename,
                file_path=file_path,
                file_size=0,
                mime_type=None,
                file_type=file_type,
            )
            await FileSpace.insert(user.id, form, db=db)
            synced += 1
            log.info(f'Synced file from transcript: {filename} (session: {selector})')

    return {'synced': synced}

