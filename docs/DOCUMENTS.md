# Preventivi, pro forma, DDT, fatture e note di credito

Cinque documenti accompagnano una vendita, e solo due sono fiscali.

```
Quote ──► ProForma ──► Invoice ──► credit_note_for(invoice)
  │                      ▲
  └──► DeliveryNote ─────┘   deferred_invoice([ddt, ddt, …])      (TD24)
```

| Documento | Classe | Fiscale | Va a SdI / Peppol | Stato iniziale |
|---|---|---|---|---|
| Preventivo | `Quote` | no | **mai** | `draft` |
| Fattura pro forma | `ProForma` | no | **mai** | `issued` |
| Documento di trasporto (DDT) | `DeliveryNote` | no | **mai** | `issued` |
| Fattura (TD01, TD24 differita, …) | `Invoice` | sì | sì | — (lo dà SdI) |
| Nota di credito (TD04) | `Invoice` con `DocumentType.CREDIT_NOTE` | sì | sì | — (lo dà SdI) |

## Perché tipi separati e non un `Invoice` con un flag

Preventivo e pro forma hanno quasi tutti i campi di una fattura, e il duck
typing li renderebbe volentieri. Ma **una pro forma trasmessa per errore è una
fattura**: SdI la accetta, entra nei registri del cliente, e annullarla richiede
una nota di credito. Per questo ogni renderer fiscale (`build_fattura_xml`,
`build_ubl_xml`, `build_cii_xml`, `get_renderer(...).render`) rifiuta con
`RenderError` tutto ciò che non è un `Invoice`, prima di scrivere un byte:

```python
build_fattura_xml(proforma)
# RenderError: FatturaPA: rappresenta solo fatture e note di credito, non un
# documento 'proforma'. Una pro forma o un preventivo si convertono prima in
# fattura (to_invoice), un DDT si fattura con deferred_invoice().
```

## Stessi totali, per costruzione

`Quote`, `ProForma` e `Invoice` sommano con **lo stesso codice**
(`models._TotalsMixin`): `vat_summary()`, `taxable_total()`, `tax_total()`,
`total_document()`, `total_payable()`. Un preventivo che dice 1.220,00 e diventa
una fattura da 1.219,99 è un preventivo di cui nessuno si fida più; due
implementazioni della stessa somma finiscono sempre per divergere di un
centesimo. Preventivo e pro forma possono portare anche cassa previdenziale,
ritenuta e bollo: il preventivo di un professionista mostra il netto a pagare.

## Conversioni

Tutte restituiscono un documento **nuovo** (copia profonda: modificare la
fattura non tocca il preventivo) e **non validano**: un'offerta a un potenziale
cliente può non avere i dati fiscali che la fattura richiederà, e il posto
dove dirlo è `Invoice.validate()`, al momento dell'emissione.

```python
quote = Quote("PR-3/2026", date(2026, 9, 1), seller, buyer, lines,
              valid_until=date(2026, 9, 30), notes="Acconto del 30% alla conferma")

proforma = quote.to_proforma(number="PF-7/2026", date=date(2026, 9, 5))
invoice  = proforma.to_invoice(number="12/2026", date=date(2026, 9, 12))
ddt      = quote.to_delivery_note(number="DDT-12/2026", date=date(2026, 9, 20),
                                  transport=TransportDetails(...))
```

- **Il numero e la data sono sempre quelli nuovi.** Una fattura si numera nella
  serie delle fatture e si data quando si emette: non eredita nulla dal
  preventivo.
- Con `mention_source=True` (default) la causale cita il documento d'origine
  nella lingua del cedente: «Preventivo N. PR-3/2026 — 01/09/2026».
- Qualunque campo si può sovrascrivere per parola chiave: `to_invoice(...,
  payments=[...], recipient_code="ABCDEFG")`.
- `ProForma.document_type` dice che fattura diventerà (TD01, o TD06 per la
  parcella di un professionista); una pro forma di una nota di credito non
  esiste e `validate()` la rifiuta.
