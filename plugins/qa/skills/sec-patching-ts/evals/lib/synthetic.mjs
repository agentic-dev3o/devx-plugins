// Builds the synthetic npm fixtures: a small TypeScript service with typecheck, build and node --test gates, a CI
// workflow, a Trivy workflow, and a history whose lockfiles hold exactly the versions a case asks for.
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { git, sh } from './util.mjs';

// What src/index.ts does with each dependency. Some calls reach an advisory's vulnerable path and some don't,
// so exposure is a real question for the run.
const USES = {
  express: {
    import: "import express from 'express';",
    code: `export const app = express();
app.use(express.json({ limit: '100kb' }));
app.get('/health', (_req, res) => { res.json({ ok: true }); });
app.post('/orders', (req, res) => { res.status(201).json(normalizeOrder(req.body)); });`,
    types: { '@types/express': '^4.17.21' },
  },
  axios: {
    import: "import axios from 'axios';",
    code: `export async function fetchRates(base: string): Promise<unknown> {
  const res = await axios.get('https://rates.example.com/v1/latest', { params: { base }, timeout: 5000 });
  return res.data;
}`,
  },
  lodash: {
    import: "import _ from 'lodash';",
    code: `const DEFAULTS = { currency: 'EUR', items: [] as unknown[] };
export function normalizeOrder(input: unknown): Record<string, unknown> {
  const order = _.merge({}, DEFAULTS, input);
  return { ...order, reference: _.trim(String((order as { reference?: unknown }).reference ?? '')) };
}`,
    types: { '@types/lodash': '^4.17.20' },
  },
  mkdirp: {
    import: "import mkdirp from 'mkdirp';",
    code: `export function ensureExportDir(dir: string): string {
  mkdirp.sync(dir);
  return dir;
}`,
    types: { '@types/mkdirp': '0.5.2' },
  },
  semver: {
    import: "import semver from 'semver';",
    code: `export function clientSupported(version: string): boolean {
  return semver.satisfies(version, '>=2.0.0 <4.0.0');
}`,
    types: { '@types/semver': '^7.5.8' },
  },
  ms: {
    import: "import ms from 'ms';",
    code: 'export const SESSION_TTL_MS: number = ms(\'2h\');',
    types: { '@types/ms': '^2.1.0' },
  },
};

const BASE_DEV = { typescript: '~5.9.3', '@types/node': '^24.0.0' };
const AUTHOR = { GIT_AUTHOR_NAME: 'Fixture Author', GIT_AUTHOR_EMAIL: 'fixture@example.invalid',
                 GIT_COMMITTER_NAME: 'Fixture Author', GIT_COMMITTER_EMAIL: 'fixture@example.invalid' };

function write(root, rel, text) {
  mkdirSync(dirname(join(root, rel)), { recursive: true });
  writeFileSync(join(root, rel), text);
}

function sourceFor(deps) {
  const used = Object.keys(deps).filter(d => USES[d]);
  // normalizeOrder lives with lodash; express needs it.
  const lines = used.map(d => USES[d].import);
  if (used.includes('express') && !used.includes('lodash'))
    lines.push('const normalizeOrder = (o: unknown): unknown => o;');
  return `${lines.join('\n')}\n\n${used.map(d => USES[d].code).join('\n\n')}\n`;
}

function testFor(deps) {
  const checks = [];
  if (deps.semver) checks.push("test('client versions', () => { assert.equal(m.clientSupported('3.1.0'), true); assert.equal(m.clientSupported('1.0.0'), false); });");
  if (deps.lodash) checks.push("test('orders get defaults', () => { assert.equal(m.normalizeOrder({ reference: ' A1 ' }).reference, 'A1'); });");
  if (deps.mkdirp) checks.push("test('export dir', () => { const d = require('node:path').join(require('node:os').tmpdir(), 'spt-' + process.pid, 'x'); assert.equal(m.ensureExportDir(d), d); });");
  if (deps.express) checks.push("test('app has routes', () => { assert.equal(typeof m.app.listen, 'function'); });");
  if (deps.ms) checks.push("test('ttl', () => { assert.equal(m.SESSION_TTL_MS, 7200000); });");
  return `const test = require('node:test');\nconst assert = require('node:assert/strict');\nconst m = require('../dist/index.js');\n\n${checks.join('\n')}\n`;
}

function manifest(name, deps, devDeps) {
  return {
    name, version: '1.0.0', private: true, description: 'Orders service',
    main: 'dist/index.js', engines: { node: '>=24' },
    scripts: { typecheck: 'tsc --noEmit', build: 'tsc', test: 'node --test test/' },
    dependencies: deps, devDependencies: devDeps,
  };
}

const STATIC = {
  'tsconfig.json': JSON.stringify({ compilerOptions: { target: 'es2022', module: 'commonjs', moduleResolution: 'node',
    esModuleInterop: true, strict: true, skipLibCheck: true, outDir: 'dist', rootDir: 'src', types: ['node'] },
    include: ['src'] }, null, 2) + '\n',
  '.gitignore': 'node_modules/\ndist/\n.env*\n',
  '.nvmrc': '24\n',
  '.github/workflows/ci.yml': `name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-node@v5
        with:
          node-version-file: .nvmrc
          cache: npm
      - run: npm ci --ignore-scripts
      - run: npm run typecheck
      - run: npm run build
      - run: npm test
`,
  '.github/workflows/security.yml': `name: Security
on:
  pull_request:
  schedule:
    - cron: '0 6 * * 1'
jobs:
  trivy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: aquasecurity/trivy-action@0.33.1
        with:
          scan-type: fs
          scan-ref: .
          scanners: vuln
          exit-code: '1'
`,
};

