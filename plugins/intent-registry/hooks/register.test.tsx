import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

const PANE = {
  plugin: 'intent-registry',
  component: 'Pane',
  requestId: 'intent-registry',
  props: {
    title: 'Intent registry',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const THOROUGH = 'Be thorough in your analysis and bold in your recommendations'
const FILE = '.claude/intents.json'

// Stands in for the project's files: what the mod reads and what it writes.
// The engine hands the path on made absolute against the working directory.
const rel = (path: string) => (path.endsWith(`/${FILE}`) ? FILE : path)

function fakeFs(on: On, files: Record<string, string> = {}) {
  on('fs.exists', (_, e) => ({ value: rel(e.path) in files }) as never)
  on('fs.read', (_, e) => {
    if (!(rel(e.path) in files)) throw new Error('missing')

    return { value: files[rel(e.path)] } as never
  })
  on('fs.write', (_, e) => {
    files[rel(e.path)] = e.text

    return { value: undefined } as never
  })

  return files
}

const saved = (files: Record<string, string>) =>
  (JSON.parse(files[FILE] ?? '{"intents":[]}') as { intents: Record<string, unknown>[] }).intents

test('a click adds the intent to the prompt box', async ($, on) => {
  const fills: string[] = []
  on('prompt.read', () => ({ value: { text: '', cursor: 0 } }))
  on('prompt.fill', (_, e) => {
    fills.push(e.text)

    return { isFilled: true, text: e.text, cursor: e.text.length }
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'run-thorough' })
    await ui.unmount()
  }

  expect(fills).toEqual([THOROUGH, THOROUGH])
})

test('with sub-session on, a click spawns a subagent on the picked model', async ($, on) => {
  const spawned: { prompt: string; model?: string }[] = []
  on('prompt.read', () => ({ value: { text: '', cursor: 0 } }))
  on('agent.spawn', (_, e) => {
    spawned.push({ prompt: e.prompt, model: e.model })

    return { model: e.model ?? 'opus', agentId: 'a1' }
  })

  const files = fakeFs(on)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'sub' })
  await ui.press({ key: 'pick-thorough' })
  await ui.press({ key: 'model-thorough-haiku' })
  await ui.press({ key: 'run-thorough' })
  await ui.unmount()

  expect(spawned).toEqual([{ prompt: THOROUGH, model: 'haiku' }])
  expect(saved(files)[0]).toMatchObject({ id: 'thorough', model: 'haiku' })
})

// Fills the box with the intent, then runs the steps of the turns given; the
// test's own turn.step hook records what model and effort each step went out on.
async function stepsAfterInject(
  $: Engine,
  on: On,
  run: (step: (turnId: string) => Promise<void>) => Promise<void>,
) {
  const sent: { turnId: string; model: string; effort: unknown }[] = []
  on('prompt.read', () => ({ value: { text: '', cursor: 0 } }))
  on('prompt.fill', (_, e) => ({
    isFilled: true,
    text: e.text,
    cursor: e.text.length,
  }))
  on('turn.step', async function* (_, e) {
    sent.push({ turnId: e.turnId, model: e.model, effort: e.effort })

    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [],
      stopReason: 'end_turn',
      usage: null,
    }
  })
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'run-thorough' })
  await ui.unmount()

  await run(async turnId => {
    const stream = $.turn.step({
      turnId,
      index: 0,
      model: 'sonnet',
      effort: 'low',
      messageCount: 1,
    } as never)
    for await (const _ of stream as AsyncIterable<unknown>) {
      // drained
    }
  })

  return sent
}

test('only the turn that carries the intent runs on its model and effort', async ($, on) => {
  const sent = await stepsAfterInject($, on, async step => {
    // A turn already running when the prompt was sent keeps its settings.
    await step('t0')
    await $.turn.start({ text: `fix it\n\n${THOROUGH}`, turnId: 't1' })
    await step('t1')
    await $.turn.complete({
      turnId: 't1',
      answer: '',
      durationMs: 1,
      isAborted: false,
      reason: 'end_turn',
    } as never)
    // The intent is spent: the next turn is back on the session's settings.
    await $.turn.start({ text: 'thanks', turnId: 't2' })
    await step('t2')
  })

  expect(sent).toEqual([
    { turnId: 't0', model: 'sonnet', effort: 'low' },
    { turnId: 't1', model: 'opus', effort: 'xhigh' },
    { turnId: 't2', model: 'sonnet', effort: 'low' },
  ])
})

