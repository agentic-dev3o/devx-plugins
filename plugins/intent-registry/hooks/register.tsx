import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type {
  ArmedIntent,
  Intent,
  IntentDraft,
  IntentEffort,
  IntentModel,
  IntentPick,
} from '../types'

const PANE = 'intent-registry'
const TITLE = 'Intent registry'

// The registry file, relative to the session's working directory: a project's
// intents, which a team can commit and share.
const FILE = '.claude/intents.json'

// The registry until the project has a file; the pane's first change writes
// them to it.
const BUILT_IN: readonly Intent[] = [
  {
    id: 'thorough',
    name: 'Thorough & bold',
    text: 'Be thorough in your analysis and bold in your recommendations',
    model: 'opus',
    effort: 'xhigh',
  },
  {
    id: 'async-scan',
    name: 'Sequential async scan',
    text: 'Do a deep scan of all hot paths and fix any unnecessary sequential async function calls',
    model: 'sonnet',
    effort: 'high',
  },
  {
    id: 'ui-review',
    name: 'Senior designer UI review',
    text: 'Review the UI as a senior product designer, take screenshots, give it a score by using esoteric grading, then iterate until 9/10 is reached',
    model: 'opus',
    effort: 'high',
  },
]

// Used until the engine's own list is read, and where it offers none.
const FALLBACK_MODELS: readonly IntentModel[] = ['opus', 'sonnet', 'haiku']
const EFFORTS: readonly IntentEffort[] = [
  'session',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
]

const EFFORT_LABELS: Record<IntentEffort, string> = {
  session: 'Session',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra',
  max: 'Max',
}

// The labels follow the alias, so a new model or version needs no change here.
const modelLabel = (model: IntentModel): string =>
  model === 'session'
    ? 'Session'
    : model.charAt(0).toUpperCase() + model.slice(1)

const isSub = atom({ plugin: 'intent-registry', key: 'isSub' } as const, false)
const intents = atom({ plugin: 'intent-registry', key: 'intents' } as const, [
  ...BUILT_IN,
])
const fileError = atom(
  { plugin: 'intent-registry', key: 'fileError' } as const,
  null,
)
const isFromFile = atom(
  { plugin: 'intent-registry', key: 'isFromFile' } as const,
  false,
)
const draft = atom({ plugin: 'intent-registry', key: 'draft' } as const, null)
const open = atom({ plugin: 'intent-registry', key: 'open' } as const, null)
const armed = atom({ plugin: 'intent-registry', key: 'armed' } as const, null)
const models = atom(
  { plugin: 'intent-registry', key: 'models' } as const,
  [...FALLBACK_MODELS],
)
const subEfforts = atom(
  { plugin: 'intent-registry', key: 'subEfforts' } as const,
  {},
)

// The mockup's tinted surface: a translucent warm gray, readable on a light
// and on a dark theme.
const TINT = 'rgba(115,114,108,0.16)'

const slug = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') || 'intent'

// An id no other intent holds, from the name.
const freshId = (name: string, taken: readonly Intent[]): string => {
  const base = slug(name)
  let id = base
  for (let n = 2; taken.some(intent => intent.id === id); n += 1) {
    id = `${base}-${n}`
  }

  return id
}

// Reads one entry of the file; a name and a text are required, the rest
// falls back to the session's model and effort.
const parseIntent = (
  raw: unknown,
  taken: readonly Intent[],
): Intent | undefined => {
  if (typeof raw !== 'object' || raw === null) return undefined
  const entry = raw as Record<string, unknown>
  const name = typeof entry.name === 'string' ? entry.name.trim() : ''
  const text = typeof entry.text === 'string' ? entry.text.trim() : ''
  if (name === '' || text === '') return undefined
  const wanted = typeof entry.id === 'string' ? slug(entry.id) : ''
  const id =
    wanted !== '' && !taken.some(intent => intent.id === wanted)
      ? wanted
      : freshId(name, taken)
  const model =
    typeof entry.model === 'string' && entry.model !== '' ? entry.model : 'session'
  const effort = EFFORTS.includes(entry.effort as IntentEffort)
    ? (entry.effort as IntentEffort)
    : 'session'

  return { id, name, text, model, effort }
}

type Loaded = { list: Intent[]; error: string | null; isFile: boolean }

// The file holds `{ "intents": [...] }` (a bare list is read too). A file that
// does not parse keeps the built-in list and an error, and is never written over.
async function readRegistry($: EngineInterface): Promise<Loaded> {
  if (!(await $.fs.exists(FILE))) {
    return { list: [...BUILT_IN], error: null, isFile: false }
  }
  try {
    const parsed: unknown = JSON.parse(await $.fs.read(FILE))
    const entries = Array.isArray(parsed)
      ? parsed
      : (parsed as { intents?: unknown } | null)?.intents
    if (!Array.isArray(entries)) throw new Error('no "intents" list')
    const list: Intent[] = []
    for (const raw of entries) {
      const intent = parseIntent(raw, list)
      if (intent !== undefined) list.push(intent)
    }

    return { list, error: null, isFile: true }
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err)

    return { list: [...BUILT_IN], error: `${FILE}: ${why}`, isFile: true }
  }
}

