// Runs one headless Claude Code session and turns its stream-json output into what the grader and the report read.
import { spawn } from 'node:child_process';
import { closeSync, openSync, readFileSync } from 'node:fs';
import { GIT_ENV } from './util.mjs';

// The session under test: only the plugin from this checkout, the repository's own project settings (hooks,
// permissions), none of the user's settings or installed plugins, the default permission mode with nobody to
// answer a prompt, so a command outside the skill's allowed-tools is denied and recorded.
export function claudeArgs({ prompt, model, effort, pluginDir, sessionId, maxBudgetUsd }) {
  return [
    '-p', prompt,
    '--model', model, '--effort', effort,
    '--plugin-dir', pluginDir,
    '--setting-sources', 'project,local',
    '--settings', JSON.stringify({ enabledPlugins: { 'devx-qa@devx-plugins': false } }),
    '--permission-prompts', 'none',
    '--output-format', 'stream-json', '--verbose',
    '--session-id', sessionId,
    ...(maxBudgetUsd ? ['--max-budget-usd', String(maxBudgetUsd)] : []),
  ];
}

// Resolves when the session exits or the ceiling kills its whole process group (Bash children included).
export function runClaude({ cwd, env, args, streamPath, stderrPath, timeoutS }) {
  return new Promise((resolve, reject) => {
    const out = openSync(streamPath, 'w'), err = openSync(stderrPath, 'w');
    const t0 = Date.now();
    const child = spawn('claude', args, {
      cwd, detached: true, stdio: ['ignore', out, err],
      // Claude Code's own handling of background tasks at the end of a print-mode turn: the skill runs its gates in
      // the background and waits for their completion notices.
      env: { ...process.env, ...GIT_ENV, ...env },
    });
    let timedOut = false;
    const kill = sig => { try { process.kill(-child.pid, sig); } catch { /* already gone */ } };
    const timer = timeoutS > 0 ? setTimeout(() => { timedOut = true; kill('SIGTERM'); setTimeout(() => kill('SIGKILL'), 15_000); },
      timeoutS * 1000) : null;
    child.on('error', e => { clearTimeout(timer); closeSync(out); closeSync(err); reject(e); });
    child.on('exit', (code, signal) => {
      clearTimeout(timer); closeSync(out); closeSync(err);
      resolve({ code, signal, timedOut, wall_s: (Date.now() - t0) / 1000 });
    });
  });
}

const textOf = c => (typeof c === 'string' ? c
  : Array.isArray(c) ? c.map(b => (b.type === 'text' ? b.text : b.type === 'image' ? '[image]' : JSON.stringify(b))).join('\n')
  : JSON.stringify(c));

const CAP = 40_000; // per tool result in the trace; the full stream stays on disk beside it

export function parseStream(streamPath) {
  const events = [];
  for (const line of readFileSync(streamPath, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch { /* a torn last line after a kill */ }
  }
  const init = events.find(e => e.type === 'system' && e.subtype === 'init') ?? null;
  const result = [...events].reverse().find(e => e.type === 'result') ?? null;
  const transcript = [];
  const calls = new Map(); // tool_use_id -> call
  const bash = [], skills = [], reads = [], texts = [];
  let pendingThinking = '';
  for (const e of events) {
    const sub = e.parent_tool_use_id ?? null;
    const who = sub ? ' (subagent)' : '';
    if (e.type === 'assistant') {
      for (const b of e.message?.content ?? []) {
        if (b.type === 'thinking' && b.thinking) pendingThinking += (pendingThinking ? '\n' : '') + b.thinking;
        else if (b.type === 'text' && b.text?.trim()) {
          transcript.push({ role: 'assistant', content: (sub ? '[subagent] ' : '') + b.text,
                            ...(pendingThinking ? { thinking: pendingThinking } : {}) });
          pendingThinking = '';
          texts.push({ text: b.text, sub, index: transcript.length - 1 });
        } else if (b.type === 'tool_use') {
          transcript.push({ role: 'tool_call', name: b.name + who, content: JSON.stringify(b.input ?? {}, null, 2),
                            ...(pendingThinking ? { thinking: pendingThinking } : {}) });
          pendingThinking = '';
          const call = { id: b.id, name: b.name, input: b.input ?? {}, sub, index: transcript.length - 1, result: null, is_error: false };
          calls.set(b.id, call);
          if (b.name === 'Bash') bash.push(call);
          if (b.name === 'Skill') skills.push(call);
          if (b.name === 'Read' || b.name === 'Grep' || b.name === 'Glob') reads.push(call);
        }
      }
    } else if (e.type === 'user') {
      const content = e.message?.content;
      if (!Array.isArray(content)) continue;
      for (const b of content) {
        if (b.type !== 'tool_result') continue;
        const text = textOf(b.content);
        const call = calls.get(b.tool_use_id);
        if (call) { call.result = text; call.is_error = !!b.is_error; }
        transcript.push({ role: 'tool_result',
                          content: text.length > CAP ? text.slice(0, CAP) + `\n[... ${text.length - CAP} more characters in stream.jsonl]` : text });
      }
    }
  }
  // The closing report: the main thread's text after its last tool call.
  const lastCall = Math.max(-1, ...[...calls.values()].filter(c => !c.sub).map(c => c.index));
  const closing = texts.filter(t => !t.sub && t.index > lastCall).map(t => t.text).join('\n\n');
  const report = closing || result?.result || '';
  return { events, init, result, transcript, bash, skills, reads, report, raw: events.map(e => JSON.stringify(e)).join('\n') };
}
