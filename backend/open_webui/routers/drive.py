from __future__ import annotations

import json
import mimetypes
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from open_webui.env import DATA_DIR
from open_webui.internal.db import get_async_session
from open_webui.models.drive import (
    DRIVE_NODE_FILE,
    DRIVE_NODE_FOLDER,
    DRIVE_SPACE_PERSONAL,
    DRIVE_SPACE_SHARED,
    DriveCreateFolderForm,
    DriveDeleteForm,
    DriveListResponse,
    DriveMoveForm,
    DriveNode,
    DriveNodeModel,
    DriveNodes,
    DriveSaveToPersonalForm,
    DriveShareForm,
)
from open_webui.utils.auth import get_verified_user
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask


router = APIRouter()

DRIVE_STORAGE_DIR = DATA_DIR / 'drive_storage'
DRIVE_TMP_DIR = DATA_DIR / 'drive_tmp'
DRIVE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DRIVE_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_space(space: str | None) -> str:
    if space not in {DRIVE_SPACE_PERSONAL, DRIVE_SPACE_SHARED}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid drive space.')
    return space


def _ensure_admin(user) -> None:
    if user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin permission required.')


def _clean_name(name: str | None) -> str:
    name = (name or '').strip()
    if not name or name in {'.', '..'} or '/' in name or '\\' in name or '\x00' in name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid name.')
    return name


def _safe_relative_parts(path: str | None) -> list[str]:
    path = (path or '').replace('\\', '/').strip('/')
    if not path:
        return []

    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or any(part in {'', '.', '..'} for part in pure_path.parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid relative path.')
    if any('\x00' in part or ':' in part for part in pure_path.parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid relative path.')
    return [_clean_name(part) for part in pure_path.parts]


def _resolve_storage_path(storage_path: str | None) -> Path:
    if not storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='File is missing.')
    path = (DRIVE_STORAGE_DIR / storage_path).resolve()
    try:
        path.relative_to(DRIVE_STORAGE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='File is missing.')
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='File is missing.')
    return path


def _content_disposition(filename: str, inline: bool = False) -> dict[str, str]:
    disposition = 'inline' if inline else 'attachment'
    quoted = quote(filename)
    return {'Content-Disposition': f'{disposition}; filename="{quoted}"; filename*=UTF-8\'\'{quoted}'}


async def _assert_node_access(
    node_id: str | None,
    user,
    db: AsyncSession,
    *,
    write: bool = False,
    expected_space: str | None = None,
) -> DriveNodeModel | None:
    if node_id is None:
        return None

    node = await DriveNodes.get_node_by_id(node_id, db=db)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Drive item not found.')
    if expected_space and node.space != expected_space:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Drive space mismatch.')

    if node.space == DRIVE_SPACE_PERSONAL:
        if node.owner_id != user.id and user.role != 'admin':
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='No access to this personal item.')
    elif node.space == DRIVE_SPACE_SHARED:
        if write and user.role != 'admin':
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Shared space is read-only.')
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid drive space.')

    return node


async def _assert_parent_access(
    parent_id: str | None,
    user,
    db: AsyncSession,
    *,
    space: str,
    write: bool,
) -> DriveNodeModel | None:
    parent = await _assert_node_access(parent_id, user, db, write=write, expected_space=space)
    if parent and parent.node_type != DRIVE_NODE_FOLDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Parent must be a folder.')
    return parent


async def _ensure_unique_name(
    parent_id: str | None,
    space: str,
    owner_id: str | None,
    name: str,
    db: AsyncSession,
    ignore_node_id: str | None = None,
) -> str:
    existing_names = set()
    for child in await DriveNodes.get_children(parent_id=parent_id, space=space, owner_id=owner_id, db=db):
        if child.id != ignore_node_id:
            existing_names.add(child.name)
    if name not in existing_names:
        return name

    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 1
    while True:
        candidate = f'{stem} ({index}){suffix}'
        if candidate not in existing_names:
            return candidate
        index += 1


