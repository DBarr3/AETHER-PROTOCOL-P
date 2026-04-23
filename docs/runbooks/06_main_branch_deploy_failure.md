# Runbook: Main Branch Deploy Failure

## Symptom
Red X on Vercel Deployments tab for the `main` branch push. Site may be serving stale build. PostHog `build_failure` alert fires (if wired).

## Who to Ping
- Owner: lilbenxo@gmail.com

## Diagnosis

### 1. Find the failing deployment and build logs
```sh
npx vercel ls --app aethersystems | head -20
```
Note the deployment URL/ID of the failed deploy.

```sh
npx vercel logs <deployment-url> --since 30m
```

### 2. Identify error class from build logs

| Error Pattern | Class | Fix Section |
|---|---|---|
| `Error: Cannot find module` | Build / missing dep | Section A |
| `Type error:` | TypeScript | Section B |
| `Test failed` / `exit code 1` | Test suite | Section C |
| `CERT_HAS_EXPIRED` / SSL error | Certificate | Section D |
| Build times out after 5 min | Stuck build | Section E |

### 3. Check recent commits on main
```sh
git log origin/main --oneline -10
```
Identify the commit that triggered the failure.

## Fixes by Error Class

### Section A: Missing dependency
```sh
cd site && npm install <missing-package>
git add site/package.json site/package-lock.json
git commit -m "fix: add missing dependency <package>"
git push origin main
```

### Section B: TypeScript error
```sh
cd site && npx tsc --noEmit 2>&1 | head -50
```
Fix the type error, commit, push.

### Section C: Test suite failure
```sh
cd site && npm test 2>&1 | tail -50
```
Fix failing tests or revert the offending commit:
```sh
git revert HEAD --no-edit
git push origin main
```

### Section D: Certificate error
Contact Vercel support — certificate issues are usually platform-side. Check https://vercel-status.com.

### Section E: Stuck build (> 5 min)
```sh
# Cancel the stuck deployment
npx vercel cancel <deployment-id>
# Retry without build cache
npx vercel --prod --force
```

## Mitigation (Stop the Bleeding)
Previous successful deployment is still serving traffic. No rollback needed unless the broken commit made it to production (rare — Vercel only promotes on success).

To manually promote the last good deployment:
```sh
npx vercel promote <last-good-deployment-url> --scope <team>
```

## Recovery
1. Fix the root cause (see Fixes by Error Class)
2. Push fix to main
3. Verify Vercel dashboard shows green deploy
4. Confirm site loads at https://aethersystems.net

## Post-Incident
- Add the error pattern to CI checks if not already caught
- If TypeScript error slipped through: verify `tsc --noEmit` is in CI
