# Sub-Task Templates

## Contents

- Investigator prompt
- Validator prompt
- Final report template

## Investigator Prompt

Use this prompt for the first readonly sub-task after collecting the branch or PR context:

```text
You are a senior application security engineer performing a focused review of the pending changes in this branch.

Review target:
<target>

Git status:
<git status output>

Files modified:
<git diff --name-only output>

Commits:
<git log --no-decorate output>

Diff content:
<git diff output>

Task:
Review the complete change set above. Identify only newly introduced application-layer vulnerabilities with real exploitation potential. This is not a general code review. Ignore pre-existing issues outside the reviewed diff.

Repository context work:
- Read nearby code for the changed files.
- Identify existing auth, tenant, validation, sanitization, serialization, templating, and secret-handling patterns.
- Compare the new code to nearby secure conventions.

Focus areas:
- auth bypass and privilege escalation
- broken object- or tenant-level authorization
- SQL, NoSQL, command, template, and path injection
- unsafe deserialization and code execution
- JWT, session, signature, and token validation flaws
- SSRF when host or protocol control exists
- CSRF and CORS only when the changed browser-facing behavior creates a concrete exploit path
- sensitive data exposure in logs, responses, or rendered payloads
- XSS only when unsafe rendering paths exist
- security-by-design regressions such as weaker policy gates, unsafe trust in internal headers, weaker tenancy, or webhook verification removal

Out of scope:
- user-controlled content in AI prompts by itself

Return candidate findings only when there is a concrete exploit path, meaningful impact, and preliminary confidence of at least 7.

Return markdown using this shape:

- `path/to/file:line`
  - severity: HIGH|MEDIUM
  - category: <short_category>
  - confidence: <7-10>
  - why_exploitable: <one short paragraph>
  - exploit_scenario: <one short paragraph>
  - recommendation: <one short paragraph>

Return `No candidate vulnerabilities.` if none.
```

## Validator Prompt

Use one readonly validator sub-task per candidate. Launch validators in parallel.

```text
You are validating one candidate vulnerability from an earlier application security review.

Candidate finding:
<paste one candidate finding here>

Task:
Challenge this candidate aggressively. Try to disprove it using surrounding code, framework behavior, trust-boundary analysis, validation logic, policy checks, escaping, or other protections. Confirm it only if the exploit path remains concrete after that challenge.

Validation rules:
- Apply `references/false-positive-filter.md` while validating this candidate.
- Review only the changed code path and the nearby context needed to understand it.
- Reject the finding if it depends on speculative attacker control or general best-practice gaps.
- Reject the finding if the issue is only in docs, tests, client-side trust assumptions, or excluded categories.
- Keep the finding only if it is introduced by the reviewed diff, still exploitable, and confidence is at least 8.
- Do not write files or attempt reproduction.

Return markdown using this shape:

- verdict: KEEP|REJECT
- confidence: <1-10>
- severity: HIGH|MEDIUM
- category: <short_category>
- rationale: <one short paragraph>
- checked_context: <files or symbols reviewed>
- recommendation: <one short paragraph if KEEP, otherwise "n/a">
```

## Final Report Template

Use this final markdown report shape after filtering:

```markdown
# Vuln 1: <Category>: `path/to/file:line`

* Severity: HIGH
* Confidence: 9/10
* Description: <what changed and why it is vulnerable>
* Exploit Scenario: <how an attacker can abuse it>
* Recommendation: <specific fix or safer pattern>
```

If no finding survives, return:

```markdown
No high-confidence application security findings in the reviewed changes.
```

Return the markdown report only.