- `to_delivery_note(include_prices=True)` produce un **DDT valorizzato**:
  prezzo, aliquota e sconti di riga viaggiano con la merce, così la fattura
  differita non deve chiederli di nuovo. Lo sconto di riga non si perde per
  strada: perderlo qui sarebbe un sovrapprezzo sulla fattura.

## Il DDT (DPR 472/1996)

`DeliveryNote.validate()` pretende ciò che la norma chiede: numero e data,
generalità del cedente e del cessionario (nome e indirizzo, o un luogo di
destinazione), descrizione e quantità dei beni, e — se il trasporto è a cura del
vettore — i dati del vettore. Il resto di `TransportDetails` è quello che ogni DDT
stampato porta comunque:

| Campo | Significato | FatturaPA (fattura accompagnatoria) |
|---|---|---|
| `reason` / `reason_text` | causale del trasporto (vendita, conto visione, reso, …) | `CausaleTrasporto` |
| `by` | trasporto a cura di mittente / destinatario / vettore | — (perdita dichiarata) |
| `carrier` | vettore: denominazione, P.IVA, CF, licenza di guida | `DatiAnagraficiVettore` |
| `means` | mezzo di trasporto | `MezzoTrasporto` |
| `packages` | numero colli (1–9999) | `NumeroColli` |
| `goods_appearance` | aspetto esteriore dei beni | `Descrizione` |
| `gross_weight` / `net_weight` / `weight_unit` | pesi (fino a 9999,99) | `PesoLordo` / `PesoNetto` / `UnitaMisuraPeso` |
| `start` | data e ora di inizio trasporto | `DataOraRitiro` + `DataInizioTrasporto` |
| `freight` | porto franco / assegnato | — (perdita dichiarata) |
| `incoterm` | resa Incoterms (tre lettere) | `TipoResa` |
| `delivery_address` | luogo di destinazione | `IndirizzoResa` |

La causale del trasporto non è un'etichetta: il DDT è anche il documento che
vince la **presunzione di cessione** (DPR 441/1997) per i beni che escono dai
locali senza essere venduti — «conto visione», «riparazione», «conto
lavorazione».

Su un cedente italiano il numero del DDT è controllato contro FatturaPA
(massimo 20 caratteri ASCII), perché la fattura differita lo scriverà in
`DatiDDT/NumeroDDT`: un DDT numerato in un modo che la fattura non può citare si
scopre un mese dopo. Un reso è un DDT con causale «reso» e **quantità
positive**, non una quantità negativa.

