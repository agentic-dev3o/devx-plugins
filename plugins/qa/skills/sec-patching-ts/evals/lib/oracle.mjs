// Two scripted agents for auditing the grader, no model involved:
//   null:   does nothing and says nothing. A grader that passes it is broken.
//   oracle: reaches the case's expected end state with the skill's own lockfile-only commands (cases.json
//           `oracle.commands`) and writes a report in the skill's format from the case's expectations. A grader
//           that fails it is broken, or the expectations can't be met.
// Both write a stream.jsonl in Claude Code's stream-json shape, so the grader reads them like a real session.
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { vectorMetrics } from './audit.mjs';
import { lockAt, movedVersions } from './lockfile.mjs';
import { addDays, git, sh } from './util.mjs';

export function runOracle(c, ctx) {
  const t0 = Date.now();
  const work = join(ctx.runDir, 'work');
  const events = [{ type: 'system', subtype: 'init', model: ctx.model, permissionMode: 'default', tools: [],
                    plugins: [{ name: 'devx-qa', path: ctx.pluginDir }] }];
  let n = 0;
  const call = (name, input, result = '') => {
    const id = `toolu_oracle_${++n}`;
    events.push({ type: 'assistant', parent_tool_use_id: null, message: { model: ctx.model, content: [{ type: 'tool_use', id, name, input }] } });
    events.push({ type: 'user', parent_tool_use_id: null, message: { content: [{ type: 'tool_result', tool_use_id: id, content: result }] } });
  };
  let report = '';
  if (!ctx.null) {
    const o = c.oracle ?? {};
    const date = ctx.pre.started_at.slice(0, 10);
    if ((c.kind ?? 'patch') === 'patch') {
      git(work, 'switch', '-q', '--detach', ctx.pre.prodSha);
      git(work, 'switch', '-q', '-c', `security/patch-${date}`);
      for (const cmd of o.commands ?? []) {
        const r = sh('bash', ['-c', cmd], { cwd: work, env: ctx.env, check: false, timeoutMs: 600_000 });
        if (r.status !== 0) throw Object.assign(new Error(`oracle command failed: ${cmd}: ${r.stderr.slice(0, 600)}`), { failure_class: 'harness' });
        call('Bash', { command: cmd }, r.stdout.slice(-2000));
      }
      const changed = git(work, 'status', '--porcelain', '--untracked-files=no').split('\n').filter(Boolean).map(l => l.slice(3));
      if (changed.length) {
        git(work, 'add', '--', ...changed);
        sh('git', ['commit', '-q', '-m', `fix(deps): patch vulnerable packages for production\n\nProduction: ${ctx.pre.prodSha}`], { cwd: work });
      }
      // The verification the skill does on every moved version, recorded as the commands it would run.
      for (const lf of c.lockfiles)
        for (const m of movedVersions(lockAt(work, ctx.pre.prodSha, lf), lockAt(work, 'HEAD', lf)))
          call('Bash', { command: `npm view ${m.name}@${m.version} _npmUser scripts dependencies dist.attestations --json` });
      for (const x of o.extra_commands ?? []) call('Bash', { command: x });
      call('Skill', { skill: 'code-review', args: `high --fix ${ctx.pre.prodSha}..HEAD -- Dependency versions are out of scope.` });
      git(work, 'switch', '-q', ctx.pre.branch);
    } else {
      for (const x of o.extra_commands ?? []) call('Bash', { command: x });
    }
    report = reportFor(c, ctx, date);
  }
  if (report) events.push({ type: 'assistant', parent_tool_use_id: null, message: { model: ctx.model, content: [{ type: 'text', text: report }] } });
  events.push({ type: 'result', subtype: 'success', is_error: false, result: report, num_turns: n + 1, total_cost_usd: 0,
                modelUsage: { [ctx.model]: { inputTokens: 1, outputTokens: 1, cacheReadInputTokens: 0, cacheCreationInputTokens: 0 } },
                permission_denials: [] });
  writeFileSync(ctx.streamPath, events.map(e => JSON.stringify(e)).join('\n') + '\n');
  return { wall_s: (Date.now() - t0) / 1000 };
}

// The oracle's own risk call: what the case says, else high only for an escalate-only decision.
const levelOf = a => a.risk ?? (a.decision.length === 1 && a.decision[0] === 'escalate' ? 'high' : 'low');

