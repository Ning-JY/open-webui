from __future__ import annotations

import time
import uuid

from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, ForeignKey, Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession


DRIVE_SPACE_PERSONAL = 'personal'
DRIVE_SPACE_SHARED = 'shared'
DRIVE_NODE_FOLDER = 'folder'
DRIVE_NODE_FILE = 'file'


class DriveNode(Base):
    __tablename__ = 'drive_node'

    id = Column(Text, unique=True, primary_key=True)
    space = Column(String(20), nullable=False)
    owner_id = Column(Text, nullable=True)
    parent_id = Column(Text, ForeignKey('drive_node.id', ondelete='CASCADE'), nullable=True)
    name = Column(Text, nullable=False)
    node_type = Column(String(20), nullable=False)
    mime_type = Column(Text, nullable=True)
    size = Column(BigInteger, default=0)
    storage_path = Column(Text, nullable=True)
    source_node_id = Column(Text, nullable=True)
    created_by = Column(Text, nullable=False)
    updated_by = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('idx_drive_node_space_owner_parent', 'space', 'owner_id', 'parent_id'),
        Index('idx_drive_node_parent_id', 'parent_id'),
        Index('idx_drive_node_source_node_id', 'source_node_id'),
    )


class DriveNodeModel(BaseModel):
    id: str
    space: str
    owner_id: str | None = None
    parent_id: str | None = None
    name: str
    node_type: str
    mime_type: str | None = None
    size: int | None = 0
    storage_path: str | None = None
    source_node_id: str | None = None
    created_by: str
    updated_by: str
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class DriveListResponse(BaseModel):
    items: list[DriveNodeModel]
    parent: DriveNodeModel | None = None


class DriveCreateFolderForm(BaseModel):
    space: str = DRIVE_SPACE_PERSONAL
    parent_id: str | None = None
    name: str


class DriveMoveForm(BaseModel):
    ids: list[str]
    target_parent_id: str | None = None


class DriveDeleteForm(BaseModel):
    ids: list[str]


class DriveShareForm(BaseModel):
    ids: list[str]
    target_parent_id: str | None = None


class DriveSaveToPersonalForm(BaseModel):
    ids: list[str]
    target_parent_id: str | None = None


class DriveNodesTable:
    async def get_node_by_id(
        self,
        node_id: str,
        db: AsyncSession | None = None,
    ) -> DriveNodeModel | None:
        async with get_async_db_context(db) as session:
            node = await session.get(DriveNode, node_id)
            return DriveNodeModel.model_validate(node) if node else None

    async def get_children(
        self,
        parent_id: str | None,
        space: str | None = None,
        owner_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[DriveNodeModel]:
        async with get_async_db_context(db) as session:
            stmt = select(DriveNode).where(DriveNode.parent_id == parent_id)
            if space:
                stmt = stmt.where(DriveNode.space == space)
            if owner_id is not None:
                stmt = stmt.where(DriveNode.owner_id == owner_id)
            stmt = stmt.order_by(DriveNode.node_type.asc(), DriveNode.name.asc())
            rows = (await session.execute(stmt)).scalars().all()
            return [DriveNodeModel.model_validate(row) for row in rows]

    async def get_child_by_name(
        self,
        parent_id: str | None,
        space: str,
        owner_id: str | None,
        name: str,
        db: AsyncSession | None = None,
    ) -> DriveNodeModel | None:
        async with get_async_db_context(db) as session:
            stmt = (
                select(DriveNode)
                .where(DriveNode.parent_id == parent_id)
                .where(DriveNode.space == space)
                .where(DriveNode.name == name)
            )
            if owner_id is None:
                stmt = stmt.where(DriveNode.owner_id.is_(None))
            else:
                stmt = stmt.where(DriveNode.owner_id == owner_id)
            node = (await session.execute(stmt)).scalars().first()
            return DriveNodeModel.model_validate(node) if node else None

    async def create_node(
        self,
        *,
        space: str,
        owner_id: str | None,
        parent_id: str | None,
        name: str,
        node_type: str,
        created_by: str,
        mime_type: str | None = None,
        size: int | None = 0,
        storage_path: str | None = None,
        source_node_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> DriveNodeModel:
        async with get_async_db_context(db) as session:
            now = int(time.time())
            node = DriveNode(
                id=str(uuid.uuid4()),
                space=space,
                owner_id=owner_id,
                parent_id=parent_id,
                name=name,
                node_type=node_type,
                mime_type=mime_type,
                size=size or 0,
                storage_path=storage_path,
                source_node_id=source_node_id,
                created_by=created_by,
                updated_by=created_by,
                created_at=now,
                updated_at=now,
            )
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return DriveNodeModel.model_validate(node)


DriveNodes = DriveNodesTable()
