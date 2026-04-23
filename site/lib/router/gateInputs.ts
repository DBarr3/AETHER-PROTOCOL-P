// Central indirection for server-resolved gate inputs.
//
// The PolicyGate route (site/app/api/internal/router/pick/route.ts) must
// never trust opusPctMtd, uvtBalance, or activeConcurrentTasks from the
// request body — each was a Critical bypass in the red-team sweep
// (C1/C2/C3 in tests/security/redteam_policygate_report.md).
//
// Instead the route calls `resolveOpusPctMtd(userId)` etc. In production,
// boot.ts installs real Supabase-backed resolvers. In tests, the default
// resolvers return fixed fixture values that match the legacy validCtx
// defaults (0 / 1_000_000 / 0) so existing suites keep passing without
// rewriting; tests that need to exercise a specific gate trip call
// `setOpusPctMtdResolver(async () => 0.95)` (or the equivalents).

export type UserId = string;
export type GateResolver = (userId: UserId) => Promise<number>;

const DEFAULT_OPUS_PCT_MTD = 0;
const DEFAULT_UVT_BALANCE = 1_000_000;
const DEFAULT_ACTIVE_CONCURRENT_TASKS = 0;

let _opusPctMtd: GateResolver = async () => DEFAULT_OPUS_PCT_MTD;
let _uvtBalance: GateResolver = async () => DEFAULT_UVT_BALANCE;
let _activeConcurrentTasks: GateResolver = async () =>
  DEFAULT_ACTIVE_CONCURRENT_TASKS;

export function setOpusPctMtdResolver(fn: GateResolver): void {
  _opusPctMtd = fn;
}
export function setUvtBalanceResolver(fn: GateResolver): void {
  _uvtBalance = fn;
}
export function setActiveConcurrentTasksResolver(fn: GateResolver): void {
  _activeConcurrentTasks = fn;
}

export async function resolveOpusPctMtd(userId: UserId): Promise<number> {
  return _opusPctMtd(userId);
}
export async function resolveUvtBalance(userId: UserId): Promise<number> {
  return _uvtBalance(userId);
}
export async function resolveActiveConcurrentTasks(
  userId: UserId,
): Promise<number> {
  return _activeConcurrentTasks(userId);
}

// Test utility — restores the fixture-valued defaults. Callers should invoke
// this in beforeEach() so prior-test stubs do not leak.
export function resetGateInputsForTests(): void {
  _opusPctMtd = async () => DEFAULT_OPUS_PCT_MTD;
  _uvtBalance = async () => DEFAULT_UVT_BALANCE;
  _activeConcurrentTasks = async () => DEFAULT_ACTIVE_CONCURRENT_TASKS;
}

// Exposed so the production-boot regression test can assert that boot
// actually swapped the resolvers away from the test defaults.
export function getDefaultOpusPctMtdForTests(): number {
  return DEFAULT_OPUS_PCT_MTD;
}
export function getDefaultUvtBalanceForTests(): number {
  return DEFAULT_UVT_BALANCE;
}
export function getDefaultActiveConcurrentTasksForTests(): number {
  return DEFAULT_ACTIVE_CONCURRENT_TASKS;
}