function riskLine(a, adv) {
  const v = vectorMetrics(adv[a.id]?.vector);
  const level = levelOf(a);
  const cvss = v.AV
    ? `CVSS AV:${v.AV} AC:${v.AC}${v.AT ? ` AT:${v.AT}` : ''} PR:${v.PR} UI:${v.UI} · ${v.VC ? `VC:${v.VC} VI:${v.VI} VA:${v.VA}` : `C:${v.C} I:${v.I} A:${v.A}`}`
    : 'CVSS n/a';
  return `${cvss} · EPSS n/a · ships → ${level}`;
}

function reportFor(c, ctx, date) {
  const ex = c.expect ?? {}, o = c.oracle ?? {}, adv = ctx.adv ?? {};
  const kind = c.kind ?? 'patch';
  if (kind === 'stop') return o.say ?? '';
  const advs = ex.advisories ?? [];
  const confirmed = advs.filter(a => !a.decision.includes('ruled-out'));
  const L = [];
  if (ex.incident) {
    const i = ex.incident;
    L.push('> [!CAUTION]', `> Malware: ${i.pkg}@${i.bad} was installed in production. Any machine that installed it may be compromised: CI runners, developers' machines, the production build.`,
      '> Rotate the secrets those machines could reach, from a clean machine. Purge the npm and CI caches.',
      `> Review CI logs since ${i.since}, when the version entered the lockfile (git log -S).`,
      '> Autonomy revoked: malware advisory.', '');
  }
  for (const pkg of new Set(advs.filter(a => a.decision.length === 1 && a.decision[0] === 'escalate').map(a => a.pkg)))
    L.push(`> Escalated: ${pkg} needs ${o.escalate_to?.[pkg] ?? '0.0.0'} (high risk). Schedule the upgrade now.`);
  L.push('', `Outcome: ${kind === 'report-only' ? 'report only, nothing changed' : 'patched on a work branch'}. Production commit \`${ctx.pre.prodSha}\` via --prod-ref.`, '');
  if (kind === 'report-only') {
    L.push('| Advisory | Package | Decision | Risk | Verdict |', '|---|---|---|---|---|');
    for (const a of advs) {
      const ruling = ex.rulings?.find(r => r.id === a.id);
      L.push(`| ${a.id} | ${a.pkg} | ${ruling ? ruling.say : a.decision[0]} | ${a.decision.includes('ruled-out') ? 'n/a' : riskLine(a, adv)} | n/a |`);
    }
  }
  L.push('Risk lines:');
  for (const a of confirmed) L.push(`- ${a.id} (${a.pkg}): ${riskLine(a, adv)}`);
  for (const r of ex.rulings ?? []) L.push(`- ${r.id}: ${r.say}`);
  if (kind === 'patch') {
    const exp = addDays(date, 90);
    const accepts = advs.filter(a => a.decision.includes('accept') && levelOf(a) === 'low');
    L.push('', '## Production base', `- Production commit \`${ctx.pre.prodSha}\` (--prod-ref, strong)`, '',
      '## Advisories fixed', '| Package | From → To | Change | Advisory | Severity | Risk | Verdict |', '|---|---|---|---|---|---|---|',
      '', '## Verification (trust but verify)', '- verified', '',
      '## Risk accepted', '| Package | Advisory | Risk line | Why the fix waits | Reason | Recorded in | Expires |', '|---|---|---|---|---|---|---|', '```');
    for (const a of accepts) {
      const tid = c.scanner === 'trivy' ? (adv[a.id]?.cve ?? a.id) : a.id;
      L.push(`# ${a.pkg}@x: accepted. Risk low (${riskLine(a, adv)}). Reviewed ${date}, PR n/a`, `${tid} exp:${exp}`);
    }
    L.push('```');
    if (c.scanner !== 'trivy') for (const a of accepts) L.push(`| ${a.pkg} | ${a.id} | ${riskLine(a, adv)} | major | low | proposed (accept) | ${exp} |`);
    L.push('', '## Deferred and ruled out', '| Package | Advisory | Reason |', '|---|---|---|', '',
      '## Gates', '| Gate | Baseline | Patched |', '|---|---|---|', '| test | ✓ | ✓ |', '', '## Review', 'none', '', '## Follow-ups', '- none');
  }
  return L.join('\n');
}
