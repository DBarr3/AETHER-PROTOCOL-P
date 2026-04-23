# Observability Alerts

All alerts route to `lilbenxo@gmail.com`. Slack webhook: not configured — ask owner before adding.

---

## Vercel Alerts

Configure at: Vercel Dashboard → Project (`aethersystems`) → Observability → Alerts

> **Setup note:** The Vercel MCP connector does not expose an alert-creation endpoint.
> These must be created manually in the Vercel dashboard UI.

| # | Alert Name | Condition | Threshold | Window | Destination |
|---|---|---|---|---|---|
| V1 | 5xx Rate Spike | Error rate on `app.aethersystems.net` > 1% | 1% for 5 min | 5 min | lilbenxo@gmail.com |
| V2 | Build Failure on Main | Build fails on `main` branch push | Any failure | — | lilbenxo@gmail.com |
| V3 | Stuck Deploy | Deploy duration > 5 min | 5 min | — | lilbenxo@gmail.com |

**V1 creation steps:**
1. Vercel Dashboard → Project → Observability → Alerts → New Alert
2. Metric: `Error Rate`, Condition: `> 1%`, Duration: `5 minutes`
3. Notification: Email → `lilbenxo@gmail.com`

**V2 creation steps:**
1. New Alert → Type: `Deployment Failed`
2. Filter: Branch = `main`
3. Notification: Email → `lilbenxo@gmail.com`

**V3 creation steps:**
1. New Alert → Type: `Deployment Duration`
2. Condition: `> 5 minutes`
3. Notification: Email → `lilbenxo@gmail.com`

---

## PostHog Alerts

Configure at: PostHog → Project 386803 → Alerts (or Insights → alert icon on each saved insight)

> **Setup note:** PostHog alert creation via REST API requires a personal API key
> (not the project ingestion key). Create these manually from the PostHog UI after
> creating the dashboards in `01_dashboards.md`.

| # | Alert Name | Event/Insight | Condition | Window | Destination |
|---|---|---|---|---|---|
| P1 | Router 5xx Rate | `router_pick_request` (needs event — see dashboards) | 5xx% > 1% | 5 min | lilbenxo@gmail.com |
| P2 | Stripe Webhook Failed | `stripe_webhook_failed` (needs event — see dashboards) | Any occurrence | immediate | lilbenxo@gmail.com |
| P3 | Installer Funnel Drop | `installer_launch_clicked` → `installer_completed` (needs events) | Drop > 20% | 1 hour | lilbenxo@gmail.com |

**P1 creation steps (once router_pick_request event exists):**
1. Open Dashboard 1 → Panel 3 (5xx rate) → click bell icon → Set Alert
2. Condition: `> 1`, Frequency: `every 5 minutes`
3. Destination: Email → `lilbenxo@gmail.com`

**P2 creation steps (once stripe_webhook_failed event exists):**
1. Insights → New → Trends → Event: `stripe_webhook_failed`
2. Save insight → bell icon → Alert: `count > 0`, Frequency: `immediately`
3. Destination: Email → `lilbenxo@gmail.com`

**P3 creation steps (once installer events exist):**
1. Insights → New → Funnel → add steps `installer_launch_clicked` → `installer_completed`
2. Save → bell icon → Alert: conversion rate drops > 20% vs previous 1h window
3. Destination: Email → `lilbenxo@gmail.com`

---

## Gap Summary

| Alert | Blocker | Action Required |
|---|---|---|
| V1, V2, V3 | No Vercel MCP alert API | Create manually in Vercel Dashboard |
| P1 | `router_pick_request` event not emitted | Add PostHog capture to router/pick/route.ts |
| P2 | `stripe_webhook_failed` event not emitted | Add PostHog capture in stripe-webhook edge fn catch block |
| P3 | Installer events not emitted | Instrument installer with 13 PostHog events |
