/**
 * `session` keeps whatever the session already runs on; any other value is a
 * model alias the person's Claude Code offers (`opus`, `sonnet`, ...).
 */
export type IntentModel = string
export type IntentEffort = 'session' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export type IntentPick = { model: IntentModel; effort: IntentEffort }

/**
 * An intent put in the prompt box. `turnId` is null until the turn that
 * carries its text starts; only that turn runs on its model and effort.
 */
export type ArmedIntent = IntentPick & { text: string; turnId: string | null }

declare module 'claude-code' {
  interface PluginState {
    'intent-registry': {
      isSub: boolean
      picks: Record<string, IntentPick>
      armed: ArmedIntent | null
      /** The intent whose model and effort picker is open. */
      open: string | null
      subEfforts: Record<string, IntentEffort>
      /** The model aliases this Claude Code offers, read at session start. */
      models: string[]
    }
  }
}
