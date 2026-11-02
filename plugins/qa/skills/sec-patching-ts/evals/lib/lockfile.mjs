// Reads lockfiles and manifests at a git revision: which version of each package is locked where.
import { posix } from 'node:path';
import { git, gitShow, parseJsonc, sh } from './util.mjs';

// One entry per locked copy: { name, version, path } where path names its place in the tree
// ("shadcn/zod" in bun.lock, "node_modules/shadcn/node_modules/zod" in package-lock.json).
export function lockInstances(text, lockfile) {
  if (text == null) return [];
  const base = posix.basename(lockfile);
  const out = [];
  if (base === 'bun.lock') {
    const d = parseJsonc(text);
    for (const [path, v] of Object.entries(d.packages ?? {})) {
      const spec = Array.isArray(v) ? v[0] : null;
      if (typeof spec !== 'string') continue;
      const at = spec.lastIndexOf('@');
      if (at <= 0) continue;
      const name = spec.slice(0, at), version = spec.slice(at + 1);
      if (/^(workspace|link|file|git|github):/.test(version)) continue;
      out.push({ name, version, path });
    }
  } else if (base === 'package-lock.json' || base === 'npm-shrinkwrap.json') {
    const d = JSON.parse(text);
    for (const [path, v] of Object.entries(d.packages ?? {})) {
      if (!path.includes('node_modules/') || v.link || !v.version) continue;
      const name = v.name ?? path.slice(path.lastIndexOf('node_modules/') + 'node_modules/'.length);
      out.push({ name, version: v.version, path, resolved: v.resolved, integrity: v.integrity,
                 hasInstallScript: !!v.hasInstallScript });
    }
  } else {
    throw new Error(`unsupported lockfile ${lockfile}`);
  }
  return out;
}

export function lockAt(repo, rev, lockfile) {
  return lockInstances(gitShow(repo, rev, lockfile), lockfile);
}

// Whether instance `inst` sits under parent package `parent` in its lockfile's tree.
export function underParent(inst, parent) {
  return inst.path.startsWith(`${parent}/`) || inst.path.includes(`node_modules/${parent}/node_modules/`);
}

// name@version pairs present at `after` and absent at `before`.
export function movedVersions(before, after) {
  const had = new Set(before.map(i => `${i.name}@${i.version}`));
  return [...new Set(after.map(i => `${i.name}@${i.version}`))].filter(k => !had.has(k))
    .map(k => { const at = k.lastIndexOf('@'); return { name: k.slice(0, at), version: k.slice(at + 1) }; });
}

// Every package.json tracked at `rev`, parsed: { path: manifest }.
export function manifestsAt(repo, rev) {
  const files = git(repo, 'ls-tree', '-r', '--name-only', rev).split('\n')
    .filter(f => posix.basename(f) === 'package.json' && !f.includes('node_modules/'));
  const out = {};
  for (const f of files) {
    try { out[f] = JSON.parse(gitShow(repo, rev, f)); } catch { /* an invalid manifest is not ours to grade */ }
  }
  return out;
}

export const DEP_FIELDS = ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'];

// Lockfiles the repository tracks at `rev`.
export function lockfilesAt(repo, rev) {
  const r = sh('git', ['ls-tree', '-r', '--name-only', rev], { cwd: repo });
  return r.stdout.split('\n').filter(f => /(^|\/)(package-lock\.json|npm-shrinkwrap\.json|bun\.lockb?|pnpm-lock\.yaml|yarn\.lock)$/.test(f)
    && !f.includes('node_modules/'));
}
