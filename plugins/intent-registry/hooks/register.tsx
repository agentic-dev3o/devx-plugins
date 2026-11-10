import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type {
  ArmedIntent,
  IntentEffort,
  IntentModel,
  IntentPick,
} from '../types'

const PANE = 'intent-registry'
const TITLE = 'Intent registry'

type Intent = { id: string; name: string; text: string } & IntentPick

// The registry. Add an intent here: `model` and `effort` are its defaults,
// which the person can change per intent from the pane.
const INTENTS: readonly Intent[] = [
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

// The labels follow the alias, so a new model or version needs no change here.
const modelLabel = (model: IntentModel): string =>
  model === 'session'
    ? 'Session'
    : model.charAt(0).toUpperCase() + model.slice(1)

// The /config model row lists every alias this build offers. Kept: plain
// model families. Left out: the session default, which `session` stands for,
// and variants (`best`, `opusplan`, the `[1m]` context sizes).
async function readModels($: EngineInterface): Promise<IntentModel[]> {
  const rows = await $.config.list()
  const options = rows.find(row => row.key === 'model')?.options ?? []
  const models = options.filter(
    option => /^[a-z]+$/.test(option) && !['default', 'best', 'opusplan'].includes(option),
  )

  return models.length > 0 ? models : [...FALLBACK_MODELS]
}

const EFFORT_LABELS: Record<IntentEffort, string> = {
  session: 'Session',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra',
  max: 'Max',
}

const isSub = atom({ plugin: 'intent-registry', key: 'isSub' } as const, false)
const picks = atom({ plugin: 'intent-registry', key: 'picks' } as const, {})
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

const pickOf = (all: Record<string, IntentPick>, intent: Intent): IntentPick =>
  all[intent.id] ?? { model: intent.model, effort: intent.effort }

async function inject($: EngineInterface, intent: Intent) {
  const pick = pickOf(await read($, picks), intent)

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
  const draft = box.text.trim()
  const started = await $.agent.spawn({
    prompt: draft.length > 0 ? `${draft}\n\n${intent.text}` : intent.text,
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
  if (draft.length > 0) await $.prompt.fill({ text: '', mode: 'replace' })
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
    // The pane opens by itself once, the first time the mod runs; after that
    // /intents opens it, and a session start or a reload leaves it alone.
    if ((await $.store.get('opened')) !== true) {
      const shown = await $.ui.open({ id: PANE, title: TITLE })
      if (shown.isPlaced) await $.store.set('opened', true)
    }

    return next(e)
  })

  on('command.run', { command: 'intents' }, async $ => {
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
    const { Box, Button, Text } = $.ui.resolve(e)
    const sub = await read($, isSub)
    const all = await read($, picks)
    const opened = await read($, open)
    const offered = await read($, models)
    // A graphical surface pads its buttons; the terminal draws a plain one
    // flush. The picker's column titles are inset to sit over their options.
    const inset = e.surface === 'terminal' ? 0 : 1

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
        {INTENTS.map((intent, index) => {
          const pick = pickOf(all, intent)
          const isOpen = opened === intent.id
          const toggle = () =>
            update($, open, (now: string | null) =>
              now === intent.id ? null : intent.id,
            )
          const set = (change: Partial<IntentPick>) =>
            update($, picks, (now: Record<string, IntentPick>) => ({
              ...now,
              [intent.id]: { ...pickOf(now, intent), ...change },
            }))

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
              <Box justifyContent="flex-end" columnGap={1}>
                {/* Two Buttons, as a desktop keeps a Button's own dimColor
                    but not a Text's inside it: the model at full strength,
                    the effort in gray. */}
                <Button
                  key={`pick-${intent.id}`}
                  label={modelLabel(pick.model)}
                  plain
                  onPress={toggle}
                />
                <Button
                  key={`pick-effort-${intent.id}`}
                  label={`${EFFORT_LABELS[pick.effort]} ${isOpen ? '▴' : '▾'}`}
                  plain
                  dimColor
                  onPress={toggle}
                />
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
                          {...(model === pick.model
                            ? { backgroundColor: TINT }
                            : {})}
                        >
                          <Button
                            key={`model-${intent.id}-${model}`}
                            plain
                            dimColor={model !== pick.model}
                            onPress={() => set({ model })}
                          >
                            {modelLabel(model)}
                            {model === pick.model ? ' ✓' : ''}
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
                          {...(effort === pick.effort
                            ? { backgroundColor: TINT }
                            : {})}
                        >
                          <Button
                            key={`effort-${intent.id}-${effort}`}
                            plain
                            dimColor={effort !== pick.effort}
                            onPress={() => set({ effort })}
                          >
                            {EFFORT_LABELS[effort]}
                            {effort === pick.effort ? ' ✓' : ''}
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
      </Box>
    )
  })
}
