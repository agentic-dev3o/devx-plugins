// Audits a lockfile at a git revision with the package manager's own audit, and reads advisories from GitHub.
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, posix } from 'node:path';
import { git, gitShow, sh } from './util.mjs';

// Ids from npm's audit report v2 and from the bulk-advisory shape `bun audit --json` prints.
export function auditIds(report) {
  const ids = new Map(); // id -> { pkg, severity, vector }
  const add = (pkg, a) => {
    const m = /GHSA-[\w-]+/.exec(a?.url ?? '');
    if (m) ids.set(m[0], { pkg, severity: a.severity, vector: a.cvss?.vectorString ?? null, range: a.vulnerable_versions ?? a.range });
  };
  if (report?.vulnerabilities) {
    for (const [pkg, v] of Object.entries(report.vulnerabilities))
      for (const via of v.via ?? []) if (typeof via === 'object') add(via.name ?? pkg, via);
  } else if (report && typeof report === 'object') {
    for (const [pkg, list] of Object.entries(report)) if (Array.isArray(list)) for (const a of list) add(pkg, a);
  }
  return ids;
}

// Writes the manifests and the lockfile of `rev` (only those of the lockfile's package) to a scratch dir and
// audits them there: no install, no scripts, nothing from the work tree.
export function auditAt(repo, rev, lockfile, { pm, env }) {
  const dir = mkdtempSync(join(tmpdir(), 'spt-audit-'));
  try {
    const root = posix.dirname(lockfile) === '.' ? '' : posix.dirname(lockfile) + '/';
    const files = git(repo, 'ls-tree', '-r', '--name-only', rev).split('\n')
      .filter(f => f.startsWith(root) && !f.includes('node_modules/')
        && (posix.basename(f) === 'package.json' || f === lockfile));
    for (const f of files) {
      const text = gitShow(repo, rev, f);
      if (text == null) continue;
      mkdirSync(dirname(join(dir, f)), { recursive: true });
      writeFileSync(join(dir, f), text);
    }
    const cwd = join(dir, root);
    const r = pm === 'bun'
      ? sh('bun', ['audit', '--json'], { cwd, env, check: false, timeoutMs: 300_000 })
      : sh('npm', ['audit', '--json', '--package-lock-only'], { cwd, env, check: false, timeoutMs: 300_000 });
    const start = r.stdout.indexOf('{');
    if (start < 0) throw new Error(`${pm} audit printed no JSON for ${lockfile}@${rev}: ${r.stderr.slice(0, 500)}`);
    return auditIds(JSON.parse(r.stdout.slice(start)));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// The fields the grader compares risk lines against, from the GitHub Advisory Database.
export function fetchAdvisory(ghsa) {
  const r = sh('gh', ['api', '-X', 'GET', `/advisories/${ghsa}`], { check: false, timeoutMs: 60_000 });
  if (r.status !== 0) return { ghsa, missing: true, error: r.stderr.slice(0, 300) };
  const a = JSON.parse(r.stdout);
  return {
    ghsa, cve: a.cve_id ?? null, severity: a.severity, type: a.type, withdrawn_at: a.withdrawn_at ?? null,
    vector: a.cvss_severities?.cvss_v4?.vector_string || a.cvss_severities?.cvss_v3?.vector_string
      || a.cvss?.vector_string || null,
    epss: a.epss ?? null,
    packages: (a.vulnerabilities ?? []).map(v => ({ name: v.package?.name, range: v.vulnerable_version_range,
                                                   patched: v.first_patched_version })),
  };
}

// "CVSS:3.1/AV:N/AC:L/..." -> { AV: 'N', AC: 'L', ... }
export function vectorMetrics(vector) {
  const out = {};
  for (const part of String(vector ?? '').split('/')) {
    const m = /^([A-Z]{1,3}):([A-Z])$/.exec(part);
    if (m) out[m[1]] = m[2];
  }
  return out;
}
