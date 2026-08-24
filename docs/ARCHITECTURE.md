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
├── lifecycle.py     Lifecycle (state machine) + LifecycleEvent + Notification
├── naming.py        sdi_filename / to_base36
├── formats/         base.py (InvoiceRenderer + registry) · fatturapa.py · ubl.py
├── transport/       base.py (Transport + Signer/ArchiveStore + Notification norm.)
│                    file_export.py · fattureincloud.py · aruba.py · zucchetti.py
│                    peppol.py · registry.py
└── engine.py        EInvoiceEngine + EngineResult
```

## Europa: EN 16931, PEPPOL, CIUS

- **EN 16931** = modello dati semantico comune europeo → è la base del nostro
  `Invoice` e del renderer `ubl`.
- **Sintassi**: UBL 2.1 (implementato) e UN/CEFACT CII (estensione). Factur-X /
  ZUGFeRD = CII dentro un PDF/A-3; XRechnung = CIUS in UBL o CII.
- **PEPPOL** = rete di trasporto (Access Point) → `PeppolTransport`.
- **CIUS** = regole nazionali aggiuntive → sottoclassi sottili del renderer UBL
  (es. `customization` diverso per XRechnung).

## Roadmap di prodotto (allineata alle fasi consigliate)

1. **IT via provider** — `fatturapa` + transport `aruba`/`fattureincloud`/`zucchetti` (✅).
2. **Ricezione + conservazione** — `parse_notification` per gli inbound + un
   `ArchiveStore` certificato (oggi c'è l'interfaccia + `FileArchive` per dev).
3. **PEPPOL / EN 16931** — `ubl` + `PeppolTransport` per PA e cross-border (✅ base).
4. **In-house** — porta in casa firma/AP solo se volumi/margini lo giustificano;
   l'architettura non cambia (basta un nuovo `Transport`/`Signer`).

## Punti di estensione

- **Nuovo formato** → sottoclasse `InvoiceRenderer` + `register_renderer(...)`.
- **Nuovo canale** → sottoclasse `Transport` + `register_transport(...)`.
- **Firma / conservazione** → implementa `Signer` / `ArchiveStore` e passali
  all'`EInvoiceEngine`.
- **Campi fiscali opzionali** → estendi i dataclass in `models.py` e i blocchi nel
  renderer (ordine XSD).