async function loadRegistry($: EngineInterface) {
  const loaded = await readRegistry($)
  await update($, intents, () => loaded.list)
  await update($, fileError, () => loaded.error)
  await update($, isFromFile, () => loaded.isFile)
  if (loaded.error !== null) $.ui.toast(`${TITLE}: ${loaded.error}`)
}

// Writes the whole registry to the file, then shows it. Refused while the
// file holds something the mod could not read, so nothing of it is lost.
async function saveRegistry(
  $: EngineInterface,
  list: Intent[],
): Promise<boolean> {
  const error = await read($, fileError)
  if (error !== null) {
    $.ui.toast(`${TITLE}: fix ${FILE} first (${error})`)

    return false
  }
  try {
    await $.fs.write(FILE, `${JSON.stringify({ intents: list }, null, 2)}\n`)
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err)
    $.ui.toast(`${TITLE}: could not write ${FILE} (${why})`)

    return false
  }
  await update($, intents, () => list)
  await update($, isFromFile, () => true)

  return true
}

async function setPick(
  $: EngineInterface,
  id: string,
  change: Partial<IntentPick>,
) {
  const list = await read($, intents)
  await saveRegistry(
    $,
    list.map(intent => (intent.id === id ? { ...intent, ...change } : intent)),
  )
}

async function saveDraft($: EngineInterface) {
  const now = await read($, draft)
  if (now === null) return
  const name = now.name.trim()
  const text = now.text.trim()
  if (name === '' || text === '') {
    $.ui.toast(`${TITLE}: an intent needs a name and a prompt`)

    return
  }
  const list = await read($, intents)
  const next =
    now.id === null
      ? [
          ...list,
          { id: freshId(name, list), name, text, model: 'session', effort: 'session' as const },
        ]
      : list.map(intent =>
          intent.id === now.id ? { ...intent, name, text } : intent,
        )
  if (await saveRegistry($, next)) await update($, draft, () => null)
}

async function deleteDraft($: EngineInterface) {
  const now = await read($, draft)
  if (now === null || now.id === null) return
  if (!now.isDeleting) {
    await update($, draft, () => ({ ...now, isDeleting: true }))

    return
  }
  const list = await read($, intents)
  const gone = now.id
  if (await saveRegistry($, list.filter(intent => intent.id !== gone))) {
    await update($, draft, () => null)
    await update($, open, (o: string | null) => (o === gone ? null : o))
  }
}

// The /config model row lists every alias this build offers. Kept: plain
// model families. Left out: the session default, which `session` stands for,
// and variants (`best`, `opusplan`, the `[1m]` context sizes).
async function readModels($: EngineInterface): Promise<IntentModel[]> {
  const rows = await $.config.list()
  const options = rows.find(row => row.key === 'model')?.options ?? []
  const found = options.filter(
    option =>
      /^[a-z]+$/.test(option) &&
      !['default', 'best', 'opusplan'].includes(option),
  )

  return found.length > 0 ? found : [...FALLBACK_MODELS]
}

