export class UnknownModelError extends Error {
  constructor(modelId: string) {
    super(`Unknown model_id: ${modelId}`);
    this.name = "UnknownModelError";
  }
}
