# Application Security Review Playbook

## Contents

- Review intent
- Repository context research
- High-value attack surfaces
- Stack-specific heuristics
- Comparative analysis questions
- Reporting standard

## Review Intent

Identify newly introduced application-layer vulnerabilities with real exploitation potential. Review only the requested change set and the surrounding code needed to understand it.

Think beyond checklist scanning. Model how an attacker would cross trust boundaries, gain unintended capability, access another tenant's data, or move untrusted input into a sensitive sink.

## Repository Context Research

Start every review by answering these questions:

1. What code paths became reachable or changed privilege?
2. What inputs are attacker-controlled, partially trusted, or internally trusted?
3. What guards already exist nearby for auth, tenant scoping, validation, encoding, or safe execution?
4. Which changed files sit on a trust boundary: controller, API route, webhook, queue consumer, worker, serializer, template, policy layer, data access layer, or client render surface?
5. What conventions does the repository already use to stay safe, and did the diff bypass them?

Prefer comparative analysis over abstract advice. A new pattern is suspicious when nearby code already uses stricter validation, central auth middleware, a safer serializer, or a safer rendering path.

## High-Value Attack Surfaces

### Input Handling and Injection

Trace user-controlled values into:

- raw SQL, query builders, Mongo selectors, search DSLs
- shell commands, task runners, OS APIs, template engines
- filesystem paths, archive extraction paths, storage keys
- XML parsers, YAML loaders, pickle or similar deserializers
- code-evaluation surfaces such as `eval`, `exec`, `vm`, dynamic imports, or unsafe template compilation

Ask:

- Can the attacker control structure or only data?
- Does the framework already parameterize or escape this sink?
- Did the diff remove validation, canonicalization, or allowlisting?

### Authentication, Authorization, and Multi-Tenancy

Inspect changes for:

- missing ownership checks
- broader role checks replacing narrower policy checks
- server-side decisions moved into client code
- tenant filters removed from queries or caches
- security middleware bypassed for convenience
- internal headers, cookies, or route params trusted without verification
- session or token issuance with weaker claims, scopes, or expiry

Ask:

- Can one authenticated user act on another user's resource?
- Can a lower-privilege actor trigger an admin-only path?
- Can cached data or background jobs leak across users or tenants?

### Outbound Requests and Integrations

Inspect:

- webhook signature verification
- callback URL handling
- server-to-server requests built from request parameters
- OAuth or SSO callback validation
- file fetchers, URL previewers, importers, and image proxies

Ask:

- Can the attacker control the host or protocol, not just the path?
- Can secrets, tokens, or metadata be sent to an attacker-controlled destination?
- Did the diff weaken origin, issuer, audience, or signature checks?

### Data Exposure and Sensitive Flows

Inspect:

- logs, analytics, tracing, and telemetry
- error responses, debug output, stack traces, and verbose exceptions
- serialization layers, DTOs, GraphQL resolvers, and response mappers
- client hydration payloads, embedded config, and server-to-client props

Ask:

- Does the change expose secrets, tokens, passwords, PII, or tenant-internal data?
- Did the diff widen what an endpoint or resolver returns?
- Does a UI-only change accidentally expose sensitive state in the rendered payload?

### Client Rendering and Design Systems

Treat client code as a security issue only when the change creates a real exploit path. Focus on:

- `dangerouslySetInnerHTML`
- Angular bypass APIs such as `bypassSecurityTrustHtml`
- markdown or MDX rendering that allows raw HTML or unsafe link schemes
- `srcdoc`, sandbox changes, or iframe embedding
- custom link or rich-text components that stop sanitizing `href`, `src`, or HTML content

Do not report missing client-side permission checks by themselves. Confirm a server-side trust failure or an actual unsafe rendering path first.

## Stack-Specific Heuristics

### TypeScript and Node.js

Look for:

- `child_process`, `exec`, `spawn`, shell interpolation, or wrapper utilities
- `path.join` or `resolve` on untrusted segments without post-normalization checks
- raw SQL strings in Prisma, Knex, Sequelize, Drizzle, or direct drivers
- JWT verification with weak algorithm selection, missing issuer or audience checks, or decode-without-verify flows
- SSR or API routes passing untrusted URLs into fetchers or proxies
- unsafe HTML sinks in Next.js, React, Express templating, or markdown renderers

### Python

Look for:

- `subprocess` with shell interpolation
- `yaml.load`, pickle usage, `eval`, `exec`, or dynamic imports on untrusted data
- ORM escapes bypassed by raw SQL fragments
- unsafe Jinja handling, `Markup`, or disabled autoescaping
- FastAPI, Flask, or Django routes that trust headers, cookies, or ownership claims without verification

### Rust

Do not spend time on impossible memory-safety findings in safe Rust. Focus on:

- authz and tenant-scope regressions
- raw SQL or string-built queries
- path traversal and archive extraction paths
- command execution
- deserialization and parser trust assumptions
- crypto misuse, token validation, and signature checks
- async workflow bugs that expose or mix up another actor's data

### Web and API Design

Check for security-by-design regressions:

- endpoints becoming public when they were previously protected
- write paths added without ownership or role checks
- privileged defaults becoming opt-out instead of opt-in
- admin and user traffic sharing the same identifiers without policy gates
- cache keys or storage namespaces dropping tenant or user scope
- internal-only helpers becoming externally reachable through a new route or worker

Also check web-specific controls when the diff changes browser-facing behavior:

- CSRF on state-changing endpoints that rely on cookies, origin checks, or anti-CSRF tokens
- CORS when credentialed cross-origin access, allowed origins, or exposed headers become broader

## Comparative Analysis Questions

For each changed file, ask:

1. What is the nearest existing secure pattern for the same task?
2. What validation or authorization step exists elsewhere but not here?
3. What sensitive sink did the diff move closer to attacker input?
4. What invariant used to hold that no longer clearly holds?

## Reporting Standard

Raise a finding only when all of the following are true:

- The issue is introduced or exposed by the reviewed change set.
- The exploit path is specific and plausible.
- The impact is meaningful enough for a security engineer to raise in PR review.
- The behavior is not already neutralized by the framework or nearby code.

When uncertain, gather more surrounding code or downgrade to "no finding" instead of stretching the claim.