async def _get_or_create_folder(
    *,
    space: str,
    owner_id: str | None,
    parent_id: str | None,
    name: str,
    user_id: str,
    db: AsyncSession,
) -> DriveNodeModel:
    existing = await DriveNodes.get_child_by_name(parent_id, space, owner_id, name, db=db)
    if existing:
        if existing.node_type != DRIVE_NODE_FOLDER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Folder path conflicts with a file.')
        return existing

    return await DriveNodes.create_node(
        space=space,
        owner_id=owner_id,
        parent_id=parent_id,
        name=name,
        node_type=DRIVE_NODE_FOLDER,
        created_by=user_id,
        db=db,
    )


async def _is_descendant(node_id: str, possible_parent_id: str | None, db: AsyncSession) -> bool:
    current_id = possible_parent_id
    while current_id:
        if current_id == node_id:
            return True
        current = await DriveNodes.get_node_by_id(current_id, db=db)
        current_id = current.parent_id if current else None
    return False


async def _collect_tree(node_id: str, db: AsyncSession) -> list[DriveNodeModel]:
    root = await DriveNodes.get_node_by_id(node_id, db=db)
    if not root:
        return []
    nodes = [root]
    for child in await DriveNodes.get_children(node_id, db=db):
        nodes.extend(await _collect_tree(child.id, db=db))
    return nodes


async def _delete_node_tree(node_id: str, db: AsyncSession) -> None:
    nodes = await _collect_tree(node_id, db)
    for node in sorted(nodes, key=lambda item: item.node_type == DRIVE_NODE_FOLDER):
        if node.node_type == DRIVE_NODE_FILE and node.storage_path:
            path = (DRIVE_STORAGE_DIR / node.storage_path).resolve()
            try:
                path.relative_to(DRIVE_STORAGE_DIR.resolve())
            except ValueError:
                continue
            if path.exists():
                path.unlink()
    await db.execute(delete(DriveNode).where(DriveNode.id.in_([node.id for node in nodes])))


async def _copy_node_tree(
    source: DriveNodeModel,
    *,
    target_space: str,
    target_owner_id: str | None,
    target_parent_id: str | None,
    user_id: str,
    db: AsyncSession,
) -> DriveNodeModel:
    name = await _ensure_unique_name(target_parent_id, target_space, target_owner_id, source.name, db)

    if source.node_type == DRIVE_NODE_FOLDER:
        copied = await DriveNodes.create_node(
            space=target_space,
            owner_id=target_owner_id,
            parent_id=target_parent_id,
            name=name,
            node_type=DRIVE_NODE_FOLDER,
            source_node_id=source.id,
            created_by=user_id,
            db=db,
        )
        for child in await DriveNodes.get_children(source.id, db=db):
            await _copy_node_tree(
                child,
                target_space=target_space,
                target_owner_id=target_owner_id,
                target_parent_id=copied.id,
                user_id=user_id,
                db=db,
            )
        return copied

    source_path = _resolve_storage_path(source.storage_path)
    stored_name = f'{uuid.uuid4()}{Path(source.name).suffix}'
    target_path = DRIVE_STORAGE_DIR / stored_name
    shutil.copyfile(source_path, target_path)

    return await DriveNodes.create_node(
        space=target_space,
        owner_id=target_owner_id,
        parent_id=target_parent_id,
        name=name,
        node_type=DRIVE_NODE_FILE,
        mime_type=source.mime_type,
        size=source.size,
        storage_path=stored_name,
        source_node_id=source.id,
        created_by=user_id,
        db=db,
    )


async def _write_upload_to_storage(file: UploadFile) -> tuple[str, int]:
    suffix = Path(file.filename or '').suffix
    stored_name = f'{uuid.uuid4()}{suffix}'
    target = DRIVE_STORAGE_DIR / stored_name
    size = 0

    with target.open('wb') as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            buffer.write(chunk)

    return stored_name, size


async def _zip_folder(node: DriveNodeModel, db: AsyncSession) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix='drive-', suffix='.zip', dir=DRIVE_TMP_DIR)
    os.close(fd)
    tmp_path = Path(tmp_name)

    with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        async def add_children(parent: DriveNodeModel, prefix: str) -> None:
            children = await DriveNodes.get_children(parent.id, db=db)
            if not children:
                archive.writestr(f'{prefix}/', '')
            for child in children:
                child_path = f'{prefix}/{child.name}'
                if child.node_type == DRIVE_NODE_FOLDER:
                    await add_children(child, child_path)
                else:
                    archive.write(_resolve_storage_path(child.storage_path), child_path)

        await add_children(node, node.name)

    return tmp_path


