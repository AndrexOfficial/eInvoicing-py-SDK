# Architettura

Motore di **e-invoicing multicanale**: un dominio fiscale unico, indipendente da
paese e canale, con due layer di adattamento intercambiabili.

## I tre livelli

```
                         EInvoiceEngine  (orchestratore)
   ┌───────────────┬──────────────────────────┬───────────────────────────┐
   │  CORE DOMAIN  │      FORMATS (render)     │     TRANSPORT (channels)  │
   ├───────────────┼──────────────────────────┼───────────────────────────┤
   │ Invoice       │ InvoiceRenderer           │ Transport                 │
   │ (EN16931)     │  ├─ FatturaPARenderer     │  ├─ FileExportTransport   │
   │ Lifecycle     │  └─ UblRenderer (Peppol)  │  ├─ FattureInCloud        │
   │ Notification  │ get_renderer("fatturapa") │  ├─ Aruba / Zucchetti     │
   │ (esiti)       │                           │  ├─ PeppolTransport (AP)  │
   │ audit trail   │ RenderedDocument(bytes)   │  └─ get_transport("aruba")│
   └───────────────┴──────────────────────────┴───────────────────────────┘
        nessuna dep            nessuna dep              httpx (opzionale)
```

1. **Core domain** — un solo modello `Invoice` (allineato a EN 16931) +
   `Lifecycle` (macchina a stati + audit + notifiche normalizzate). Non modella
   "l'Italia nel database": i campi IT (ritenuta, bollo, natura, split payment,
   regime) sono opzionali e convivono con altri paesi.
2. **Formats / renderers** — trasformano il modello nei byte di uno standard
   (FatturaPA, UBL/Peppol BIS, …). Il rendering è **separato dal trasporto**: lo
   stesso UBL può andare su PEPPOL o essere esportato su file.
3. **Transport / channels** — consegnano il documento su un canale (SdI via
   provider, PEPPOL Access Point, portale, file) e normalizzano gli esiti.
   Firma e conservazione sono pluggable (`Signer`, `ArchiveStore`).

L'**`EInvoiceEngine`** lega i tre: `validate → render → [sign] → transmit →
[archive]`, facendo avanzare la macchina a stati e registrando l'audit.

## Macchina a stati unica

```
draft → validated → [signed] → queued → sent ─┬─ delivered ─┬─ accepted ─┐
                                  │            ├─ rejected   ┘            ├─ archived
                       (failed) ──┘            └─ not_delivered ──────────┘
