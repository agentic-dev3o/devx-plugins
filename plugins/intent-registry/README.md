# intent-registry

A Claude Code mod (function hooks) that adds an **Intent registry** pane: a list of reusable prompts, each with its own model and effort.

- Click an intent (or, for the first nine, press its digit while the pane has focus) to append it to the prompt box. The turn that carries it runs on the intent's model and effort.
- Turn **Run in a sub-session** on to start the intent in a background subagent instead; whatever is typed in the prompt box goes with it.
- The pane opens by itself the first time the mod runs; after that, `/intents` opens it.
- The model picker lists the models your Claude Code offers (its `/config` model choices), so new models appear without a change to the mod.

Intents live in the `INTENTS` list at the top of `hooks/register.tsx`.

## Develop

```bash
claude plugin validate plugins/intent-registry
claude plugin test plugins/intent-registry
claude --plugin-dir plugins/intent-registry
```
