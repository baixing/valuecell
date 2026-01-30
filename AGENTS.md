# Guidelines

## Project Structure

Monorepo with Python backend (`./python/`) and React/TypeScript frontend (`./frontend/`).

## Python Backend

### Environment & Commands

* Package manager: `uv`, Python >=3.12, virtual env at `./python/.venv`
* Commands (from root): `make format`, `make lint`, `make test`
* Run single test: `uv run pytest path/to/test.py::test_function` or `uv run pytest path/to/test.py::TestClassName::test_method`
* Run tests with keyword: `uv run pytest ./python -k "test_create_plan"`

### Code Style

* Linting/formatting: Use `ruff` (line length 88, target py312), `ruff format` + `isort`
* Imports: Avoid inline imports unless for circular deps. Import >3 names? Use qualified imports: `import pathlib; pathlib.Path`. Use `TYPE_CHECKING` for type hints.
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mypkg.schemas import AgentConfig
```
* Runtime checks: Avoid excessive `getattr`/`hasattr`. For pydantic `BaseModel`, prefer validated attributes/type annotations. Use Protocols/TypedDict for structural typing. Make runtime checks explicit, minimal, well-documented.
* Async-first: Prefer async APIs for I/O. Use `httpx` for HTTP, `asyncio`/`anyio` for async. Ensure clear async boundaries: public APIs and I/O paths should be async. Provide minimal sync adapters only when needed.
```python
import asyncio
import httpx
async def fetch_state(url: str, timeout_s: float) -> dict:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

def fetch_state_sync(url: str, timeout_s: float) -> dict:
    """Synchronous adapter. Prefer the async variant."""
    return asyncio.run(fetch_state(url, timeout_s))
```
* Logging: Use `loguru` with `{}` placeholders. Log key events at info. Avoid excessive logging. Do not log sensitive data. `logger.warning` for recoverable issues, `logger.exception` only for truly unexpected errors.
```python
from loguru import logger
logger.info("Processing {count} items", count=count)

# Recoverable error
async def send_notification(msg: str) -> None:
    try:
        await notify_service(msg)
    except NetworkError as exc:
        logger.warning("Notification failed, continuing: {err}", err=str(exc))

# Unexpected error
async def critical_operation() -> None:
    try:
        await process_critical_data()
    except Exception:
        logger.exception("Critical operation failed unexpectedly")
        raise
```
* Type hints: Add to public/internal APIs. Comments/docstrings in English explaining why, not what. Use Protocols, TypedDict, pydantic models; avoid excessive literal dict access.
* Error handling: Max 2 levels try-except. Catch specific exceptions. Prefer guard clauses over broad exception use.
```python
try:
    data = json.loads(raw)
except json.JSONDecodeError as exc:
    logger.info("Invalid JSON: {err}", err=str(exc))
    return {}
```
* Structure: Extract helpers at module level; avoid nested functions. Functions <200 lines. Max 10 parameters; prefer wrapping in struct/object. Separate concerns: I/O, parsing, business logic, orchestration.
* Strings/literals: Wrap lines <100 chars. Avoid long string literals. Centralize constants. Avoid magic numbers/strings.
```python
DEFAULT_TIMEOUT_S: float = 10.0
MAX_RETRIES: int = 3
```
* Boolean logic: Be careful with `or` where 0, empty, or False may be meaningful. Prefer explicit checks: `value if value is not None else default`.
* Module layout: Group agent core, adapters, utilities into separate modules. Keep public surface small. Delay re-exports in `__init__` until stable. For circular deps, extract to shared interfaces/contracts module.

## Frontend

### Environment & Commands

* Package manager: `bun`, Node >=22, React Router v7, TypeScript strict mode
* Commands: `bun run dev`, `bun run build`, `bun run typecheck`, `bun run lint`, `bun run check`
* Auto-fix: `bun run lint:fix`, `bun run format:fix`, `bun run check:fix`

### Code Style

* Linting/formatting: Use `biome` (configured in `biome.json`). Double quotes. 2-space indentation.
* Path aliases: `@/*` → `./src/*`, `@valuecell/*` → `./src/components/valuecell/*`
* Imports: Use `type` keyword for type-only imports. Biome auto-organizes imports.
```typescript
import type { AgentInfo } from "@/types/agent";
import { useQuery } from "@tanstack/react-query";
```
* Components: `.tsx` extension, PascalCase naming. Prefer named exports. Use `memo` when needed. Extract custom hooks to `src/hooks/`. Use `cn()` (clsx + tailwind-merge) for className composition.
```typescript
export const StreamingIndicator = memo(() => {
  return <div>...</div>;
});
```
* State management: React Query (`@tanstack/react-query`) for server state. Zustand for client state. `mutative` for immutable updates.
```typescript
const { data } = useQuery({
  queryKey: ["conversations"],
  queryFn: () => apiClient.get("/conversations/"),
});
```
* API & data: Zod for runtime validation. Types in `src/types/`. `@tanstack/react-form` for forms.
* Utilities: `.ts` extension, camelCase naming. Place in `src/lib/` or feature-specific directories.

## Testing

* Python: Use `pytest` with `pytest-asyncio` for async tests. 90% coverage threshold enforced by `diff-cover`.
* Frontend: No test framework configured yet. When adding tests, check `package.json` scripts and `biome.json` rules.

## Git Workflow

* On push to main/PRs, GitHub Actions run:
  * Python: ruff check, ruff format check, isort, pytest with coverage
  * Frontend: biome checks, typecheck, build verification
* Ensure all checks pass before merging.

## Common Patterns

* Avoid inline imports unless for circular dependencies
* Prefer explicit checks: `value if value is not None else default` over `value or default`
* Centralize constants, avoid magic numbers/strings
* Keep public API surfaces small, delay `__init__` re-exports
* If circular dependencies appear, extract to shared interfaces/contracts module
