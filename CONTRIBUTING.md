# Contributing

## Commit messages

Every commit subject uses the Conventional Commits form:

```
<type>(<scope>): <imperative summary, lowercase, no full stop>
```

- **type**: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
- **scope** (optional): the area changed, for example `servicing`, `ledger`, `payments`, `auth`, `deploy`, `ci`.
- **subject**: at most 72 characters, written as a command ("add", "fix", "pin"), not as a status.
- **body** (optional): wrap at 72 characters. Explain *why* when the reason is not obvious from the diff.

Examples:

```
feat(payments): add overpayment credit and full integrity checks
fix(ci): pin Pillow 13 to clear the dependency audit
docs: add contributing guide
```

Do not use day labels, progress words or status claims in subjects
(for example `Day 3 complete`, `WIP`, `done`, `fixed stuff`). Put verification
results in the body or the pull request, not in the subject.

## Before you push

- Run the backend tests: `cd backend && pytest app/tests/`.
- Run the same tests against PostgreSQL when you touch the ledger or migrations:
  `TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db pytest app/tests/`.
- Lint with `ruff check app` (the CI configuration).
- Keep commits focused: one logical change per commit.

## Pull requests

- Describe what changed and how it was verified.
- Schema changes need an Alembic migration and a test that runs it.
- Do not commit secrets. Keep tokens and API keys in environment variables.
