# Repository Guidelines

This document describes how to work on the LLM Council repo as a contributor or agent.

## Repository Purpose & Core Concepts

LLM Council is a local web app that lets users query a group of language models (the “council”) instead of a single model. For each user message, the system collects independent model answers, has models review and rank each other’s outputs, and then synthesizes a final “chairman” answer. The flow is implemented across three stages in `backend.council` and surfaced as Stage 1/2/3 tabs in the frontend.

The backend operates primarily on conversations and context items. Conversations are JSON records in `data/conversations/` containing an `id`, `created_at`, `title`, and ordered `messages` with per-turn metadata (stage results, rankings, and model mappings). Context items come from retrieval helpers in `backend.retrieval` and generally include fields like `provider`, `source`, `title`, `summary`, `url`, `published_at`, `content`, and a `metadata` dict; they enrich prompts with news, papers, releases, and RSS content.

## Project Structure & Module Organization

- Backend: Python FastAPI app in `backend/` (`backend.main`, `backend.council`, `backend.retrieval`, `backend.storage`).
- Frontend: React + Vite app in `frontend/` (`frontend/src/components/*.jsx`, `App.jsx`).
- Data: JSON conversation logs in `data/conversations/` (treat as runtime data, not hand-edited).
- Tests: Python tests live in `tests/` (e.g., `tests/test_retrieval.py`).

## Build, Test, and Development Commands

- Install backend deps: `uv sync`
- Install frontend deps: `cd frontend && npm install`
- Run backend (dev): `uv run python -m backend.main`
- Run frontend (dev): `cd frontend && npm run dev`
- Run backend tests: `uv run python -m unittest tests.test_retrieval`
- Lint frontend: `cd frontend && npm run lint`

## Coding Style & Naming Conventions

- Python: 4-space indentation, type hints where practical, PEP 8-style naming (`snake_case` for functions/modules, `PascalCase` for classes).
- React/JS: Components in `PascalCase` (`ChatInterface.jsx`), hooks in `camelCase`. Prefer functional components with hooks.
- Keep files small and focused (e.g., new backend helpers in `backend/retrieval.py` or similar modules).

## Testing Guidelines

- Prefer unit tests in `tests/` mirroring backend modules (e.g., retrieval helpers in `test_retrieval.py`).
- Name tests descriptively and assert on concrete values, not just truthiness.
- Run `uv run python -m unittest` (or the specific test module) before opening a PR.

## Commit & Pull Request Guidelines

- Commits: Use short, imperative summaries (e.g., `add retrieval aggregation tests`, `refine council ranking metadata`).
- PRs: Include a clear description, screenshots or API examples for UX/API changes, and reference related issues when available.
- Keep changes scoped; prefer smaller PRs that touch a coherent part of the system (backend logic, frontend UI, or tests).

## Security & Configuration

- Do not commit secrets. Keep API keys in `.env` (e.g., `OPENROUTER_API_KEY`, optional `GITHUB_TOKEN`).
- Treat `backend/config.py` as code, not as a place to hard-code credentials. Use env vars for anything sensitive.
