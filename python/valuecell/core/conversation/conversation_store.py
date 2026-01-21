from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

from psycopg2.extras import RealDictCursor
from psycopg2 import pool

from .models import Conversation


class ConversationStore(ABC):
    """Conversation storage abstract base class - handles conversation metadata only.

    Implementations should provide async methods to save, load, delete and
    list conversation metadata. Conversation items themselves are managed
    separately by ItemStore implementations.
    """

    @abstractmethod
    def save_conversation(self, conversation: Conversation) -> None:
        """Save conversation"""

    @abstractmethod
    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Load conversation"""

    @abstractmethod
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete conversation"""

    @abstractmethod
    def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Conversation]:
        """List conversations. If user_id is None, return all conversations."""

    @abstractmethod
    def conversation_exists(self, conversation_id: str) -> bool:
        """Check if conversation exists"""


class InMemoryConversationStore(ConversationStore):
    """In-memory ConversationStore implementation used for testing and simple scenarios.

    Stores conversations in a dict keyed by conversation_id.
    """

    def __init__(self):
        self._conversations: Dict[str, Conversation] = {}

    def save_conversation(self, conversation: Conversation) -> None:
        """Save conversation to memory"""
        self._conversations[conversation.conversation_id] = conversation

    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Load conversation from memory"""
        return self._conversations.get(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete conversation from memory"""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Conversation]:
        """List conversations. If user_id is None, return all conversations."""
        if user_id is None:
            # Return all conversations
            conversations = list(self._conversations.values())
        else:
            # Filter by user_id
            conversations = [
                conversation
                for conversation in self._conversations.values()
                if conversation.user_id == user_id
            ]

        # Sort by creation time descending
        conversations.sort(key=lambda c: c.created_at, reverse=True)

        # Apply pagination
        start = offset
        end = offset + limit
        return conversations[start:end]

    def conversation_exists(self, conversation_id: str) -> bool:
        """Check if conversation exists"""
        return conversation_id in self._conversations

    def clear_all(self) -> None:
        """Clear all conversations (for testing)"""
        self._conversations.clear()

    def get_conversation_count(self) -> int:
        """Get total conversation count (for debugging)"""
        return len(self._conversations)


class PostgresConversationStore(ConversationStore):
    """PostgreSQL-backed conversation store using psycopg2.

    Uses psycopg2 with connection pooling for database operations.
    Table schema is created via init_db.py migration scripts.
    """

    def __init__(self, dsn: str):
        """Initialize PostgreSQL conversation store.

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
    def _row_to_conversation(row: dict) -> Conversation:
        """Convert database row to Conversation object."""
        return Conversation(
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            title=row["title"],
            agent_name=row["agent_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
        )

    def save_conversation(self, conversation: Conversation) -> None:
        """Save conversation to PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, user_id, title, agent_name, created_at, updated_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        title = EXCLUDED.title,
                        agent_name = EXCLUDED.agent_name,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        status = EXCLUDED.status
                    """,
                    (
                        conversation.conversation_id,
                        conversation.user_id,
                        conversation.title,
                        conversation.agent_name,
                        conversation.created_at,
                        conversation.updated_at,
                        conversation.status.value
                        if hasattr(conversation.status, "value")
                        else str(conversation.status),
                    ),
                )
                conn.commit()
        finally:
            pool.putconn(conn)

    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Load conversation from PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                row = cur.fetchone()
                return self._row_to_conversation(dict(row)) if row else None
        finally:
            pool.putconn(conn)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete conversation from PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            pool.putconn(conn)

    def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Conversation]:
        """List conversations from PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id is None:
                    # Return all conversations
                    cur.execute(
                        "SELECT * FROM conversations ORDER BY created_at DESC LIMIT %s OFFSET %s",
                        (limit, offset),
                    )
                else:
                    # Filter by user_id
                    cur.execute(
                        "SELECT * FROM conversations WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                        (user_id, limit, offset),
                    )

                rows = cur.fetchall()
                return [self._row_to_conversation(dict(row)) for row in rows]
        finally:
            pool.putconn(conn)

    def conversation_exists(self, conversation_id: str) -> bool:
        """Check if conversation exists in PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                row = cur.fetchone()
                return row is not None
        finally:
            pool.putconn(conn)

    def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
