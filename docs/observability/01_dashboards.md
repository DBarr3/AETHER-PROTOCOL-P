# Observability Dashboards

PostHog project: `386803` (US Cloud — `https://us.posthog.com`)

> **Setup note:** Dashboard creation via REST API requires a PostHog personal API key
> (Settings → Personal API Keys). The project ingestion key (`NEXT_PUBLIC_POSTHOG_KEY`)
> cannot authenticate management API calls. Create dashboards manually in the PostHog UI
> using the queries below, or grant a personal API key and re-run this stream.

---

## Dashboard 1: Router Health

> **Gap:** The router (`/api/internal/router/pick`) logs decisions to the Supabase
> `routing_decisions` table and OpenTelemetry, but does **not** emit PostHog events.
> This dashboard requires adding PostHog server-side capture to the router route, or
> building a Supabase-backed Grafana panel.
>
> **Events needed (not yet emitted):**
> - `router_pick_request` — emitted on every call with `status_code`, `latency_ms`,
>   `gate_type`, `reason_code`, `chosen_model`, `tier`, `userId`
> - `router_gate_tripped` — emitted on gate rejection with `gate_type`
> - `router_rate_limited` — emitted on 429 responses

**Once events are added, create these panels:**

| # | Panel | Query (HogQL) |
|---|---|---|
| 1 | p50/p95/p99 latency (24h) | `SELECT quantile(0.50)(latency_ms), quantile(0.95)(latency_ms), quantile(0.99)(latency_ms) FROM events WHERE event = 'router_pick_request' AND timestamp > now() - INTERVAL 24 HOUR` |
| 2 | Request volume/min by status code | `SELECT toStartOfMinute(timestamp) AS t, properties.status_code, count() FROM events WHERE event = 'router_pick_request' AND timestamp > now() - INTERVAL 24 HOUR GROUP BY t, properties.status_code ORDER BY t` |
| 3 | 5xx rate % (24h) | `SELECT countIf(properties.status_code >= 500) * 100.0 / count() FROM events WHERE event = 'router_pick_request' AND timestamp > now() - INTERVAL 24 HOUR` |
| 4 | Gate trip rate by gate_type | `SELECT properties.gate_type, count() FROM events WHERE event = 'router_gate_tripped' AND timestamp > now() - INTERVAL 24 HOUR GROUP BY properties.gate_type` |
| 5 | Rate-limit rejections/min | `SELECT toStartOfMinute(timestamp) AS t, count() FROM events WHERE event = 'router_rate_limited' AND timestamp > now() - INTERVAL 24 HOUR GROUP BY t` |
| 6 | Top userIds by volume (1h) | `SELECT distinct_id, count() AS reqs FROM events WHERE event = 'router_pick_request' AND timestamp > now() - INTERVAL 1 HOUR GROUP BY distinct_id ORDER BY reqs DESC LIMIT 20` |

**Alert on panel 3:** 5xx rate > 1% for 5 consecutive minutes → email `lilbenxo@gmail.com`

**Dashboard URL:** *(to be filled after manual creation)*

---

## Dashboard 2: Stripe Lifecycle

Uses existing server-side events emitted from `aethercloud/supabase/functions/stripe-webhook/`.

> **Partial gap:** Webhook-level success/failure rates require a `stripe_webhook_failed`
> event that is not yet emitted. Add a `captureServerEvent("stripe_webhook_failed", {...})`
> call in the catch block of `stripe-webhook/index.ts`.

**Panels:**

| # | Panel | Event(s) | Query |
|---|---|---|---|
| 1 | Webhook success rate by event type | `checkout_completed`, `subscription_canceled`, `payment_failed` | Group by `properties.event_type`, count per day |
| 2 | Webhook latency p50/p95 | `checkout_completed` | `SELECT quantile(0.50)(properties.latency_ms), quantile(0.95)(properties.latency_ms) FROM events WHERE event IN ('checkout_completed','subscription_canceled','payment_failed')` |
| 3 | Webhook failures (last 20) | `stripe_webhook_failed` *(not yet emitted)* | `SELECT timestamp, properties.event_type, properties.error FROM events WHERE event = 'stripe_webhook_failed' ORDER BY timestamp DESC LIMIT 20` |
| 4 | Licenses created per day (30d) | `checkout_completed` | `SELECT toDate(timestamp) AS day, count() FROM events WHERE event = 'checkout_completed' AND timestamp > now() - INTERVAL 30 DAY GROUP BY day ORDER BY day` |
| 5 | License status transitions | `subscription_canceled`, `payment_failed` | `SELECT event, count() FROM events WHERE event IN ('subscription_canceled','payment_failed') AND timestamp > now() - INTERVAL 30 DAY GROUP BY event` |

**HogQL for panel 1 (copy into PostHog → Insights → SQL):**
```sql
SELECT
  properties.event_type AS event_type,
  count() AS count
FROM events
WHERE event IN ('checkout_completed', 'subscription_canceled', 'payment_failed')
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY event_type
ORDER BY count DESC
```

**Dashboard URL:** *(to be filled after manual creation)*

---

## Dashboard 3: Installer Funnel

> **Gap — cannot build yet:** No installer events are currently emitted to PostHog.
> The prompt spec calls for 13 event types from `installer_opened` → `installer_completed`,
> but none of these events appear in the PostHog event stream.
>
> **Events needed (not yet emitted):**
> `installer_opened`, `eula_accepted`, `install_path_selected`, `install_started`,
> `files_extracted`, `registry_written`, `desktop_shortcut_created`, `start_menu_added`,
> `first_launch_triggered`, `activation_prompted`, `activation_attempted`,
> `activation_succeeded`, `installer_completed`
>
> Once the installer (desktop-installer/ or aether-installer-v4/) emits these events,
> create a Funnel insight in PostHog UI:
> - Type: Funnel
> - Steps: all 13 events in order
> - Breakdown: none (or by OS bucket if added as a property)
> - Window: 1 hour (single install session)

**Dashboard URL:** *(to be filled after installer instrumentation)*
