export const UVT_WEIGHTS_V1 = Object.freeze({
  version: 1,
  w_in: 1.0,
  w_out: 4.0,
  w_think: 5.0,
  w_cached_in: 0.1,
  w_subagent_fixed: 250,
  w_tool: 50,
});

export const MODEL_MULTIPLIERS_V1: Readonly<Record<string, number>> =
  Object.freeze({
    "claude-haiku-4": 0.25,
    "claude-sonnet-4": 1.0,
    "claude-opus-4": 5.0,
    "gpt-5-mini": 0.3,
    "gpt-5": 1.2,
    "perplexity-sonar": 0.4,
  });
