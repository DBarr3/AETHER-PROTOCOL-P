export interface RouterGateErrorArgs {
  message: string;
  gateCapKey: string;
  planCapValue: number | string;
  observedValue: number | string;
}

export abstract class RouterGateError extends Error {
  abstract readonly gateType: string;
  abstract readonly httpStatus: number;
  abstract readonly userMessageCode: string;
  readonly gateCapKey: string;
  readonly planCapValue: number | string;
  readonly observedValue: number | string;

  constructor(args: RouterGateErrorArgs) {
    super(args.message);
    this.name = this.constructor.name;
    this.gateCapKey = args.gateCapKey;
    this.planCapValue = args.planCapValue;
    this.observedValue = args.observedValue;
  }
}

// PR2 — never fires on the tier×task default path in PR1; class shape frozen today.
export class FreeTierModelBlockedError extends RouterGateError {
  readonly gateType = "free_tier_model_blocked";
  readonly httpStatus = 402;
  readonly userMessageCode = "upgrade_for_model";
}

export class OpusBudgetExceededError extends RouterGateError {
  readonly gateType = "opus_budget_exceeded";
  readonly httpStatus = 402;
  readonly userMessageCode = "opus_budget_exceeded";
}

export class OutputTokensExceedCapError extends RouterGateError {
  readonly gateType = "output_tokens_exceed_cap";
  readonly httpStatus = 413;
  readonly userMessageCode = "output_tokens_exceed_plan";
}

export class ConcurrencyCapExceededError extends RouterGateError {
  readonly gateType = "concurrency_cap_exceeded";
  readonly httpStatus = 429;
  readonly userMessageCode = "concurrency_exceeded";
}

export class InsufficientUvtBalanceError extends RouterGateError {
  readonly gateType = "insufficient_uvt_balance";
  readonly httpStatus = 402;
  readonly userMessageCode = "uvt_balance_insufficient";
}
