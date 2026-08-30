-- Vista "studio del territorio" (richiesta dal cliente).
--
-- ATTENZIONE ALLA LETTURA DEL DATO: questa vista conta le aziende che LA
-- PIPELINE ha individuato e classificato, non le aziende esistenti sul
-- territorio. Non è un censimento di mercato: dipende dalle query di
-- sourcing, dai comuni interrogati e da cosa Google Maps ed Exa hanno
-- restituito quel giorno. L'etichetta viaggia INSIEME ai dati (colonna
-- `fonte_dato`) proprio perché non possa essere persa per strada.

create or replace view studio_territorio as
select
    'Aziende individuate e classificate dal sistema — non è un censimento del mercato'
        as fonte_dato,
    coalesce(nullif(trim(provincia), ''), 'non rilevata')        as provincia,
    coalesce(categoria::text, 'non classificata')                as categoria,
    classe::text                                                 as classe,
    count(*)                                                     as aziende,
    count(*) filter (where esito_analisi = 'TARGET')             as di_cui_target,
    count(*) filter (where esito_fetch = 'nessun_sito')          as di_cui_senza_sito,
    count(*) filter (where segnali @> '[{"tipo":"annuncio_lavoro"}]')
        as di_cui_con_segnale_lavoro,
    count(*) filter (where segnali @> '[{"tipo":"ex_cliente"}]') as di_cui_ex_clienti
from aziende
group by 2, 3, 4
order by 2, 3, 4;

comment on view studio_territorio is
    'Aziende individuate e classificate dalla pipeline. NON è un censimento '
    'del mercato: il totale dipende dalle query di sourcing e dai comuni '
    'interrogati. Da presentare sempre con questa dicitura.';
