# False-Positive Filter

## Contents

- Default posture
- Hard exclusions
- Precedents
- Validation questions
- Confidence rubric
- Severity guardrails
- Validator behavior
- Final keep or reject rule

## Default Posture

Assume the burden of proof is high. Keep only findings that are clearly exploitable, introduced by the reviewed change set, and meaningful for a security team to act on.

Prefer "no findings" over speculative noise.

## Hard Exclusions

Do not report findings that match these patterns unless there is a concrete, high-confidence exploit path that overrides the exclusion:

1. Denial-of-service, memory exhaustion, CPU exhaustion, or generic resource exhaustion.
2. Secrets or credentials stored on disk when the claim is only about their presence on disk.
3. Rate limiting concerns or service overload scenarios.
4. Non-security validation gaps on ordinary fields without a concrete security consequence.
5. GitHub Actions sanitization concerns unless untrusted input can clearly reach a dangerous sink.
6. General hardening gaps or "missing best practice" observations without an exploit path.
7. Theoretical race conditions or timing attacks without a concrete, practical abuse case.
8. Outdated third-party dependencies or package versions.
9. Memory-safety bugs in Rust or other memory-safe languages.
10. Files that are only tests or only used to run tests.
11. Log spoofing or log injection by itself.
12. SSRF claims where the attacker controls only the path and cannot control host or protocol.
13. Including user-controlled text in AI prompts.
14. Regex injection and regex DoS.
15. Documentation-only findings, including markdown files and insecure prose.
16. Lack of audit logs.

## Precedents

Apply these precedents consistently:

- Logging high-value secrets or PII in plaintext is a vulnerability.
- Logging non-PII data is not a vulnerability by itself.
- UUIDs can be treated as unguessable.
- Environment variables and CLI flags are trusted inputs in normal secure deployments.
- Resource leaks such as memory leaks or file descriptor leaks are not valid findings here.
- Subtle web issues such as tabnabbing, XS-Leaks, prototype pollution, and open redirects are usually too weak unless the exploit path is unusually concrete.
- React and Angular are generally XSS-safe unless the change uses explicitly unsafe rendering paths.
- Missing client-side permission checks are not a vulnerability unless the server now trusts that client decision.
- Notebook and shell-script findings need a very specific attacker-controlled path to be valid.
- MEDIUM findings must still be obvious, concrete, and actionable.

## Validation Questions

Reject a candidate unless each answer is strong:

1. What exact attacker-controlled input exists?
2. What sensitive sink, policy boundary, or privileged action does that input reach?
3. Is the vulnerable behavior server-side, security-relevant, and introduced by the reviewed diff?
4. Is the exploit scenario realistic without assuming control over environment variables, deployment settings, or privileged operators?
5. Does a framework, library, or nearby guard already neutralize the issue?
6. Is the finding outside docs-only or test-only code?

## Confidence Rubric

Use this scale:

- `1-3` - weak claim, likely noise
- `4-6` - suspicious but unproven
- `7` - plausible, still missing a key proof point
- `8-9` - strong evidence and a clear exploit path
- `10` - certain, direct, and difficult to dispute

Keep only findings with confidence `>= 8`.

## Severity Guardrails

- **HIGH** - Directly exploitable auth bypass, tenant escape, RCE, sensitive data exposure, signature bypass, or similar severe impact.
- **MEDIUM** - Significant security impact that needs some condition or chaining but is still concrete and obvious.
- **LOW** - Do not report. Treat as noise for this skill.

## Validator Behavior

When validating a candidate:

1. Try to disprove the finding first.
2. Read the surrounding code to confirm attacker control, sink reachability, and missing safeguards.
3. Look for framework protections, safe defaults, allowlists, policy layers, and escaping that break the exploit path.
4. Downgrade or reject the finding if the exploit path depends on unstated assumptions.
5. Keep the finding only if the remaining argument is concise, concrete, and actionable.

## Final Keep or Reject Rule

Keep a finding only when all of the following are true:

- The issue is in the reviewed change set.
- The exploit path is concrete.
- The impact is HIGH or MEDIUM.
- The confidence score is at least 8.

Otherwise reject it.