`check()` segnala senza bloccare: trasporto iniziato prima della data del DDT
(va emesso prima dell'inizio del trasporto), cessionario senza P.IVA né codice
fiscale, vettore senza P.IVA.

## La fattura differita (art. 21 c.4 lett. a DPR 633/72)

```python
invoice = deferred_invoice([ddt_1, ddt_2, ddt_3], number="15/2026",
                           date=date(2026, 9, 30))
```

- Elenca le righe di tutti i DDT, in ordine di data, e cita ogni DDT in
  `DatiDDT` con numero, data e — quando i DDT sono più d'uno — le righe della
  fattura che copre (`RiferimentoNumeroLinea`).
- Porta con sé i riferimenti dei DDT (l'ordine del cliente → `DatiOrdineAcquisto`).
- **Rifiuta** DDT di cedenti o cessionari diversi, in valute diverse, o lo
  stesso DDT due volte.
- Le righe senza prezzo si prezzano con `pricing=lambda line: (prezzo, aliquota)`
  (o `(prezzo, aliquota, natura)`); senza, l'errore le elenca.
- `Invoice.check()` controlla la norma: `deferred_mixed_months` (DDT di mesi
  diversi nella stessa fattura), `deferred_late` (data oltre il 15 del mese
  successivo alle consegne), `deferred_before_delivery` (fattura datata prima
  dell'ultimo DDT). Sono rilievi, non errori: SdI non li controlla, e un
  documento può dover essere emesso comunque.

In UBL/CII il riferimento al DDT (BT-16) è **uno solo** (UBL-SR-03): la fattura
cita il primo; tutti restano nel modello e in FatturaPA.

## La nota di credito

```python
credit_note_for(invoice, number="NC-1/2026", date=date(2026, 10, 3))                 # tutta
credit_note_for(invoice, number="NC-2/2026", date=..., lines={1: Decimal("3")})      # 3 pezzi della riga 2
credit_note_for(invoice, number="NC-3/2026", date=..., amount=Decimal("150.00"))     # 150 € IVA inclusa
```

- **Intera**: righe, sconti di documento, cassa e ritenuta specchiati — il
  riepilogo IVA della nota è quello della fattura.
- **Per righe** (indici da 0): la merce tornata indietro; gli sconti di riga si
  riducono in proporzione alla quantità.
- **Per importo**: l'importo lordo si ripartisce sulle aliquote della fattura in
  proporzione al loro peso, una riga per aliquota, al centesimo (resto maggiore).
  Stornare tutto a un'aliquota sola è l'errore che la funzione esiste per
  evitare: su un conto di cibo al 10% e vino al 22% sposterebbe IVA da
  un'aliquota all'altra. A certe aliquote alcuni importi lordi non hanno una
  scomposizione netto+IVA esatta al centesimo: la nota dice quello che può, e il
  totale da conservare è `note.total_document()`, non l'importo chiesto.
- Su una fattura con ritenuta o cassa lo storno parziale **per importo** è
  rifiutato: l'importo da solo non dice come ripartirle. Si indicano le righe.
- Il bollo non si copia: era dovuto sulla fattura e la nota non lo rimborsa.
- La nota cita la fattura (`DatiFattureCollegate`) e non può esserle anteriore
  (SdI scarta con **00418**). Non si storna una nota di credito: per annullarla
  si emette una nuova fattura.

## Stati

`initial_status(kind)`, `next_statuses(kind, stato)`, `can_transition(...)`,
`transition(...)` (solleva `IllegalTransition` con gli stati ammessi):

| Documento | Da | A |
|---|---|---|
| Preventivo | `draft` | `sent`, `accepted`, `rejected`, `converted`, `cancelled` |
| | `sent` | `draft`, `accepted`, `rejected`, `expired`, `converted`, `cancelled` |
| | `accepted` | `converted`, `cancelled` |
| | `expired` | `sent`, `cancelled` |
| | `rejected`, `converted`, `cancelled` | — |
| Pro forma | `issued` | `converted`, `cancelled` |
| DDT | `issued` | `invoiced`, `cancelled` |

Un DDT nasce `issued`: una bolla che ha viaggiato con la merce non torna bozza.
Gli stati dei documenti fiscali li dà SdI (`InvoiceState`), non questa tabella.

La **numerazione** resta al chiamante: una sequenza senza buchi è una riga di
database con il suo lock, non qualcosa che un pacchetto senza stato può
garantire.

## JSON e PDF

`document_to_dict` / `document_from_dict` (e le varianti `_json`) scrivono e
rileggono tutti e cinque i documenti con un discriminante `"kind"`; un JSON
senza `kind` è una fattura, come ogni JSON scritto prima della 0.10.0.

`document_pdf(doc)` stampa qualunque documento (A4, 31 lingue, logo):
il preventivo con la validità e lo spazio «per accettazione»; la pro forma con
la dichiarazione che **non è una fattura**; il DDT con cedente, cessionario,
destinazione, dati del trasporto, righe (con i prezzi solo se valorizzato) e le
tre firme — conducente, vettore, destinatario; fattura e nota di credito col
proprio titolo, i riferimenti, sconti, bollo, ritenuta e netto a pagare, e la
modalità di pagamento con IBAN. Dalla riga di comando: `einvoice pdf doc.json`.

## Cosa non c'è

- **Formati elettronici per preventivo e DDT** (UBL `Quotation`,
  `DespatchAdvice` / Peppol BIS Despatch Advice): in Italia il DDT non si
  trasmette a SdI, e i canali che li usano (per esempio il nodo NSO della sanità
  pubblica) hanno regole proprie che questo pacchetto non modella.
- **La fattura semplificata** (TD07–TD09, formato FSM10): il renderer
  ordinario la rifiuta invece di produrre un file che SdI scarterebbe.
- **Le scadenze di legge dello storno** (art. 26 DPR 633/72): il termine di un
  anno vale solo per alcune cause della variazione, che il documento non dice.
