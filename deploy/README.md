# deploy/

Operational scripts + configs for the VPS2 production deploy.

**First time on a new server?** Read [vps2-runbook.md](vps2-runbook.md). Top to bottom. Don't skip steps.

**Just shipping a code change?** SSH in and run [deploy.sh](deploy.sh). It records the current SHA, fast-forwards to `origin/main`, restarts the service, runs healthchecks, and auto-rolls-back if anything's wrong.

**Panicking about UVT specifically?** Don't bother with code rollback. SSH in, set `AETHER_UVT_ENABLED=false` in `/opt/aether/.env`, `sudo systemctl restart aether`. Three seconds. The legacy `/agent/chat` path takes over.

**Panicking about the whole release?** [rollback.sh](rollback.sh). Reverts to the SHA `deploy.sh` saved before the last deploy.

## Files

| File | What |
|---|---|
| [vps2-runbook.md](vps2-runbook.md) | The doc. Read it. |
| [aether.service](aether.service) | systemd unit for uvicorn |
| [nginx.conf](nginx.conf) | Reverse proxy + TLS + rate limits |
| [deploy.sh](deploy.sh) | One-command redeploy |
| [rollback.sh](rollback.sh) | Revert to `.last-deployed-sha` |
| [healthcheck.sh](healthcheck.sh) | Crontab probe (3 endpoints, 5s budget each) |
| [env.example](env.example) | Template for `/opt/aether/.env` — fill in every `REPLACE_ME` |

## Acceptance checks (run on a Linux box, not Windows)

```bash
# Shell scripts pass shellcheck
shellcheck deploy/*.sh

# systemd unit parses
systemd-analyze verify deploy/aether.service

# Nginx config parses (note: rate-limit zones must be in http{} of main config)
sudo nginx -t -c $(pwd)/deploy/nginx.conf
```

The Python tests covering `feature_flags` + `health_routes` + the gated UVT endpoints run on any platform:

```bash
pytest tests/test_feature_flags.py tests/test_health_routes.py tests/test_uvt_routes.py -v
```
