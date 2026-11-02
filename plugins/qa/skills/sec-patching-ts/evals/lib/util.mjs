// Shared helpers for the sec-patching-ts eval: processes, git, semver, JSONC.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { homedir } from 'node:os';

// Commits made by the harness or by the run never use the user's signing key: a passphrase prompt would hang
// the headless session.
export const GIT_ENV = {
  GIT_CONFIG_COUNT: '2', GIT_CONFIG_KEY_0: 'commit.gpgsign', GIT_CONFIG_VALUE_0: 'false',
  GIT_CONFIG_KEY_1: 'tag.gpgsign', GIT_CONFIG_VALUE_1: 'false', GIT_TERMINAL_PROMPT: '0',
};

export function sh(cmd, args, { cwd, env, check = true, input, timeoutMs } = {}) {
  const r = spawnSync(cmd, args, {
    cwd, input, encoding: 'utf8', maxBuffer: 1 << 30, timeout: timeoutMs,
    env: { ...process.env, ...GIT_ENV, ...(env ?? {}) },
  });
  if (r.error) throw r.error;
  if (check && r.status !== 0)
    throw new Error(`${cmd} ${args.join(' ')} exited ${r.status} in ${cwd ?? '.'}: ${(r.stderr || r.stdout).slice(0, 2000)}`);
  return r;
}

export const git = (cwd, ...args) => sh('git', args, { cwd }).stdout.replace(/\n$/, '');
export const gitOk = (cwd, ...args) => sh('git', args, { cwd, check: false }).status === 0;
export const gitShow = (cwd, rev, path) => {
  const r = sh('git', ['show', `${rev}:${path}`], { cwd, check: false });
  return r.status === 0 ? r.stdout : null;
};

export const sha256 = s => createHash('sha256').update(s).digest('hex');
export const expandHome = p => (p.startsWith('~/') ? homedir() + p.slice(1) : p);

// JSONC as Bun writes bun.lock: trailing commas, no comments. Strings are skipped so a "," inside one survives.
export function parseJsonc(text) {
  let out = '', i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === '"') {
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      out += text.slice(i, j + 1); i = j + 1; continue;
    }
    if (ch === ',') {
      let j = i + 1;
      while (/\s/.test(text[j] ?? '')) j++;
      if (text[j] === '}' || text[j] === ']') { i++; continue; }
    }
    out += ch; i++;
  }
  return JSON.parse(out);
}

// --- semver: just enough for lockfile versions and simple ranges --------------------------------------------

export function parseVersion(v) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?/.exec(String(v).trim());
  return m ? { major: +m[1], minor: +m[2], patch: +m[3], pre: m[4] ?? null } : null;
}

export function compare(a, b) {
  const x = typeof a === 'string' ? parseVersion(a) : a, y = typeof b === 'string' ? parseVersion(b) : b;
  for (const k of ['major', 'minor', 'patch']) if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1;
  if (x.pre === y.pre) return 0;
  if (x.pre == null) return 1;
  if (y.pre == null) return -1;
  return x.pre < y.pre ? -1 : 1;
}

// The skill's notion of a major: 0.x minors count as majors.
export function majorKey(v) {
  const p = typeof v === 'string' ? parseVersion(v) : v;
  if (!p) return null;
  return p.major > 0 ? String(p.major) : `0.${p.minor}`;
}

// Ranges as advisories and cases.json write them: comparators separated by spaces, alternatives by "||".
export function satisfies(version, range) {
  const v = parseVersion(version);
  if (!v) return false;
  return String(range).split('||').some(alt => alt.trim().split(/\s+/).filter(Boolean).every(c => {
    const m = /^(>=|<=|>|<|=)?\s*(.+)$/.exec(c);
    const r = parseVersion(m[2]);
    if (!r) return false;
    const d = compare(v, r);
    switch (m[1] ?? '=') {
      case '>=': return d >= 0;
      case '>': return d > 0;
      case '<=': return d <= 0;
      case '<': return d < 0;
      default: return d === 0;
    }
  }));
}

// The major a declared spec pins: "^4.17.20" -> "4", "~0.21.1" -> "0.21". Null for workspace:, catalog:, URLs.
export function specMajor(spec) {
  const s = String(spec).trim();
  if (/^(workspace:|catalog:|file:|link:|git|github:|https?:|npm:)/.test(s) || s === '*' || s === 'latest') return null;
  const m = /(\d+)(?:\.(\d+|x|\*))?/.exec(s);
  if (!m) return null;
  return +m[1] > 0 ? m[1] : `0.${/^\d+$/.test(m[2] ?? '') ? m[2] : 'x'}`;
}

// Removes heredoc bodies and quoted strings, so text inside a commit message or a grep pattern never reads as a
// command.
export function stripQuoted(command) {
  return String(command)
    .replace(/<<-?\s*(['"]?)(\w+)\1[\s\S]*?\n\s*\2\b/g, ' ')
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'[^']*'/g, "''");
}

export function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