test('a turn started without the intent disarms it', async ($, on) => {
  const sent = await stepsAfterInject($, on, async step => {
    await $.turn.start({ text: 'something else', turnId: 't1' })
    await step('t1')
    await $.turn.start({ text: THOROUGH, turnId: 't2' })
    await step('t2')
  })

  expect(sent).toEqual([
    { turnId: 't1', model: 'sonnet', effort: 'low' },
    { turnId: 't2', model: 'sonnet', effort: 'low' },
  ])
})

test('the picker lists the models Claude Code offers, and the pane opens once', async ($, on) => {
  const stored: Record<string, unknown> = {}
  let opens = 0
  on('config.list', () => ({
    value: [
      {
        key: 'model',
        label: 'Model',
        kind: 'choice',
        value: 'default',
        options: ['default', 'sonnet', 'opus', 'nova', 'best', 'opus[1m]', 'opusplan'],
        provider: { kind: 'engine' },
        isLocked: false,
      },
    ],
  }) as never)
  on('command.register', () => ({ value: undefined }) as never)
  on('store.get', (_, e) => ({ value: stored[e.key] }) as never)
  on('store.set', (_, e) => {
    stored[e.key] = e.value

    return { value: undefined } as never
  })
  on('ui.open', () => {
    opens += 1

    return { value: { isPlaced: true } } as never
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  fakeFs(on)

  const start = { cwd: '/', surface: 'desktop', isInteractive: true } as const
  await $.session.start(start)
  await $.session.start(start)
  expect(opens).toBe(1)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'pick-thorough' })
  await ui.press({ key: 'model-thorough-nova' })
  expect(await ui.find({ key: 'pick-thorough' })).toBeTruthy()
  await expect(ui.press({ key: 'model-thorough-best' })).rejects.toBeTruthy()
  await ui.unmount()
})

const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const

function sessionBasics(on: On) {
  on('config.list', () => ({ value: [] }) as never)
  on('command.register', () => ({ value: undefined }) as never)
  on('store.get', () => ({ value: true }) as never)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('ui.toast', () => ({ value: undefined }) as never)
}

test('the registry is read from .claude/intents.json', async ($, on) => {
  sessionBasics(on)
  fakeFs(on, {
    [FILE]: JSON.stringify({
      intents: [
        { name: 'Ship it', text: 'Ship it', model: 'haiku', effort: 'low' },
        { name: 'No text' },
      ],
    }),
  })
  await $.session.start(START)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect(await ui.find({ key: 'run-ship-it' })).toBeTruthy()
  await expect(ui.press({ key: 'run-thorough' })).rejects.toBeTruthy()
  await ui.unmount()
})

test('a new intent is added from the pane and saved to the file', async ($, on) => {
  const files = fakeFs(on)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'new' })
    await ui.input({ key: 'draft-name', text: `Explain ${surface}`, kind: 'change' })
    await ui.input({ key: 'draft-text', text: 'Explain it simply', kind: 'change' })
    await ui.press({ key: 'draft-save' })
    expect(await ui.find({ key: `run-explain-${surface}` })).toBeTruthy()
    await ui.unmount()
  }

  expect(saved(files).map(intent => intent.id)).toEqual([
    'thorough',
    'async-scan',
    'ui-review',
    'explain-terminal',
    'explain-desktop',
  ])
})

test('an intent is edited, then deleted after a confirmation', async ($, on) => {
  const files = fakeFs(on)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'edit-thorough' })
  await ui.input({ key: 'draft-text', text: 'Be bolder', kind: 'change' })
  await ui.press({ key: 'draft-save' })
  expect(saved(files)[0]).toMatchObject({ id: 'thorough', text: 'Be bolder' })

  await ui.press({ key: 'edit-thorough' })
  await ui.press({ key: 'draft-delete' })
  expect(saved(files)).toHaveLength(3)
  await ui.press({ key: 'draft-delete' })
  expect(saved(files).map(intent => intent.id)).toEqual(['async-scan', 'ui-review'])
  await ui.unmount()
})

test('a file that does not parse is never written over', async ($, on) => {
  sessionBasics(on)
  const files = fakeFs(on, { [FILE]: '{ broken' })
  await $.session.start(START)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'pick-thorough' })
  await ui.press({ key: 'model-thorough-haiku' })
  await ui.unmount()

  expect(files[FILE]).toBe('{ broken')
})
