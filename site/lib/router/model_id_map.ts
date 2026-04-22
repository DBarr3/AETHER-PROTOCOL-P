// Spec logical name → Python short key (DB enum value).
// public.usage_events.model CHECK-constrains to haiku|sonnet|opus|gpt5|gemma.
// Any writer targeting that table MUST pass chosen_model through toShortKey
// first. routing_decisions.chosen_model stores logical names (new table,
// no enum constraint) so the audit log preserves PR1 semantics as-picked.
//
// TODO PR2: add gpt-5-mini as distinct enum value; add real perplexity-sonar
// bridge (drop the gemma placeholder).

export const LOGICAL_TO_SHORT: Readonly<Record<string, string>> = Object.freeze({
  "claude-haiku-4": "haiku",
  "claude-sonnet-4": "sonnet",
  "claude-opus-4": "opus",
  "gpt-5-mini": "gpt5",
  "gpt-5": "gpt5",
  "perplexity-sonar": "gemma",
});

export function toShortKey(logical: string): string {
  const short = LOGICAL_TO_SHORT[logical];
  if (short === undefined) {
    throw new Error(`Unknown model_id: ${logical}`);
  }
  return short;
}
