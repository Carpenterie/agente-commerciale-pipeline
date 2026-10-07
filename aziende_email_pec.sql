-- Colonna `email_pec` su aziende (7/10): un'email commerciale non deve mai
-- partire verso una PEC. La pipeline mette le PEC qui (fetch.e_pec) e mai
-- in email_aziendale; l'app la legge ma non la modifica.

alter table public.aziende add column email_pec text;

comment on column public.aziende.email_pec is
    'PEC dell''azienda (dal sito o dai ripassi). Solo da leggere: le email '
    'commerciali NON partono mai verso questo indirizzo.';

grant select (email_pec) on public.aziende to authenticated;

-- Scrittura solo dalla pipeline (service_role). Il trigger vale qualunque
-- siano i grant di update dell'app sulla tabella: se un domani qualcuno
-- desse l'update su tutta la tabella, email_pec resterebbe comunque chiusa.
create or replace function public.aziende_email_pec_solo_pipeline()
returns trigger language plpgsql set search_path = '' as $$
begin
    if current_user in ('authenticated', 'anon')
       and ((tg_op = 'INSERT' and new.email_pec is not null)
            or (tg_op = 'UPDATE' and new.email_pec is distinct from old.email_pec)) then
        raise exception 'email_pec la scrive solo la pipeline';
    end if;
    return new;
end $$;

create trigger aziende_email_pec_solo_pipeline
    before insert or update on public.aziende
    for each row execute function public.aziende_email_pec_solo_pipeline();
