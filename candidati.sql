-- Tabella `candidati` (selezione di un geometra o architetto di cantiere),
-- separata da aziende e agenti. La riempie candidati_ricerca.py --scrivi
-- col service_role; dall'app la vedono e la modificano SOLO gli utenti con
-- app_metadata.selezione = true, e solo in stato, motivo_scarto e
-- note_selezione.
--
-- CONSERVAZIONE (privacy): chi non arriva al colloquio si cancella 90
-- giorni dopo l'ultimo aggiornamento (cron di candidati_ricerca.py
-- --conservazione). `arrivato_colloquio` lo mette il trigger e non torna
-- piu' indietro: uno scartato DOPO il colloquio non si cancella da solo.

create table public.candidati (
    id                  uuid primary key default gen_random_uuid(),
    nome                text,
    cognome             text not null,
    linkedin_url        text not null unique,
    localita            text,
    sintesi             text,
    -- [{"n": 1..17, "criterio": "...", "esito": "si|no|da_verificare",
    --   "evidenza": "frase del profilo o null"}]
    criteri             jsonb not null,
    criteri_verificati  smallint not null,
    -- zona, titolo e almeno 3 anni (criteri 2, 3 e 7): vanno in testa
    requisiti_base      boolean not null,
    aziende_segnalate   text[],
    nota_disponibilita  text,
    bozza_messaggio     text,
    stato               text not null default 'da_valutare'
        check (stato in ('da_valutare', 'da_contattare', 'contattato',
                         'colloquio', 'scartato', 'assunto')),
    motivo_scarto       text,
    note_selezione      text,
    arrivato_colloquio  boolean not null default false,
    fonte               text not null default 'exa',
    trovato_il          date not null default current_date,
    aggiornato_il       timestamptz not null default now(),
    constraint scarto_motivato
        check (stato <> 'scartato' or nullif(btrim(motivo_scarto), '') is not null)
);

create index candidati_ordine on public.candidati
    (requisiti_base desc, criteri_verificati desc);
create index candidati_conservazione on public.candidati (aggiornato_il)
    where not arrivato_colloquio;

create or replace function public.candidati_aggiorna()
returns trigger language plpgsql set search_path = '' as $$
begin
    new.aggiornato_il := now();
    if new.stato in ('colloquio', 'assunto')
       or (tg_op = 'UPDATE' and old.arrivato_colloquio) then
        new.arrivato_colloquio := true;
    end if;
    return new;
end $$;

create trigger candidati_aggiorna
    before insert or update on public.candidati
    for each row execute function public.candidati_aggiorna();

alter table public.candidati enable row level security;

revoke all on public.candidati from anon, authenticated;
grant all on public.candidati to service_role;
grant select on public.candidati to authenticated;
grant update (stato, motivo_scarto, note_selezione) on public.candidati to authenticated;

create policy candidati_selezione_lettura on public.candidati
    for select to authenticated
    using (coalesce((auth.jwt() -> 'app_metadata' ->> 'selezione')::boolean, false));

create policy candidati_selezione_modifica on public.candidati
    for update to authenticated
    using (coalesce((auth.jwt() -> 'app_metadata' ->> 'selezione')::boolean, false))
    with check (coalesce((auth.jwt() -> 'app_metadata' ->> 'selezione')::boolean, false));

-- L'accesso a un account si da' a parte, aggiungendo la chiave SENZA toccare
-- le altre (il ruolo resta com'e'):
--   update auth.users
--      set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb)
--                              || '{"selezione": true}'::jsonb
--    where email = '<email>';
-- Vale dal prossimo accesso (il token si rinnova al login).
