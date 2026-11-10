/**
 * `session` keeps whatever the session already runs on; any other value is a
 * model alias the person's Claude Code offers (`opus`, `sonnet`, ...).
 */
export type IntentModel = string
export type IntentEffort = 'session' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export type IntentPick = { model: IntentModel; effort: IntentEffort }

/** One entry of the registry, as `.claude/intents.json` holds it. */
export type Intent = IntentPick & { id: string; name: string; text: string }

/**
 * The intent being written in the pane: `id` null for a new one.
 * `isDeleting` once Delete was pressed and waits for its confirmation.
 */
export type IntentDraft = {
  id: string | null
  name: string
  text: string
  isDeleting: boolean
}

/**
 * An intent put in the prompt box. `turnId` is null until the turn that
 * carries its text starts; only that turn runs on its model and effort.
 */
export type ArmedIntent = IntentPick & { text: string; turnId: string | null }

declare module 'claude-code' {
  interface PluginState {
    'intent-registry': {
      isSub: boolean
      /** The registry: the file's intents, or the built-in ones without it. */
      intents: Intent[]
      /** Why `.claude/intents.json` could not be read; the pane then won't write it. */
      fileError: string | null
      /** Whether the registry comes from `.claude/intents.json`. */
      isFromFile: boolean
      draft: IntentDraft | null
      armed: ArmedIntent | null
      /** The intent whose model and effort picker is open. */
      open: string | null
      subEfforts: Record<string, IntentEffort>
      /** The model aliases this Claude Code offers, read at session start. */
      models: string[]
    }
  }
}
