from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from psycopg2.extras import RealDictCursor
from psycopg2 import pool

from valuecell.core.types import ConversationItem, ConversationItemEvent, Role


class ItemStore(ABC):
    """Abstract storage interface for conversation items.

    Implementations must provide async methods for saving and querying
    ConversationItem instances.
    """

    @abstractmethod
    def save_item(self, item: ConversationItem) -> None: ...

    @abstractmethod
    def get_items(
        self,
        conversation_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        role: Optional[Role] = None,
        **kwargs,
    ) -> List[ConversationItem]: ...

    @abstractmethod
    def get_latest_item(
        self, conversation_id: str
    ) -> Optional[ConversationItem]: ...

    @abstractmethod
    def get_item(self, item_id: str) -> Optional[ConversationItem]: ...

    @abstractmethod
    def get_item_count(self, conversation_id: str) -> int: ...

    @abstractmethod
    def delete_conversation_items(self, conversation_id: str) -> None: ...


class InMemoryItemStore(ItemStore):
    """In-memory store for conversation items.

    Useful for tests and lightweight usage where persistence is not required.
    """

    def __init__(self):
        # conversation_id -> list[ConversationItem]
        self._items: Dict[str, List[ConversationItem]] = {}

    def save_item(self, item: ConversationItem) -> None:
        arr = self._items.setdefault(item.conversation_id, [])
        arr.append(item)

    def get_items(
        self,
        conversation_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        role: Optional[Role] = None,
        **kwargs,
    ) -> List[ConversationItem]:
        if conversation_id is not None:
            items = list(self._items.get(conversation_id, []))
        else:
            # Collect all items from all conversations
            items = []
            for conv_items in self._items.values():
                items.extend(conv_items)
        if role is not None:
            items = [m for m in items if m.role == role]
        if offset:
            items = items[offset:]
        if limit is not None:
            items = items[:limit]
        return items

    def get_latest_item(self, conversation_id: str) -> Optional[ConversationItem]:
        items = self._items.get(conversation_id, [])
        return items[-1] if items else None

    def get_item(self, item_id: str) -> Optional[ConversationItem]:
        for arr in self._items.values():
            for m in arr:
                if m.item_id == item_id:
                    return m
        return None

    def get_item_count(self, conversation_id: str) -> int:
        return len(self._items.get(conversation_id, []))

    def delete_conversation_items(self, conversation_id: str) -> None:
        self._items.pop(conversation_id, None)


class PostgresItemStore(ItemStore):
    """PostgreSQL-backed item store using psycopg2.

    Uses psycopg2 with connection pooling for database operations.
    Table schema is created via init_db.py migration scripts.
    """

    def __init__(self, dsn: str):
        """Initialize PostgreSQL item store.

        Args:
            dsn: PostgreSQL connection string (e.g., postgresql://user:pass@host:5432/dbname)
        """
        self.dsn = dsn
        self._pool = None

    def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=self.dsn
            )
        return self._pool

    @staticmethod
    def _row_to_item(row: dict) -> ConversationItem:
        return ConversationItem(
            item_id=row["item_id"],
            role=row["role"],
            event=row["event"],
            conversation_id=row["conversation_id"],
            thread_id=row["thread_id"],
            task_id=row["task_id"],
            payload=row["payload"],
            agent_name=row["agent_name"],
            metadata=row["metadata"],
        )

    def save_item(self, item: ConversationItem) -> None:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            role_val = getattr(item.role, "value", str(item.role))
            event_val = getattr(item.event, "value", str(item.event))
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_items (
                        item_id, role, event, conversation_id, thread_id, task_id, payload, agent_name, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (item_id) DO UPDATE SET
                        role = EXCLUDED.role,
                        event = EXCLUDED.event,
                        conversation_id = EXCLUDED.conversation_id,
                        thread_id = EXCLUDED.thread_id,
                        task_id = EXCLUDED.task_id,
                        payload = EXCLUDED.payload,
                        agent_name = EXCLUDED.agent_name,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        item.item_id,
                        role_val,
                        event_val,
                        item.conversation_id,
                        item.thread_id,
                        item.task_id,
                        item.payload,
                        item.agent_name,
                        item.metadata,
                    ),
                )
                conn.commit()
        finally:
            pool.putconn(conn)

    def get_items(
        self,
        conversation_id: Optional[str] = None,
        role: Optional[Role] = None,
        event: Optional[ConversationItemEvent] = None,
        component_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        **kwargs,
    ) -> List[ConversationItem]:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            params = []
            where_clauses = []
            if conversation_id is not None:
                where_clauses.append("conversation_id = %s")
                params.append(conversation_id)
            if role is not None:
                where_clauses.append("role = %s")
                params.append(getattr(role, "value", str(role)))
            if event is not None:
                where_clauses.append("event = %s")
                params.append(getattr(event, "value", str(event)))
            if component_type is not None:
                where_clauses.append("payload::jsonb->>'component_type' = %s")
                params.append(component_type)

            where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            sql = f"SELECT * FROM conversation_items {where} ORDER BY created_at ASC"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(int(limit))
            if offset:
                if limit is None:
                    sql += " LIMIT ALL"
                sql += " OFFSET %s"
                params.append(int(offset))

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [self._row_to_item(dict(r)) for r in rows]
        finally:
            pool.putconn(conn)

    def get_latest_item(self, conversation_id: str) -> Optional[ConversationItem]:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM conversation_items WHERE conversation_id = %s ORDER BY created_at DESC LIMIT 1",
                    (conversation_id,),
                )
                row = cur.fetchone()
                return self._row_to_item(dict(row)) if row else None
        finally:
            pool.putconn(conn)

    def get_item(self, item_id: str) -> Optional[ConversationItem]:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM conversation_items WHERE item_id = %s",
                    (item_id,),
                )
                row = cur.fetchone()
                return self._row_to_item(dict(row)) if row else None
        finally:
            pool.putconn(conn)

    def get_item_count(self, conversation_id: str) -> int:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(1) FROM conversation_items WHERE conversation_id = %s",
                    (conversation_id,),
                )
                row = cur.fetchone()
                return int(row[0] if row else 0)
        finally:
            pool.putconn(conn)

    def delete_conversation_items(self, conversation_id: str) -> None:
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM conversation_items WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conn.commit()
        finally:
            pool.putconn(conn)

    def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
