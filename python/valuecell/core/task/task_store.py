import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

from psycopg2.extras import RealDictCursor
from psycopg2 import pool

from .models import Task, TaskStatus


class TaskStore(ABC):
    """Task storage abstract base class.

    Implementations should provide async methods to save, load, delete and
    list tasks.
    """

    @abstractmethod
    def save_task(self, task: Task) -> None:
        """Save task"""

    @abstractmethod
    def load_task(self, task_id: str) -> Optional[Task]:
        """Load task"""

    @abstractmethod
    def delete_task(self, task_id: str) -> bool:
        """Delete task"""

    @abstractmethod
    def list_tasks(
        self,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """List tasks with optional filters."""

    @abstractmethod
    def task_exists(self, task_id: str) -> bool:
        """Check if task exists"""


class InMemoryTaskStore(TaskStore):
    """In-memory TaskStore implementation used for testing and simple scenarios.

    Stores tasks in a dict keyed by task_id.
    """

    def __init__(self):
        self._tasks: Dict[str, Task] = {}

    def save_task(self, task: Task) -> None:
        """Save task to memory"""
        self._tasks[task.task_id] = task

    def load_task(self, task_id: str) -> Optional[Task]:
        """Load task from memory"""
        return self._tasks.get(task_id)

    def delete_task(self, task_id: str) -> bool:
        """Delete task from memory"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def list_tasks(
        self,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """List tasks with optional filters."""
        tasks = list(self._tasks.values())

        # Apply filters
        if conversation_id is not None:
            tasks = [t for t in tasks if t.conversation_id == conversation_id]
        if user_id is not None:
            tasks = [t for t in tasks if t.user_id == user_id]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        # Sort by creation time descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)

        # Apply pagination
        start = offset
        end = offset + limit
        return tasks[start:end]

    def task_exists(self, task_id: str) -> bool:
        """Check if task exists"""
        return task_id in self._tasks

    def clear_all(self) -> None:
        """Clear all tasks (for testing)"""
        self._tasks.clear()

    def get_task_count(self) -> int:
        """Get total task count (for debugging)"""
        return len(self._tasks)


class PostgresTaskStore(TaskStore):
    """PostgreSQL-backed task store using psycopg2.

    Uses psycopg2 with connection pooling for database operations.
    Table schema is created via init_db.py migration scripts.
    """

    def __init__(self, dsn: str):
        """Initialize PostgreSQL task store.

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
    def _row_to_task(row: dict) -> Task:
        """Convert database row to Task object."""
        # Parse JSON fields
        schedule_config = None
        if row["schedule_config"]:
            try:
                schedule_config = json.loads(row["schedule_config"])
            except Exception:
                pass

        return Task(
            task_id=row["task_id"],
            title=row["title"] or "",
            query=row["query"],
            conversation_id=row["conversation_id"],
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            agent_name=row["agent_name"],
            status=row["status"],
            pattern=row["pattern"],
            schedule_config=schedule_config,
            handoff_from_super_agent=bool(row["handoff_from_super_agent"]),
            created_at=row["created_at"],
            started_at=row["started_at"] if row["started_at"] else None,
            completed_at=row["completed_at"] if row["completed_at"] else None,
            updated_at=row["updated_at"],
            error_message=row["error_message"],
        )

    def save_task(self, task: Task) -> None:
        """Save task to PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            # Serialize complex fields
            schedule_config_json = None
            if task.schedule_config:
                schedule_config_json = json.dumps(task.schedule_config.model_dump())

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (
                        task_id, title, query, conversation_id, thread_id, user_id, agent_name,
                        status, pattern, schedule_config, handoff_from_super_agent,
                        created_at, started_at, completed_at, updated_at, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        query = EXCLUDED.query,
                        conversation_id = EXCLUDED.conversation_id,
                        thread_id = EXCLUDED.thread_id,
                        user_id = EXCLUDED.user_id,
                        agent_name = EXCLUDED.agent_name,
                        status = EXCLUDED.status,
                        pattern = EXCLUDED.pattern,
                        schedule_config = EXCLUDED.schedule_config,
                        handoff_from_super_agent = EXCLUDED.handoff_from_super_agent,
                        created_at = EXCLUDED.created_at,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        updated_at = EXCLUDED.updated_at,
                        error_message = EXCLUDED.error_message
                    """,
                    (
                        task.task_id,
                        task.title,
                        task.query,
                        task.conversation_id,
                        task.thread_id,
                        task.user_id,
                        task.agent_name,
                        task.status.value
                        if hasattr(task.status, "value")
                        else str(task.status),
                        task.pattern.value
                        if hasattr(task.pattern, "value")
                        else str(task.pattern),
                        schedule_config_json,
                        int(task.handoff_from_super_agent),
                        task.created_at,
                        task.started_at if task.started_at else None,
                        task.completed_at if task.completed_at else None,
                        task.updated_at,
                        task.error_message,
                    ),
                )
                conn.commit()
        finally:
            pool.putconn(conn)

    def load_task(self, task_id: str) -> Optional[Task]:
        """Load task from PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM tasks WHERE task_id = %s",
                    (task_id,),
                )
                row = cur.fetchone()
                return self._row_to_task(dict(row)) if row else None
        finally:
            pool.putconn(conn)

    def delete_task(self, task_id: str) -> bool:
        """Delete task from PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tasks WHERE task_id = %s",
                    (task_id,),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            pool.putconn(conn)

    def list_tasks(
        self,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """List tasks from PostgreSQL database with optional filters."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            # Build query with filters
            query = "SELECT * FROM tasks WHERE 1=1"
            params = []

            if conversation_id is not None:
                query += " AND conversation_id = %s"
                params.append(conversation_id)

            if user_id is not None:
                query += " AND user_id = %s"
                params.append(user_id)

            if status is not None:
                query += " AND status = %s"
                params.append(status.value if hasattr(status, "value") else str(status))

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return [self._row_to_task(dict(r)) for r in rows]
        finally:
            pool.putconn(conn)

    def task_exists(self, task_id: str) -> bool:
        """Check if task exists in PostgreSQL database."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM tasks WHERE task_id = %s",
                    (task_id,),
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
