---
allowed-tools: Bash, Read, Grep, Glob
description: Create a GitHub pull request using gh CLI. Use when user asks to open/create a PR or runs /pr.
argument-hint: [base-branch]
model: claude-haiku-4-5
---

# Create Pull Request

Base branch: "$ARGUMENTS" or default `main`

## Workflow

1. Verify clean working tree and get current branch (`git status`)
2. Analyze commits since base branch (`git log`, `git diff <base>...HEAD`)
3. Push branch if needed (`git push -u origin HEAD`)
4. Create PR with `gh pr create`:

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
- If working tree is dirty, stop and inform the user
