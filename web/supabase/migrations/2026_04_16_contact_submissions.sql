-- contact_submissions table for the central contact page
-- Captures every inbound lead across AetherSecurity / AetherProtocol / AetherCloud
-- RLS: reads locked to service_role, inserts from anon (edge function is the real gate)

create extension if not exists "pgcrypto";

create type contact_intent as enum (
  'sales',
  'support',
  'security',
  'press',
  'beta',
  'careers',
  'general'
);

create type contact_product as enum (
  'aether_security',
  'aether_protocol',
  'aether_cloud',
  'site_wide'
);

create table if not exists public.contact_submissions (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  intent        contact_intent not null default 'general',
  product       contact_product not null default 'site_wide',
  name          text not null check (char_length(name) between 1 and 120),
  email         text not null check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  company       text check (char_length(company) <= 160),
  role          text check (char_length(role) <= 120),
  message       text not null check (char_length(message) between 10 and 4000),

  -- Context captured automatically
  source_path   text,
  source_cta    text,
  utm           jsonb default '{}'::jsonb,
  user_agent    text,

  -- Lifecycle
  status        text not null default 'new'
                check (status in ('new','triaged','responded','closed','spam')),
  assigned_to   text,
  triaged_at    timestamptz,
  responded_at  timestamptz,

  -- Anti-abuse
  ip_hash       text,
  honeypot      text
);

create index if not exists idx_contact_created on public.contact_submissions(created_at desc);
create index if not exists idx_contact_status  on public.contact_submissions(status) where status <> 'closed';
create index if not exists idx_contact_intent  on public.contact_submissions(intent);

alter table public.contact_submissions enable row level security;

create policy "service_role_reads"
  on public.contact_submissions for select
  to service_role
  using (true);

create policy "anon_can_insert"
  on public.contact_submissions for insert
  to anon
  with check (
    honeypot is null
    and char_length(message) >= 10
    and email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'
  );

create policy "service_role_updates"
  on public.contact_submissions for update
  to service_role
  using (true);

create or replace view public.contact_inbox as
  select id, created_at, intent, product, name, email, company, role, message, source_path, status
  from public.contact_submissions
  where status in ('new','triaged')
  order by created_at desc
  limit 200;
