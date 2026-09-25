# Schemi ufficiali FatturaPA — solo per i test

Copie non modificate degli schemi con cui SdI controlla il formato del file
(scarto `00200 — file non conforme al formato`). Servono a
`tests/test_fatturapa_schema.py`: prima di questi, il renderer era provato solo
contro il proprio parser, e un errore commesso da entrambi — `DatiDDT` scritto
come un ordine d'acquisto — passava ogni test mentre SdI avrebbe scartato il file.

| File | Fonte | Scaricato |
|---|---|---|
| `Schema_VFPR12_v1.2.3.xsd` | Agenzia delle Entrate, *Specifiche tecniche versione 1.9* — https://www.agenziaentrate.gov.it/portale/specifiche-tecniche-versione-1.9 | 2026-09-25 |
| `xmldsig-core-schema.xsd` | W3C — https://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd | 2026-09-25 |

Lo schema FatturaPA importa quello della firma da un URL remoto: il test
riscrive quell'import verso la copia locale **in memoria**, così i file restano
identici agli originali e i test non vanno in rete.

Quando esce una nuova versione delle specifiche: sostituire il file, aggiornare
la tabella e far girare `pytest tests/test_fatturapa_schema.py`.
