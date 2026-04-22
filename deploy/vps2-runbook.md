# AetherCloud VPS2 Deploy Runbook

This is the doc you should actually read before touching production.
It covers first-time server setup, routine redeploy, the staged UVT
rollout checklist, and the "what to do when X breaks" playbook.

**tl;dr for the common cases:**
- Shipping new code: `ssh aether@vps2 && cd /opt/aether && ./deploy/deploy.sh`
- Panicking about UVT: SSH in, edit `.env`, set `AETHER_UVT_ENABLED=false`, `sudo systemctl restart aether`. That's 3 seconds. Everything else is a slower kind of panic.
- Full code rollback: `./deploy/rollback.sh`

---

## First-time setup (run ONCE per new server)

Estimated: 45 minutes of hands-on. Have `.env.example` open in another window.

### 1. Prerequisites on your laptop

```bash
# You need SSH access to the server
ssh root@<vps2-ip>

# You need a DNS record pointing at the VPS:
#   api.aethersystems.net  A  <vps2-ip>
# Verify with:
dig +short api.aethersystems.net
```

### 2. Create the `aether` system user

```bash
# On the server, as root:
adduser --system --group --home /opt/aether --shell /bin/bash aether

# Give it sudo rights JUST for systemctl restart (deploy.sh needs this):
cat >/etc/sudoers.d/aether-systemctl <<'EOF'
aether ALL=(root) NOPASSWD: /bin/systemctl restart aether, /bin/systemctl reload nginx
EOF
chmod 0440 /etc/sudoers.d/aether-systemctl
```

### 3. Install system packages

```bash
apt update
apt install -y python3.12 python3.12-venv python3-pip \
               nginx certbot python3-certbot-nginx \
               git curl jq
```

### 4. Clone the repo

```bash
su - aether
cd /opt/aether
git clone https://github.com/DBarr3/AETHER-CLOUD.git .
git checkout main

python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 5. Provision `.env`

```bash
# Still as the aether user:
cp deploy/env.example .env
chmod 600 .env
nano .env   # fill in every REPLACE_ME value from the template

