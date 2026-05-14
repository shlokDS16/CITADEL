# Rule: Code Style

> Lints + manual conventions. Both backend (Python) and frontend (JavaScript/JSX).

## Python (backend)
- **Formatter**: `ruff format` (replaces `black`). 100 char line width.
- **Linter**: `ruff check` with rules: `E,F,I,B,UP,N,SIM,RUF,ASYNC,S,A,COM`. Errors fail CI.
- **Types**: `mypy --strict` on `app/`. Library `Any` is allowed only at boundaries (third-party SDK calls).
- **Imports**: stdlib → third-party → first-party. `ruff` enforces grouping.
- **Naming**: `snake_case` for functions/vars, `PascalCase` for classes, `SCREAMING_SNAKE` for module-level constants.
- **Docstrings**: Google style. Required on public service methods. Optional on routers (the OpenAPI summary covers it).
- **Type hints**: required on every function signature. Return type explicit, even when `None`.
- **Exceptions**: raise typed `app.core.errors.*`. Never `raise Exception(...)`.

### Async discipline
- `async def` for any function that awaits something. Use `def` for pure CPU code.
- Use `asyncio.to_thread(fn, ...)` for blocking CPU calls (model inference) inside async handlers.
- `async with` for sessions, files, HTTP clients. Never leak.

### Pydantic
- Models inherit from `BaseModel` (or `BaseSchema` if we add a project base).
- Use `model_config = ConfigDict(from_attributes=True)` on `Out` schemas reading from ORM models.
- `Field(..., description="...", examples=["..."])` for any field exposed in OpenAPI.

### SQLAlchemy
- Declarative `Mapped[...]` style (SQLAlchemy 2.0).
- `__tablename__ = "snake_case_plural"` (e.g. `documents`, `traffic_incidents`).
- All FKs declared `ondelete="CASCADE"` or `"SET NULL"` explicitly — never default.
- Indexes named: `ix_<table>_<col>` (single), `ix_<table>_<col1>_<col2>` (composite).

## JavaScript / JSX (frontend)
- **Formatter**: project uses no auto-formatter — match existing 2-space indent, single quotes, no semicolons-at-end-only when needed.
- **Naming**: `camelCase` for variables/functions, `PascalCase` for components, `SCREAMING_SNAKE` for constants.
- **Components**: function components only. Hooks with `use*` prefix.
- **State**: `React.useState` / `React.useReducer` for local. **No** Redux / Zustand / Context for global state.
- **Comments**: only when intent isn't obvious from code. Avoid restating what the code does.
- **No unused imports** (we don't have a linter here, but eyeballing matters).

### Component structure
```jsx
const MyComponent = ({ propA, propB, onAction }) => {
  const [state, setState] = React.useState(...);
  const derived = React.useMemo(() => ..., [state]);

  React.useEffect(() => { ... }, [propA]);

  const handleClick = () => { ... };

  return (
    <div className="my-component">
      ...
    </div>
  );
};
```

### CSS class naming
- `kebab-case`, prefixed by component / module: `kpi-card`, `kpi-card-header`, `kpi-card-body`.
- Modifier suffix with `--` only when it improves clarity; otherwise compose with state words: `kpi-card.active`, `kpi-card.over`.
- No `!important` unless overriding a third-party style.

## Git
- Commit messages: imperative mood, ≤ 72 char subject, optional body wrapped at 100.
- Subject format: `<area>: <change>` — e.g. `doc-intel: extract OCR pipeline into service layer`.
- One logical change per commit. PRs can be multi-commit but each commit must build green.
- Branch names: `<type>/<short-slug>` — e.g. `feat/doc-intel-pipeline`, `fix/resume-bias-panel-overflow`.

## Anti-patterns (general)
- ❌ Files > 500 lines (refactor into multiple files instead).
- ❌ Functions > 50 lines (extract helpers).
- ❌ Nested ternaries that span multiple lines.
- ❌ Magic numbers (extract to named constants).
- ❌ TODO comments without an owner / issue link.
