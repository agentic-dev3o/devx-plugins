# Path Scoping Patterns

Rules in `.claude/rules/*.md` can include a `paths:` frontmatter to load only when matching files are read or edited.

## Contents

- Frontmatter Shape
- Common Patterns (frontend, backend, db, tests, security, infra, Python, Rust)
- One Domain Per File
- Verifying Scopes
- Symlinks for Cross-Project Standards
- Frontmatter Tips

## Frontmatter Shape

```yaml
---
paths:
  - <glob>
  - <glob>
---
```

Rules with `paths:` load on demand. Rules without `paths:` load at session start (treat them like CLAUDE.md — use sparingly).

## Common Patterns

### Frontend (web / mobile)

```yaml
paths:
  - apps/web/**
  - packages/ui/**
  - "**/*.tsx"
```

### Backend / API

```yaml
paths:
  - packages/backend/**
  - services/api/**
  - "**/*_api.ts"
```

### Database / migrations

```yaml
paths:
  - prisma/migrations/**
  - db/migrations/**
  - "**/*.sql"
  - convex.json
```

### Tests

```yaml
paths:
  - "**/*.test.ts"
  - "**/*.spec.ts"
  - tests/**
  - e2e/**
```

### Security-sensitive

```yaml
paths:
  - packages/backend/src/auth/**
  - apps/web/src/auth/**
  - "**/middleware/**"
  - "**/permissions/**"
```

### Infrastructure / CI

```yaml
paths:
  - .github/**
  - terraform/**
  - "**/Dockerfile"
  - "**/docker-compose*.yml"
```

### Python services

```yaml
paths:
  - services/*/src/**
  - "**/*.py"
  - pyproject.toml
```

### Rust crates

```yaml
paths:
  - crates/*/src/**
  - "**/Cargo.toml"
```

## One Domain Per File

Each rule file should answer one question: "What do I do when editing X?"

| Good split | Bad split |
|------------|-----------|
| `frontend.md`, `backend.md`, `security.md` | `conventions.md` covering everything |
| `convex.md` (scoped to Convex backend) | `db.md` covering Convex + Postgres + Redis |
| `auth.md` for both client and server auth flows | `auth-client.md` and `auth-server.md` for the same model |
| `migrations.md` for schema changes only | `data.md` mixing migrations + queries + caching |

## Verifying Scopes

After writing rules:

1. Open a file inside the intended scope and run `/memory` — confirm the rule loaded
2. Open a file *outside* the scope and confirm it did **not** load
3. If the rule loads everywhere, the path scope is too broad
4. If the rule never loads, the glob does not match real files

## Symlinks for Cross-Project Standards

Maintain shared rules centrally and symlink into each project:

```bash
ln -s ~/company-standards/security.md .claude/rules/security.md
```

The symlink loads like a normal rule file. Updates to the central file propagate to every project.

## Frontmatter Tips

- Use absolute-from-root globs (`apps/web/**`) — relative paths inside frontmatter are confusing
- Quote globs that start with `*` or contain special characters
- Keep the `paths:` list short — three to five globs is usually enough
- If you need more than five globs, the rule is probably trying to cover two domains