```

Le notifiche asincrone (RC consegna, NS scarto, MC mancata consegna, NE/EC esito,
DT decorrenza termini) sono normalizzate in `Notification` e applicate uniforme­
mente: `lifecycle.apply(notification)`. Ogni transizione è un evento immutabile
in `lifecycle.audit_trail()` — è il vero valore del modulo (audit/riconciliazione
perfetti, indipendenti dal canale).

## Mappa dei moduli

```
einvoice/
├── models.py        Invoice + Party/Address/LineItem/Payment + AllowanceCharge,
│                    WithholdingTax, DocumentReference, Attachment, BankAccount, VatSummary
├── enums.py         DocumentType, VatNature, PaymentMeans, WithholdingType,
│                    InvoiceState, NotificationType (+ map verso UNCL/EN16931)
├── money.py         helper Decimal
├── countries.py     CountryProfile + EInvoicingRegime (30 paesi) + renderer_for_country
├── taxid.py         validazione tax-id: cifra di controllo (20 paesi) o struttura
├── serde.py         JSON ⇄ Invoice (importi come stringhe, enum come codici)
├── parsing.py       XML → Invoice: rileva il formato e rilegge tutti e tre
├── cli.py           python -m einvoice / comando `einvoice`
├── lifecycle.py     Lifecycle (state machine) + LifecycleEvent + Notification
├── naming.py        sdi_filename / to_base36 / safe_filename
├── rates.py         aliquote IVA per categoria di prodotto (Allegato III)
├── reference.py     viste JSON dei dati di riferimento, per le UI di setup
├── formats/         base.py (InvoiceRenderer + registry)
│                    fatturapa.py · ubl.py · cii.py
├── transport/       base.py (Transport + Signer/ArchiveStore + Notification norm.)
│                    file_export.py · fattureincloud.py · aruba.py · zucchetti.py
│                    peppol.py · generic_hub.py · registry.py
│                    providers.py  65 preset di piattaforma, per categoria
├── signer.py        CAdES .p7m (opz.) · conservation.py  pacchetto di conservazione
└── engine.py        EInvoiceEngine + EngineResult
```

### Il motore va in due direzioni

I renderer scrivono, `parsing.py` rilegge. Non è simmetria per eleganza:
l'obbligo di **ricezione** (Germania 2025, Francia 2026) è vincolante quanto
quello di emissione, e un pacchetto che sa solo emettere copre metà del problema.

La regola che governa la lettura è che **i totali si ricalcolano, non si
credono**: da un documento ricevuto si estraggono le righe e si lascia che sia
`Invoice` a derivare gli importi. Importare il totale dichiarato come fatto
nasconderebbe esattamente il caso che interessa vedere — quello in cui non
coincide con le righe del fornitore stesso (`compare_declared_totals`).

### Due livelli di verifica, non uno

`Invoice.validate()` **solleva**: il documento è sbagliato e non deve partire.
`Invoice.check()` **restituisce** rilievi: il documento è valido ma sospetto —
un'aliquota che quel paese non usa, una cessione intra-UE con IVA esposta, una
scadenza anteriore alla data.

Tenerli separati è deliberato. Regimi speciali ed eccezioni locali sono troppi
per essere enumerati: trasformare un sospetto in un errore bloccherebbe fatture
legittime, e un motore che rifiuta documenti validi viene aggirato, non corretto.

### Dati di riferimento per una UI

`reference.py` non aggiunge conoscenza: rende serializzabile quella che c'è
già. Esiste perché le due piattaforme che incorporano il pacchetto stavano
mantenendo a mano, ciascuna, la propria tabella dei paesi in TypeScript —
quattro paesi contro i trenta qui, tenute allineate da un commento in cima al
file. Dati di riferimento copiati sono dati di riferimento che divergono, e una
schermata di setup che mostra l'etichetta fiscale sbagliata è sbagliata in un
modo che nessuno nota finché una fattura non viene rifiutata.

Due regole nella conversione:

- **niente `float`.** Le aliquote escono come stringhe e rientrano come
  `Decimal` identici. Un 8.1 che passa per un binario non è più 8,1.
- **`country_reference()` è stretto**, mentre `profile_for()` è permissivo
  apposta. Quella serve a non far mai fallire il rendering su un paese
  sconosciuto; questa risponde alla domanda «quali sono le regole qui», dove
  un profilo generico spacciato per quelle del Portogallo è peggio di un
  `KeyError`.
- **I valori di vocabolario viaggiano con la loro parola.** `country_reference(code,
  locale)` affianca `kind_label` a ogni aliquota e `b2b_label` / `b2g_label` al
  regime, nelle trentuno lingue di `einvoice.i18n`. L'identificatore **resta**:
  `kind` è ciò su cui il codice si dirama, `kind_label` è ciò che legge una
  persona. Prima di questo i due prodotti stampavano `super_reduced` accanto a
  etichette tradotte, e si erano poi costruiti ciascuno la propria tabella —
  la stessa divergenza che questo modulo era nato per chiudere. Un'etichetta
  che manca torna `None`, mai l'identificatore: altrimenti «non tradotto» e
  «tradotto» diventano indistinguibili.

## Europa: EN 16931, PEPPOL, CIUS

- **EN 16931** = modello dati semantico comune europeo → è la base del nostro
  `Invoice`.
- **Sintassi**: UBL 2.1 (`ubl`) **e** UN/CEFACT CII (`cii`) — entrambe
  implementate. Portano lo stesso significato ma non sono intercambiabili sul
  filo: un destinatario ne accetta una sola. Factur-X / ZUGFeRD = CII dentro un
  PDF/A-3 (qui produciamo l'XML, non il PDF).
- **PEPPOL** = rete di trasporto (Access Point) → `PeppolTransport`.
- **CIUS** = regole nazionali aggiuntive, selezionate dal profilo paese:
  `renderer_for_country(code, b2g=True)` sceglie XRechnung (DE), NLCIUS (NL) o
  CIUS-RO (RO). Mandare Peppol BIS liscio a chi si aspetta un CIUS è uno scarto.
- **Formati nazionali fuori EN 16931** — KSeF FA(2) in Polonia, Facturae in
  Spagna — non sono coperti dai renderer, e il profilo lo dichiara in
  `regime.national_format` invece di lasciarlo scoprire in produzione.

## Roadmap di prodotto (allineata alle fasi consigliate)

1. **IT via provider** — `fatturapa` + transport `aruba`/`fattureincloud`/`zucchetti` (✅).
2. **Ricezione + conservazione** — `parse_notification` per gli inbound + un
   `ArchiveStore` certificato (oggi c'è l'interfaccia + `FileArchive` per dev).
3. **PEPPOL / EN 16931** — `ubl` + `PeppolTransport` per PA e cross-border (✅).
4. **CII / Factur-X** — `cii` per Francia (Chorus Pro) e Germania (ZUGFeRD) (✅).
5. **Copertura paese** — 30 profili con validazione tax-id, aliquote e regimi (✅).
6. **Ricezione** — `parse_invoice` per i tre formati, totali ricalcolati (✅).
7. **Formati nazionali** — convertitori verso KSeF FA(2) e Facturae, dove il
   mandato non accetta EN 16931 (aperto).
8. **Factur-X completo** — embedding dell'XML in PDF/A-3 (aperto: serve un
   toolkit PDF, che romperebbe il core senza dipendenze — probabilmente un
   pacchetto separato).
9. **In-house** — porta in casa firma/AP solo se volumi/margini lo giustificano;
   l'architettura non cambia (basta un nuovo `Transport`/`Signer`).

## Punti di estensione

- **Nuovo formato** → sottoclasse `InvoiceRenderer` + `register_renderer(...)`.
- **Nuovo canale** → sottoclasse `Transport` + `register_transport(...)`.
- **Firma / conservazione** → implementa `Signer` / `ArchiveStore` e passali
  all'`EInvoiceEngine`.
- **Campi fiscali opzionali** → estendi i dataclass in `models.py` e i blocchi nel
  renderer (ordine XSD).