# Verify perms: root + aether only
ls -la .env
#  -rw------- 1 aether aether ... .env
```

Required secrets and where to find each:

| Var | Where |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → Settings → Keys |
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | Supabase dashboard → Project `cjjcdwrnpzwlvradbros` → Settings → API |
| `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` | Stripe dashboard → Developers → API keys / Webhooks |
| `STRIPE_PRICE_AETHER_CLOUD_{SOLO,PRO,TEAM}` | Already in `env.example` — the 2026-04-21 price IDs |
| `RESEND_API_KEY` | resend.com → API Keys |
| `POSTHOG_KEY` | app.posthog.com → Project settings → API keys |

Leave `AETHER_UVT_ENABLED=false`, `AETHER_UVT_ROLLOUT_PCT=0`, `AETHER_UVT_USER_OVERRIDES=` empty on first boot. The rollout starts in step 11 below.

### 6. Create the DLQ directory

```bash
sudo mkdir -p /var/lib/aethercloud
sudo chown aether:aether /var/lib/aethercloud
sudo chmod 750 /var/lib/aethercloud
```

### 7. Run Supabase migrations

From **your laptop** (not the server), with the Supabase CLI authenticated:

```bash
cd <local-repo>
supabase db push --project-ref cjjcdwrnpzwlvradbros
```

This applies `aethercloud/supabase/migrations/*.sql`. **All migrations must be idempotent** — the current set uses `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`, so re-running is safe.

Verify:

```bash
supabase db execute --project-ref cjjcdwrnpzwlvradbros \
  "select count(*) from public.plans;"
# Expected: 4  (free, solo, pro, team)
```

### 8. Install systemd unit

```bash
sudo cp /opt/aether/deploy/aether.service /etc/systemd/system/aether.service
sudo systemctl daemon-reload
sudo systemctl enable aether
sudo systemctl start aether
# Watch it boot:
sudo journalctl -u aether -f
```

Expected output includes `UVT stack initialized (PricingGuard + Router + /agent/run)`.

Check the local liveness endpoint:

```bash
curl -s http://127.0.0.1:8000/healthz | jq
# { "ok": true, "sha": "abc1234", "uptime_s": 3.2 }
```

### 9. Install nginx + TLS

```bash
sudo cp /opt/aether/deploy/nginx.conf /etc/nginx/sites-available/aether

# Add the rate-limit zones to /etc/nginx/nginx.conf's http block — see
# the comment at the top of deploy/nginx.conf for the two limit_req_zone
# lines. Paste them between `http {` and the first `include`.
sudo nano /etc/nginx/nginx.conf

sudo ln -sf /etc/nginx/sites-available/aether /etc/nginx/sites-enabled/aether
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t   # must print "syntax is ok" + "test is successful"
sudo systemctl reload nginx
```

### 10. Obtain TLS certificate

```bash
sudo certbot --nginx -d api.aethersystems.net \
  --agree-tos --email ops@aethersystems.net --no-eff-email
# Accept the redirect-to-https prompt.

# Verify external:
curl -s https://api.aethersystems.net/healthz | jq
# same {ok:true} — but now over TLS from the public internet
```

### 11. Enable the cron healthcheck

```bash
sudo crontab -e -u aether
# Paste (replace $SLACK_WEBHOOK with your real URL or remove the pipe):
* * * * * /opt/aether/deploy/healthcheck.sh || curl -s -X POST "https://hooks.slack.com/services/REPLACE/ME" -d '{"text":"AetherCloud healthcheck failed on vps2"}'
```

### 12. You're live (UVT still off).

At this point:
- `api.aethersystems.net/healthz` → 200
- `api.aethersystems.net/agent/run` → 404 (UVT disabled — desktop falls back to `/agent/chat`)
- Everything else routes normally

Proceed to the **Rollout progression** section below for the staged UVT enable.

---

## Routine redeploy (every code push)

```bash
ssh aether@vps2
cd /opt/aether
./deploy/deploy.sh
# Then tail for 60s:
sudo journalctl -u aether -f --since "1 min ago"
```

What `deploy.sh` does:
1. `git fetch origin main`
2. Records current SHA to `.last-deployed-sha`
3. `git reset --hard origin/main`
4. `pip install -r requirements.txt` (fast — already cached)
5. `systemctl restart aether`
6. Runs `healthcheck.sh` — if it fails, auto-rollback

If it's unhappy:

```bash
./deploy/rollback.sh
```

What `rollback.sh` does: reverts to `.last-deployed-sha`, reinstalls deps, restarts. Does NOT re-run healthcheck (to avoid infinite loop).

**Supabase schema changes** are NOT applied by `deploy.sh` — see step 7 above. Run migrations separately from your laptop.

---

## Rollout progression — the staged UVT enable

**Do this across a week. Do not skip steps. Do not start on a Friday.**

### Hour 0: canary as yourself

```bash
# 1. Find your public.users.id:
supabase db execute --project-ref cjjcdwrnpzwlvradbros \
  "select id, email, tier from public.users where email = 'YOUR@EMAIL';"
# → copy the UUID

# 2. On the server, edit .env:
ssh aether@vps2
nano /opt/aether/.env
# Set:
#   AETHER_UVT_ENABLED=false
#   AETHER_UVT_ROLLOUT_PCT=0
#   AETHER_UVT_USER_OVERRIDES=YOUR-UUID:true

sudo systemctl restart aether
```

**Smoke test:**
- Open the desktop app → UVT meter droplet should render in the chatbar
- Send 5 messages → meter tube should move
- Stripe dashboard → Developers → Events — confirm no new unexpected webhook failures

If any of those don't work, **flip `AETHER_UVT_USER_OVERRIDES` back to empty** and debug.

### Day 1: 5% rollout

After 24 hours of clean journal logs (`sudo journalctl -u aether --since yesterday | grep -iE 'error|traceback'` returns nothing):

```bash
# Edit .env:
#   AETHER_UVT_ROLLOUT_PCT=5
#   AETHER_UVT_USER_OVERRIDES=   (clear it — you're in the 5% too)
# Or leave your override on; it's harmless.
sudo systemctl restart aether

# Watch denial rate:
sudo journalctl -u aether --since "1 hour ago" | grep -c "402"
sudo journalctl -u aether --since "1 hour ago" | grep -c "429"
```

**Expected denial rate**: ~10-15% for a realistic persona mix (the harness's pro-tier sample showed 84% but that was dominated by abusive users; real populations are casual-heavy).

**If denial rate > 40%**: caps are too tight OR abusive users are over-represented. Review [reports/sample-pro-25u-30d.md](../reports/sample-pro-25u-30d.md) assumptions before ramping.

### Day 3: 25% rollout

```bash
# .env:
#   AETHER_UVT_ROLLOUT_PCT=25
sudo systemctl restart aether
```

Monitor for 48 hours. Watch:
- Stripe webhook success rate (Stripe dashboard → Webhooks)
- `sudo journalctl -u aether | grep "rpc_record_usage failed"` — should be zero
- DLQ file size: `ls -la /var/lib/aethercloud/usage_dlq.jsonl` — should stay at 0 bytes

### Day 5: 100% / full enable

```bash
# Either:
#   AETHER_UVT_ROLLOUT_PCT=100
# OR (equivalent):
#   AETHER_UVT_ENABLED=true
#   AETHER_UVT_ROLLOUT_PCT=0
sudo systemctl restart aether
```

UVT is now live for everyone. The legacy `/agent/chat` path still exists — do NOT remove it for at least 90 days. It's your rollback target.

---

## When X breaks

### UVT-specific: "I want to turn this off NOW"

The fastest revert, always:

```bash
ssh aether@vps2
sudo sed -i 's/^AETHER_UVT_ENABLED=.*/AETHER_UVT_ENABLED=false/' /opt/aether/.env
sudo sed -i 's/^AETHER_UVT_ROLLOUT_PCT=.*/AETHER_UVT_ROLLOUT_PCT=0/' /opt/aether/.env
sudo systemctl restart aether
```

3 seconds. `/agent/run` returns 404, desktop falls back to `/agent/chat`, Stripe overage usage stops accumulating. No code rollback needed.

### Supabase is down

`/healthz/deep` returns 503. `/healthz` stays 200 so nginx doesn't mark the upstream down. Symptoms on users:
- `/agent/run` → 502 (Supabase query fails in PricingGuard or Router)
- Desktop meter → 5xx on `/account/usage` poll, UI shows stale cache

What to do:
1. Check Supabase status page: status.supabase.com
2. If it's us (misconfigured env), restart with corrected `SUPABASE_SERVICE_ROLE_KEY`
3. If it's them, wait. No code action needed; the DLQ catches dropped usage events and a replay job processes them when Supabase recovers.

### Stripe webhooks failing

Stripe dashboard → Webhooks → filter by failures.

Common causes:
- `STRIPE_WEBHOOK_SECRET` rotated in Stripe but not in `.env` → fix `.env`, restart
- Webhook endpoint URL wrong → in Stripe, point at `https://api.aethersystems.net/functions/v1/stripe-webhook` (note: that's the Supabase edge function, not VPS2)