async function inject($: EngineInterface, intent: Intent) {
  const pick: IntentPick = { model: intent.model, effort: intent.effort }

  if (!(await read($, isSub))) {
    const box = await $.prompt.read()
    const lead = box.text.length > 0 && !/\s$/.test(box.text) ? '\n\n' : ''
    const filled = await $.prompt.fill({
      text: lead + intent.text,
      mode: 'append',
    })

    if (!filled.isFilled) {
      $.ui.toast(`${TITLE}: the prompt box could not take the intent`)

      return
    }
    await update($, armed, () => ({
      ...pick,
      text: intent.text,
      turnId: null,
    }))

    return
  }

  // Sub-session: what is typed in the box, if anything, goes with the intent.
  const box = await $.prompt.read()
  const typed = box.text.trim()
  const started = await $.agent.spawn({
    prompt: typed.length > 0 ? `${typed}\n\n${intent.text}` : intent.text,
    description: intent.name,
    ...(pick.model === 'session' ? {} : { model: pick.model }),
  })

  if (started.deny !== undefined || started.agentId === undefined) {
    $.ui.toast(`${TITLE}: not started (${started.deny ?? 'no agent id'})`)

    return
  }
  const agentId = started.agentId
  await update($, subEfforts, (all: Record<string, IntentEffort>) => ({
    ...all,
    [agentId]: pick.effort,
  }))
  if (typed.length > 0) await $.prompt.fill({ text: '', mode: 'replace' })
  $.ui.toast(`${TITLE}: "${intent.name}" runs in a sub-session`)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'intents',
      description: 'Open the Intent registry pane',
    })
    const offered = await readModels($)
    await update($, models, () => offered)
    await loadRegistry($)
    // The pane opens by itself once, the first time the mod runs; after that
    // /intents opens it, and a session start or a reload leaves it alone.
    if ((await $.store.get('opened')) !== true) {
      const shown = await $.ui.open({ id: PANE, title: TITLE })
      if (shown.isPlaced) await $.store.set('opened', true)
    }

    return next(e)
  })

  // /intents reads the file again, so an edit made outside the pane shows.
  on('command.run', { command: 'intents' }, async $ => {
    await loadRegistry($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Intent registry opened.' }
  })

  // The turn that carries an injected intent runs on that intent's model and
  // effort. The intent is tied to that turn when it starts, not when the prompt
  // is sent: a prompt sent while a turn runs waits, and the running turn must
  // not take the intent's settings. A turn started from a prompt without the
  // intent disarms it.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && e.text !== '') {
      await update($, armed, (now: ArmedIntent | null) => {
        if (now === null || now.turnId != null) return now

        return e.text.includes(now.text) ? { ...now, turnId: e.turnId } : null
      })
    }

    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    let pick: Partial<IntentPick> | undefined

    if (e.agentId === undefined) {
      const now = await read($, armed)
      if (now !== null && now.turnId === e.turnId) pick = now
    } else {
      // Kept for the agent's whole life: a subagent woken for a later turn
      // runs at the same effort. The map is the session's and stays small.
      const effort = (await read($, subEfforts))[e.agentId]
      if (effort !== undefined) pick = { effort }
    }

    const model =
      pick?.model === undefined || pick.model === 'session'
        ? e.model
        : pick.model
    const effort =
      pick?.effort === undefined || pick.effort === 'session'
        ? e.effort
        : pick.effort

    return yield* next({ ...e, model, effort })
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      await update($, armed, (now: ArmedIntent | null) =>
        now !== null && now.turnId === e.turnId ? null : now,
      )
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Input, Text } = $.ui.resolve(e)
    const sub = await read($, isSub)
    const list = await read($, intents)
    const error = await read($, fileError)
    const fromFile = await read($, isFromFile)
    const writing = await read($, draft)
    const opened = await read($, open)
    const offered = await read($, models)
    // A graphical surface pads its buttons; the terminal draws a plain one
    // flush. The picker's column titles are inset to sit over their options.
    const inset = e.surface === 'terminal' ? 0 : 1
    const setDraft = (change: Partial<IntentDraft>) =>
      update($, draft, (now: IntentDraft | null) =>
        now === null ? now : { ...now, ...change, isDeleting: false },
      )

    // The form a new or an edited intent is written in.
    const form = (now: IntentDraft) => (
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor="claude"
        paddingX={1}
        rowGap="sm"
      >
        <Input
          key="draft-name"
          label="Name"
          placeholder="Thorough & bold"
          value={now.name}
          autoFocus
          onInput={name => setDraft({ name })}
          onSubmit={() => saveDraft($)}
        />
        <Input
          key="draft-text"
          label="Prompt"
          placeholder="What the intent asks of Claude"
          rows={3}
          value={now.text}
          onInput={text => setDraft({ text })}
          onSubmit={() => saveDraft($)}
        />
        <Box justifyContent="space-between">
          <Box>
            <Button
              key="draft-save"
              label="Save"
              variant="primary"
              onPress={() => saveDraft($)}
            />
            <Button
              key="draft-cancel"
              label="Cancel"
              onPress={() => update($, draft, () => null)}
            />
          </Box>
          {now.id !== null && (
            <Button
              key="draft-delete"
              label={now.isDeleting ? 'Confirm delete' : 'Delete'}
              plain
              dimColor={!now.isDeleting}
              onPress={() => deleteDraft($)}
            />
          )}
        </Box>
      </Box>
    )

    return (
      <Box flexDirection="column" gap="md">
        <Box flexDirection="column">
          <Box justifyContent="space-between" alignItems="center">
            <Text weight="medium">
              {sub && <Text color="claude">● </Text>}
              Run in a sub-session
            </Text>
            {/* A desktop draws a Button's own label in its theme color and
                ignores a Text inside it: the pill around a plain Button is
                what turns orange. */}
            <Box
              borderStyle="round"
              borderColor={sub ? 'claude' : 'subtle'}
              {...(sub ? { backgroundColor: 'claude' } : {})}
              paddingX={1}
            >
              <Button
                key="sub"
                label={sub ? 'On' : 'Off'}
                plain
                onPress={() => update($, isSub, (now: boolean) => !now)}
              />
            </Box>
          </Box>
          <Text dimColor size="caption">
            {sub
              ? 'A click starts the intent in a background sub-session.'
              : 'A click adds the intent to the prompt box.'}
          </Text>
        </Box>
        {error !== null && (
          <Text color="error" size="caption">
            {`${error}. The built-in intents are shown and the pane won't write the file until it is fixed; /intents reads it again.`}
          </Text>
        )}
        {list.map((intent, index) => {
          if (writing !== null && writing.id === intent.id) return form(writing)
          const isOpen = opened === intent.id
          const toggle = () =>
            update($, open, (now: string | null) =>
              now === intent.id ? null : intent.id,
            )

          return (
            <Box
              flexDirection="column"
              borderStyle="round"
              borderColor="subtle"
              paddingX={1}
              rowGap="sm"
            >
              {/* A column stretches the Button over the row's width, and the
                  keyed Box lights the whole row under the pointer. */}
              <Box
                key={`row-${intent.id}`}
                flexDirection="column"
                backgroundColor={TINT}
                hover={{ backgroundColor: 'claude' }}
                paddingY="xs"
              >
                <Button
                  key={`run-${intent.id}`}
                  {...(index < 9 ? { hotkey: String(index + 1) } : {})}
                  plain
                  label={intent.name}
                  onPress={() => inject($, intent)}
                />
                {/* Outside the Button, which a desktop draws as its label
                    alone; absolute, so the Button keeps the whole row. */}
                <Box position="absolute" right={1}>
                  <Text dimColor size="footnote">
                    {sub ? 'Run' : 'Insert'}
                  </Text>
                </Box>
              </Box>
              <Text dimColor size="footnote">
                {intent.text}
              </Text>
              <Box justifyContent="space-between">
                <Button
                  key={`edit-${intent.id}`}
                  label="Edit"
                  plain
                  dimColor
                  onPress={() =>
                    update($, draft, () => ({
                      id: intent.id,
                      name: intent.name,
                      text: intent.text,
                      isDeleting: false,
                    }))
                  }
                />
                {/* Two Buttons, as a desktop keeps a Button's own dimColor
                    but not a Text's inside it: the model at full strength,
                    the effort in gray. */}
                <Box columnGap={1}>
                  <Button
                    key={`pick-${intent.id}`}
                    label={modelLabel(intent.model)}
                    plain
                    onPress={toggle}
                  />
                  <Button
                    key={`pick-effort-${intent.id}`}
                    label={`${EFFORT_LABELS[intent.effort]} ${isOpen ? '▴' : '▾'}`}
                    plain
                    dimColor
                    onPress={toggle}
                  />
                </Box>
              </Box>
              {isOpen && (
                <Box justifyContent="flex-end">
                  <Box
                    borderStyle="round"
                    borderColor="subtle"
                    paddingX={1}
                    columnGap={2}
                  >
                    <Box flexDirection="column">
                      <Box paddingLeft={inset}>
                        <Text dimColor size="caption" weight="medium">
                          Model
                        </Text>
                      </Box>
                      {['session', ...offered].map(model => (
                        <Box
                          {...(model === intent.model
                            ? { backgroundColor: TINT }
                            : {})}
                        >
                          <Button
                            key={`model-${intent.id}-${model}`}
                            plain
                            dimColor={model !== intent.model}
                            onPress={() => setPick($, intent.id, { model })}
                          >
                            {modelLabel(model)}
                            {model === intent.model ? ' ✓' : ''}
                          </Button>
                        </Box>
                      ))}
                    </Box>
                    <Box flexDirection="column">
                      <Box paddingLeft={inset}>
                        <Text dimColor size="caption" weight="medium">
                          Effort
                        </Text>
                      </Box>
                      {EFFORTS.map(effort => (
                        <Box
                          {...(effort === intent.effort
                            ? { backgroundColor: TINT }
                            : {})}
                        >
                          <Button
                            key={`effort-${intent.id}-${effort}`}
                            plain
                            dimColor={effort !== intent.effort}
                            onPress={() => setPick($, intent.id, { effort })}
                          >
                            {EFFORT_LABELS[effort]}
                            {effort === intent.effort ? ' ✓' : ''}
                          </Button>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                </Box>
              )}
            </Box>
          )
        })}
        {writing !== null && writing.id === null ? (
          form(writing)
        ) : (
          <Button
            key="new"
            label="+ New intent"
            plain
            dimColor
            onPress={() =>
              update($, draft, () => ({
                id: null,
                name: '',
                text: '',
                isDeleting: false,
              }))
            }
          />
        )}
        <Text dimColor size="caption">
          {fromFile
            ? `Saved in ${FILE}`
            : `Built-in intents; the first change saves them to ${FILE}`}
        </Text>
      </Box>
    )
  })
}
