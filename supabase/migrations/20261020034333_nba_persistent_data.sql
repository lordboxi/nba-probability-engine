-- Private Streamlit server only. No browser/anon/authenticated access to owner data.
begin;
create table if not exists public.nba_snapshots (
    workspace text not null,
    identity text not null check (identity ~ '^[a-f0-9]{64}$'),
    resource text not null check (resource in ('teams', 'roster', 'players')),
    season text not null,
    season_type text not null default '',
    team_id text not null default '',
    observed timestamptz not null,
    payload text not null check (jsonb_typeof(payload::jsonb) = 'object'),
    primary key (workspace, identity)
);
create index if not exists nba_snapshots_lookup on public.nba_snapshots
    (workspace, resource, season, season_type, team_id, observed desc, identity desc);

create table if not exists public.nba_forecasts (
    workspace text not null,
    identity text not null check (identity ~ '^[a-f0-9]{64}$'),
    game_id text not null,
    tipoff timestamptz not null,
    as_of timestamptz not null,
    issued_at timestamptz not null default clock_timestamp(),
    home_team text not null,
    away_team text not null,
    payload text not null check (jsonb_typeof(payload::jsonb) = 'object'),
    primary key (workspace, identity),
    check (as_of < tipoff),
    check (home_team <> away_team)
);
create index if not exists nba_forecasts_history on public.nba_forecasts (workspace, as_of, identity);
create index if not exists nba_forecasts_game on public.nba_forecasts (workspace, game_id);

create table if not exists public.nba_outcomes (
    workspace text not null,
    game_id text not null,
    recorded_at timestamptz not null,
    home_points integer not null check (home_points >= 0),
    away_points integer not null check (away_points >= 0),
    primary key (workspace, game_id, recorded_at),
    check (home_points <> away_points)
);
create index if not exists nba_outcomes_history on public.nba_outcomes (workspace, recorded_at, game_id);

alter table public.nba_snapshots enable row level security;
alter table public.nba_forecasts enable row level security;
alter table public.nba_outcomes enable row level security;

revoke all on public.nba_snapshots, public.nba_forecasts, public.nba_outcomes
    from public, anon, authenticated, service_role;
grant select, insert on public.nba_snapshots, public.nba_forecasts, public.nba_outcomes
    to service_role;
-- No permissive RLS policies: only the trusted server's service role can access these.
-- App inserts use ON CONFLICT DO NOTHING. Normal API users cannot update/delete records.
commit;
