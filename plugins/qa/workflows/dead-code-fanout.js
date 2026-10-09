export const meta = {
  name: 'dead-code-fanout',
  description: 'Run the dead-code-fixer Haiku agents over ledger units: scanners, lens verifiers, or removers',
  whenToUse: 'Launched by the devx-qa:dead-code-fixer skill with the args `ledger.py dispatch` prints. Invoked bare it runs nothing: use /devx-qa:dead-code-fixer instead.',
  phases: [
    { title: 'Scan', detail: 'one Haiku scanner per shard of source files', model: 'haiku' },
    { title: 'Verify', detail: 'one Haiku verifier per batch of candidates, through one lens', model: 'haiku' },
    { title: 'Remove', detail: 'one Haiku remover per unit of confirmed-dead code', model: 'haiku' },
  ],
}

// The ledger script owns every decision: which units exist, what they contain,
// and how their outputs are tallied. This script only fans the units out.
// Model and effort repeat the agents' frontmatter so a session at a higher tier never leaks into them.
const STAGES = {
  scan: { phase: 'Scan', agentType: 'devx-qa:dead-code-scanner', model: 'haiku', effort: 'medium' },
  verify: { phase: 'Verify', agentType: 'devx-qa:dead-code-verifier', model: 'haiku', effort: 'high' },
  remove: { phase: 'Remove', agentType: 'devx-qa:dead-code-remover', model: 'haiku', effort: 'medium' },
}

const RECEIPT = {
  type: 'object',
  required: ['unit', 'status', 'items'],
  properties: {
    unit: { type: 'string' },
    status: { type: 'string', enum: ['done', 'partial', 'failed'] },
    items: { type: 'integer' },
    note: { type: 'string' },
  },
  additionalProperties: false,
}

let input = args
if (typeof input === 'string') {
  try {
    input = JSON.parse(input)
  } catch {
    input = null
  }
}
const stage = input && STAGES[input.stage]
const units = input && Array.isArray(input.units)
  ? input.units.filter(u => typeof u === 'string' && /^[svr][0-9]+$/.test(u))
  : []

if (!stage || typeof input.ledger !== 'string' || units.length === 0) {
  log('dead-code-fanout needs the args `ledger.py dispatch` prints; nothing ran')
  return {
    started: false,
    next: 'Run /devx-qa:dead-code-fixer: it prepares the units and launches this workflow.',
  }
}

phase(stage.phase)
log(`${units.length} ${input.stage} unit(s), one Haiku agent each`)

const receipts = await parallel(units.map(unit => () =>
  agent(
    `Your work unit is ${input.ledger}/units/${unit}.json. Read it first: it holds the repository root, ` +
    `your inputs, and the exact output path. Do what your instructions say for this unit, write the ` +
    `output file, then return your receipt.`,
    { label: `${input.stage}:${unit}`, phase: stage.phase, agentType: stage.agentType, model: stage.model,
      effort: stage.effort, schema: RECEIPT },
  )))

const failed = units.filter((unit, i) => !receipts[i] || receipts[i].status === 'failed')
if (failed.length) log(`no usable receipt from ${failed.join(', ')}; ingest sends them back for another try`)

return {
  started: true,
  stage: input.stage,
  units: units.length,
  done: receipts.filter(r => r && r.status === 'done').length,
  partial: receipts.filter(r => r && r.status === 'partial').map(r => r.unit),
  failed,
  next: `ledger.py ingest ${input.stage}`,
}
