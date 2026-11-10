# intent-registry

A Claude Code mod (function hooks) that adds an **Intent registry** pane: a list of reusable prompts, each with its own model and effort.

- Click an intent (or, for the first nine, press its digit while the pane has focus) to append it to the prompt box. The turn that carries it runs on the intent's model and effort.
- Turn **Run in a sub-session** on to start the intent in a background subagent instead; whatever is typed in the prompt box goes with it.
- The pane opens by itself the first time the mod runs; after that, `/intents` opens it.
- The model picker lists the models your Claude Code offers (its `/config` model choices), so new models appear without a change to the mod.

## Where intents live

Intents are read from `.claude/intents.json` in the session's working directory, so a team can commit and share them:

```json
{
  "intents": [
    {
      "id": "thorough",
      "name": "Thorough & bold",
      "text": "Be thorough in your analysis and bold in your recommendations",
      "model": "opus",
      "effort": "xhigh"
    }
  ]
}
```

- `name` and `text` are required; `id` is derived from the name when absent.
- `model` is a model alias your Claude Code offers, or `session` (the default); `effort` is one of `session`, `low`, `medium`, `high`, `xhigh`, `max`.
- Without the file, three built-in intents are shown, and the pane's first change writes them to it.
- In the pane, **+ New intent** adds one, **Edit** changes its name and prompt (and offers **Delete**, which asks for a confirmation), and the model and effort picker saves to the file.
- `/intents` reads the file again, so changes made outside the pane show. A file that does not parse is reported in the pane and never written over.

## Develop

```bash
claude plugin validate plugins/intent-registry
claude plugin test plugins/intent-registry
claude --plugin-dir plugins/intent-registry
```