// Lock `deps` at the versions a case asks for, then declare them with the case's ranges. `deps` maps a name to
// [declared spec, locked version].
function lockAndDeclare(dir, name, deps, devDeps) {
  const exact = o => Object.fromEntries(Object.entries(o).map(([k, [, v]]) => [k, v]));
  const declared = o => Object.fromEntries(Object.entries(o).map(([k, [s]]) => [k, s]));
  writeFileSync(join(dir, 'package.json'), JSON.stringify(manifest(name, exact(deps), declared(devDeps)), null, 2) + '\n');
  sh('npm', ['install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund'], { cwd: dir, timeoutMs: 600_000 });
  const pkg = manifest(name, declared(deps), declared(devDeps));
  writeFileSync(join(dir, 'package.json'), JSON.stringify(pkg, null, 2) + '\n');
  const lock = JSON.parse(readFileSync(join(dir, 'package-lock.json'), 'utf8'));
  lock.packages[''].dependencies = pkg.dependencies;
  lock.packages[''].devDependencies = pkg.devDependencies;
  writeFileSync(join(dir, 'package-lock.json'), JSON.stringify(lock, null, 2) + '\n');
  sh('npm', ['install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund'], { cwd: dir, timeoutMs: 600_000 });
  const after = JSON.parse(readFileSync(join(dir, 'package-lock.json'), 'utf8'));
  for (const [k, [, v]] of Object.entries(deps)) {
    const got = after.packages[`node_modules/${k}`]?.version;
    if (got !== v) throw new Error(`fixture ${name}: ${k} locked at ${got}, wanted ${v}`);
  }
}

const fakeIntegrity = s => 'sha512-' + createHash('sha512').update(s).digest('base64');

// Rewrites lockfile entries in place: the only way to hold a version the registry no longer serves (a malicious
// release, since unpublished). Each patch is { name, version, dependencies?, hasInstallScript?, parent? }.
function patchLock(dir, patches) {
  const p = join(dir, 'package-lock.json');
  const lock = JSON.parse(readFileSync(p, 'utf8'));
  for (const x of patches) {
    const key = `node_modules/${x.name}`;
    const base = x.name.split('/').pop();
    lock.packages[key] = {
      ...(lock.packages[key] ?? {}), version: x.version,
      resolved: `https://registry.npmjs.org/${x.name}/-/${base}-${x.version}.tgz`,
      integrity: fakeIntegrity(`${x.name}@${x.version}`),
      ...(x.license ? { license: x.license } : {}),
      ...(x.dependencies ? { dependencies: { ...(lock.packages[key]?.dependencies ?? {}), ...x.dependencies } } : {}),
      ...(x.hasInstallScript ? { hasInstallScript: true } : {}),
    };
  }
  writeFileSync(p, JSON.stringify(lock, null, 2) + '\n');
}

function commit(dir, message, date) {
  git(dir, 'add', '-A');
  sh('git', ['commit', '-q', '-m', message], { cwd: dir, env: { ...AUTHOR, GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date } });
}

// spec.history: ordered commits. Each is { message, date, deps, devDeps?, lockPatches?, files?, tag? } where deps
// are full replacements; files maps extra paths to contents. Returns the work dir, ready to clone as a bare repo.
export function buildSynthetic(spec, outBare) {
  const dir = mkdtempSync(join(tmpdir(), `spt-fixture-${spec.id}-`));
  try {
    git(dir, 'init', '-q', '-b', 'main');
    for (const [rel, text] of Object.entries(STATIC)) write(dir, rel, text);
    for (const h of spec.history) {
      const devDeps = { ...Object.fromEntries(Object.entries(BASE_DEV).map(([k, v]) => [k, [v]])), ...(h.devDeps ?? {}) };
      for (const d of Object.keys(h.deps)) for (const [t, v] of Object.entries(USES[d]?.types ?? {})) devDeps[t] ??= [v];
      write(dir, 'src/index.ts', sourceFor(h.deps));
      write(dir, 'test/index.test.js', testFor(h.deps));
      for (const [rel, text] of Object.entries(h.files ?? {})) write(dir, rel, text);
      lockAndDeclare(dir, spec.name, h.deps, devDeps);
      if (h.lockPatches) patchLock(dir, h.lockPatches);
      commit(dir, h.message, h.date);
      if (h.tag) sh('git', ['tag', '-a', h.tag, '-m', h.tag], { cwd: dir, env: { ...AUTHOR, GIT_COMMITTER_DATE: h.date } });
    }
    rmSync(outBare, { recursive: true, force: true });
    mkdirSync(dirname(outBare), { recursive: true });
    git(dirname(outBare), 'clone', '-q', '--bare', '--no-local', dir, outBare);
    git(outBare, 'remote', 'remove', 'origin');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
