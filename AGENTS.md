# Agent Notes

## Environment and packaging

- Use `uv` for environment and dependency management.
- Install project and dev dependencies with `uv sync --dev`.
- Run commands with `uv run ...` (for example `uv run pytest`).
- Treat `pyproject.toml` as the dependency source of truth.
- Do not add or update runtime dependencies directly in `requirements.txt`.
- Keep `requirements.txt` as a compatibility note/export pointer only.