@router.get('/list', response_model=DriveListResponse)
async def list_drive_nodes(
    space: str = DRIVE_SPACE_PERSONAL,
    parent_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    space = _normalize_space(space)
    parent = await _assert_parent_access(parent_id, user, db, space=space, write=False)
    owner_id = user.id if space == DRIVE_SPACE_PERSONAL else None
    if parent and space == DRIVE_SPACE_PERSONAL and parent.owner_id != user.id and user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='No access to this personal folder.')

    return DriveListResponse(
        parent=parent,
        items=await DriveNodes.get_children(parent_id, space=space, owner_id=owner_id, db=db),
    )


@router.post('/folders', response_model=DriveNodeModel)
async def create_drive_folder(
    form_data: DriveCreateFolderForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    space = _normalize_space(form_data.space)
    if space == DRIVE_SPACE_SHARED:
        _ensure_admin(user)
    parent = await _assert_parent_access(form_data.parent_id, user, db, space=space, write=True)
    owner_id = user.id if space == DRIVE_SPACE_PERSONAL else None
    if parent:
        owner_id = parent.owner_id

    name = await _ensure_unique_name(form_data.parent_id, space, owner_id, _clean_name(form_data.name), db)
    return await DriveNodes.create_node(
        space=space,
        owner_id=owner_id,
        parent_id=form_data.parent_id,
        name=name,
        node_type=DRIVE_NODE_FOLDER,
        created_by=user.id,
        db=db,
    )


@router.post('/upload', response_model=list[DriveNodeModel])
async def upload_drive_files(
    space: str = Form(DRIVE_SPACE_PERSONAL),
    parent_id: str | None = Form(None),
    relative_paths: str | None = Form(None),
    files: list[UploadFile] = File(...),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    space = _normalize_space(space)
    if space == DRIVE_SPACE_SHARED:
        _ensure_admin(user)
    parent = await _assert_parent_access(parent_id, user, db, space=space, write=True)
    owner_id = user.id if space == DRIVE_SPACE_PERSONAL else None
    if parent:
        owner_id = parent.owner_id

    paths: list[str] = []
    if relative_paths:
        try:
            parsed = json.loads(relative_paths)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid relative paths.')
        if not isinstance(parsed, list):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid relative paths.')
        paths = [str(path) for path in parsed]

    created: list[DriveNodeModel] = []
    for index, upload in enumerate(files):
        relative_path = paths[index] if index < len(paths) else upload.filename
        parts = _safe_relative_parts(relative_path)
        if not parts:
            parts = [_clean_name(upload.filename)]

        current_parent_id = parent_id
        for folder_name in parts[:-1]:
            folder = await _get_or_create_folder(
                space=space,
                owner_id=owner_id,
                parent_id=current_parent_id,
                name=folder_name,
                user_id=user.id,
                db=db,
            )
            current_parent_id = folder.id

        filename = await _ensure_unique_name(current_parent_id, space, owner_id, _clean_name(parts[-1]), db)
        storage_path, size = await _write_upload_to_storage(upload)
        mime_type = upload.content_type or mimetypes.guess_type(filename)[0]
        created.append(
            await DriveNodes.create_node(
                space=space,
                owner_id=owner_id,
                parent_id=current_parent_id,
                name=filename,
                node_type=DRIVE_NODE_FILE,
                mime_type=mime_type,
                size=size,
                storage_path=storage_path,
                created_by=user.id,
                db=db,
            )
        )

    return created


@router.post('/move', response_model=bool)
async def move_drive_nodes(
    form_data: DriveMoveForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not form_data.ids:
        return True

    first = await _assert_node_access(form_data.ids[0], user, db, write=True)
    if not first:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Drive item not found.')
    if first.space == DRIVE_SPACE_SHARED:
        _ensure_admin(user)
    target = await _assert_parent_access(form_data.target_parent_id, user, db, space=first.space, write=True)
    target_owner_id = target.owner_id if target else (first.owner_id if first.space == DRIVE_SPACE_PERSONAL else None)

    for node_id in form_data.ids:
        node = await _assert_node_access(node_id, user, db, write=True, expected_space=first.space)
        if not node:
            continue
        if node.space == DRIVE_SPACE_PERSONAL and node.owner_id != target_owner_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot move across personal spaces.')
        if await _is_descendant(node.id, form_data.target_parent_id, db):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot move a folder into itself.')
        new_name = await _ensure_unique_name(
            form_data.target_parent_id,
            node.space,
            node.owner_id,
            node.name,
            db,
            ignore_node_id=node.id,
        )
        await db.execute(
            update(DriveNode)
            .where(DriveNode.id == node.id)
            .values(parent_id=form_data.target_parent_id, name=new_name, updated_by=user.id, updated_at=int(time.time()))
        )

    await db.commit()
    return True


@router.post('/delete', response_model=bool)
async def delete_drive_nodes(
    form_data: DriveDeleteForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    for node_id in form_data.ids:
        node = await _assert_node_access(node_id, user, db, write=True)
        if node and node.space == DRIVE_SPACE_SHARED:
            _ensure_admin(user)
        if node:
            await _delete_node_tree(node.id, db)
    await db.commit()
    return True


@router.post('/share', response_model=list[DriveNodeModel])
async def share_to_shared_space(
    form_data: DriveShareForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    _ensure_admin(user)
    await _assert_parent_access(form_data.target_parent_id, user, db, space=DRIVE_SPACE_SHARED, write=True)

    copied: list[DriveNodeModel] = []
    for node_id in form_data.ids:
        source = await _assert_node_access(node_id, user, db, write=False)
        if not source or source.space != DRIVE_SPACE_PERSONAL:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Only personal items can be shared.')
        copied.append(
            await _copy_node_tree(
                source,
                target_space=DRIVE_SPACE_SHARED,
                target_owner_id=None,
                target_parent_id=form_data.target_parent_id,
                user_id=user.id,
                db=db,
            )
        )
    return copied


@router.post('/save-to-personal', response_model=list[DriveNodeModel])
async def save_shared_to_personal(
    form_data: DriveSaveToPersonalForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await _assert_parent_access(form_data.target_parent_id, user, db, space=DRIVE_SPACE_PERSONAL, write=True)

    copied: list[DriveNodeModel] = []
    for node_id in form_data.ids:
        source = await _assert_node_access(node_id, user, db, write=False, expected_space=DRIVE_SPACE_SHARED)
        if source:
            copied.append(
                await _copy_node_tree(
                    source,
                    target_space=DRIVE_SPACE_PERSONAL,
                    target_owner_id=user.id,
                    target_parent_id=form_data.target_parent_id,
                    user_id=user.id,
                    db=db,
                )
            )
    return copied


@router.get('/{node_id}/download')
async def download_drive_node(
    node_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    node = await _assert_node_access(node_id, user, db, write=False)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Drive item not found.')

    if node.node_type == DRIVE_NODE_FOLDER:
        zip_path = await _zip_folder(node, db)
        return FileResponse(
            zip_path,
            filename=f'{node.name}.zip',
            media_type='application/zip',
            background=BackgroundTask(lambda path: Path(path).unlink(missing_ok=True), zip_path),
            headers=_content_disposition(f'{node.name}.zip'),
        )

    return FileResponse(
        _resolve_storage_path(node.storage_path),
        filename=node.name,
        media_type=node.mime_type or 'application/octet-stream',
        headers=_content_disposition(node.name),
    )


@router.get('/{node_id}/preview')
async def preview_drive_node(
    node_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    node = await _assert_node_access(node_id, user, db, write=False)
    if not node or node.node_type != DRIVE_NODE_FILE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Preview file not found.')

    return FileResponse(
        _resolve_storage_path(node.storage_path),
        filename=node.name,
        media_type=node.mime_type or mimetypes.guess_type(node.name)[0] or 'application/octet-stream',
        headers=_content_disposition(node.name, inline=True),
    )