The Stripe webhook lives on Supabase edge, not VPS2. VPS2 is NOT in the billing loop for subscription events — only for live UVT enforcement via `/agent/run`.

### High error rate

```bash
sudo journalctl -u aether --since "5 min ago" | grep -iE 'error|traceback' | tail -50
```

If it's UVT-pipeline errors (PricingGuard / Router / TokenAccountant), **flip the UVT flag off** (3-second fix above) and keep investigating with pressure off.

If it's pre-UVT errors (mcp-chat, project orchestration), flag-off doesn't help; use `rollback.sh`.

### DLQ growing

```bash
wc -l /var/lib/aethercloud/usage_dlq.jsonl
```

- 0 lines: nothing to do.
- <100 lines: probably a transient Supabase blip. Restart, it should drain (we don't have an auto-replay yet — Stage K).
- \>1000 lines: Supabase is persistently failing writes. Investigate `SUPABASE_SERVICE_ROLE_KEY` rotation + Supabase status. Don't delete the file — it's your only record of that usage.

### Nginx says "502 Bad Gateway"

Uvicorn isn't responding on 127.0.0.1:8000. Check:

```bash
sudo systemctl status aether
sudo journalctl -u aether -n 100
```

If the process died, systemd's `Restart=on-failure` will have tried to restart it. Check for boot-loop detection (`start-limit-hit`).

---

## Appendix A: env var reference

See [deploy/env.example](env.example) — every var documented there.

## Appendix B: file layout

```
/opt/aether/                     # repo + venv live here
├── .venv/                       # pip-managed, not in git
├── .env                         # chmod 600, aether:aether, NEVER committed
├── .last-deployed-sha           # rollback target, written by deploy.sh
├── api_server.py                # FastAPI app entry
├── lib/
│   ├── feature_flags.py         # Stage J kill switch
│   ├── health_routes.py         # Stage J /healthz family
│   ├── pricing_guard.py         # Stage E
│   ├── router.py                # Stage D
│   ├── token_accountant.py      # Stage A — only Anthropic call site
│   └── uvt_routes.py            # Stage F — /agent/run etc.
├── deploy/
│   ├── aether.service           # systemd unit
│   ├── nginx.conf               # reverse proxy + rate limits
│   ├── deploy.sh                # one-command redeploy
│   ├── rollback.sh              # panic button
│   ├── healthcheck.sh           # crontab target
│   └── env.example              # this runbook's secret-less twin
└── /var/lib/aethercloud/
    └── usage_dlq.jsonl          # dead-letter for failed rpc_record_usage
```

## Appendix C: deferred work (post-J, not blocking)

| Stage | What | When to revisit |
|---|---|---|
| B.5 | Refactor `agent/claude_agent.py` + `hardened_claude_agent.py` through TokenAccountant | After 2-4 weeks of real traffic |
| D.5 | Sub-agent dispatch with right-sizing | When a user actually asks for multi-agent orchestration |
| DLQ replay | Cron job that reads `usage_dlq.jsonl` + re-fires `rpc_record_usage` | If the DLQ ever shows >100 lines |
| Post-90d | Delete the legacy `/agent/chat` path | Only after UVT has been 100% on for 90 days with zero rollback |
