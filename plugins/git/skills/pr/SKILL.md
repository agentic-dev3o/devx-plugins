---
name: pr
description: Creates a GitHub pull request using gh CLI. Triggered when the user asks to open, create, or submit a PR, or runs /pr.
---

# Create Pull Request

Accept an optional base branch argument (default: `main`).

## Workflow

1. Verify clean working tree and current branch via `git status`
   - If working tree is dirty, stop and inform the user
2. Analyze commits since base branch via `git log` and `git diff <base>...HEAD`
3. Push branch if needed: `git push -u origin HEAD`
4. Create PR:

```bash
gh pr create --title "<type>: <concise title>" --body "$(cat <<'EOF'
## Summary
- <1-3 bullets focusing on WHY, not what>

## Test plan
- [ ] <verification steps>
EOF
)"
```

5. Return the PR URL

## Rules

- Never use interactive flags (`-i`)
