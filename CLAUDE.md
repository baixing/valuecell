# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ValueCell is a multi-agent platform for financial applications. It provides investment agents for stock research, trading strategies, and market analysis. The system stores sensitive data locally and supports multiple LLM providers and exchange integrations.

**Tech Stack:**
- **Backend**: Python 3.12+, FastAPI, Agno agents, A2A protocol
- **Frontend**: React 19, React Router 7, Bun, TypeScript, TailwindCSS
- **Desktop**: Tauri
- **Database**: SQLite (conversations), LanceDB (knowledge)

## Development Commands

### Full Application
```bash
./start.sh          # Start both frontend and backend (auto-installs deps)
./start.sh --no-frontend    # Backend only
./start.sh --no-backend     # Frontend only
```

### Backend (Python)
```bash
cd python

uv sync --group dev           # Install dependencies (run first)
uv run pytest                 # Run all tests
uv run pytest ./path/to/test.py  # Run specific test
python -m valuecell.server.main  # Run API server directly

# Format and lint
make format
make lint
```

### Frontend
```bash
cd frontend

bun install           # Install dependencies
bun run dev           # Start dev server
bun run build         # Production build
bun run typecheck     # Type check
bun run check:fix     # Auto-fix lint/format issues
bun run check         # Check lint/format without fixing
```

## Architecture

### Backend Structure (`python/valuecell/`)
```
valuecell/
├── core/           # Orchestration: super_agent, planner, task executor
├── agents/         # Agent implementations: research, strategy, news, grid
├── adapters/       # Exchange integrations (Binance, OKX, Hyperliquid)
├── server/         # FastAPI server, routers, database, services
└── utils/          # Shared utilities (model config, logging)
```

### Core Orchestration Flow
1. **SuperAgent** triages user input - either answers directly or enriches for planning
2. **Planner** creates execution plan (with HITL for clarifications)
3. **TaskExecutor** runs tasks via A2A protocol to remote agents
4. **ResponseBuffer** streams annotated responses to UI

Key modules:
- `core/coordinate/orchestrator.py` - Main orchestration entry point
- `core/super_agent/` - Initial query triage
- `core/plan/` - Intent-to-plan conversion
- `core/task/` - Task execution via A2A
- `core/event/` - Response routing and buffering

### Adding a New Agent

1. Create agent class extending `BaseAgent` with `stream()` method
2. Create agent card in `python/configs/agent_cards/`
3. Use `create_wrapped_agent()` decorator for A2A serving

Example:
```python
from valuecell.core.types import BaseAgent, StreamResponse
from valuecell.core.agent.responses import streaming

class MyAgent(BaseAgent):
    async def stream(self, query, conversation_id, task_id, dependencies=None):
        yield streaming.message_chunk("Thinking...")
        yield streaming.message_chunk(f"Result: {query}")
        yield streaming.done()
```

### Event System

Events defined in `core/types`:
- `MESSAGE_CHUNK`, `TOOL_CALL_STARTED`, `TOOL_CALL_COMPLETED` - streaming responses
- `TASK_STARTED`, `TASK_COMPLETED`, `TASK_FAILED` - task lifecycle
- `PLAN_REQUIRE_USER_INPUT` - HITL checkpoint

Emit via `streaming.*` helpers from `core.agent.responses`.

### Model Configuration

Models configured via `.env` and `python/configs/providers/`. Use `get_model("MODEL_ID")` where MODEL_IDs include:
- `RESEARCH_AGENT_MODEL_ID`
- `STRATEGY_AGENT_MODEL_ID`
- `EMBEDDING_MODEL_ID`

## Code Style

### Python
- **Linter**: Ruff (configured in `pyproject.toml`)
- **Import sorting**: isort
- **Async-first**: Use async/await for I/O, httpx for HTTP
- **Logging**: loguru with `{}` placeholders; avoid logging sensitive data
- **Models**: Pydantic `BaseModel` for contracts

### Frontend
- **Linter/Formatter**: Biome (`biome.json`)
- **Styling**: TailwindCSS with shadcn/ui components
- **State**: Zustand, TanStack Query
- **Forms**: TanStack Form, Zod validation

## Key Files

- `start.sh` - App launcher (installs deps, starts services)
- `python/pyproject.toml` - Python dependencies and lint config
- `frontend/package.json` - Frontend dependencies and scripts
- `docs/CORE_ARCHITECTURE.md` - Detailed architecture documentation
- `docs/CONTRIBUTING_AN_AGENT.md` - Agent development guide
- `AGENTS.md` - Development guidelines (imports, async, logging)

## Environment Variables

Configuration loaded from system app directory:
- macOS: `~/Library/Application Support/ValueCell/.env`
- Linux: `~/.config/valuecell/.env`
- Windows: `%APPDATA%\ValueCell\.env`

Run `./start.sh` to auto-generate from `.env.example`.

## Testing

- Python tests: `uv run pytest ./python`
- Frontend: No test framework configured yet
- Run `make test` from project root for Python tests
