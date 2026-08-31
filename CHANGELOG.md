# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] — 2026-08-31

Il pacchetto smette di credere a quello che ha appena scritto. Le tre
correzioni di questa versione hanno la stessa forma: non falliva niente, il file
restava valido, e quello che cambiava erano i soldi o la leggibilità. Si trovano
solo facendo il giro completo — scrivi, rileggi, confronta — perché guardando
solo chi scrive sembra tutto a posto.

Insieme, il catalogo del ferro impara a dire **per che via** ci si parla con un
dispositivo e **che cosa** gli si può davvero comandare, e a nominare chi resta
fuori invece di ometterlo.

### Added

- **`einvoice.notifications`** — il lettore delle ricevute SdI. Il pacchetto
  sapeva costruire la fattura, firmarla, trasmetterla e modellarne il ciclo di
  vita, e non sapeva leggere l'unica cosa che torna indietro: ogni integrazione
  se le riparsava per conto suo, che è la duplicazione che questo pacchetto
  esiste per togliere. `parse_sdi_receipt()` riconosce tutte e sette le sigle
  (RC, NS, MC, NE, DT, AT, EC) e ne estrae identificativo SdI, nome file, data,
  esito e — su uno scarto — i **codici d'errore**, che sono il dato che fa
  ripartire il lavoro: un `00404` (duplicata) non va ritrasmesso, un `00311`
  (codice destinatario non valido) va corretto e rimandato, e sono due azioni
  opposte. `.to_notification()` la consegna al ciclo di vita esistente. Il
  namespace non si pretende, perché gli intermediari lo riscrivono e un parser
  che lo esigesse fallirebbe su file perfettamente validi.
- **`parse_invoices()`** e `parse_fattura_batch()` — un file FatturaPA può
  contenere più fatture (il **lotto**: un header solo, più
  `FatturaElettronicaBody`), ed è la forma normale delle forniture ricorrenti.
  `parse_invoices()` restituisce sempre una lista, per tutti i formati: è la
  funzione da usare quando il file arriva da fuori e non sai cosa contiene.
  Vedi *Fixed*.
- **`docs/CHOOSING.md`** — pro e contro di ogni terminale e di ogni stampante,
  più gli abbinamenti per situazione. Tenuto **fuori dal catalogo** di
  proposito: un campo `recommended` dentro una struttura dati è un'opinione
  travestita da fatto, e nessuno la aggiorna. Un documento datato dice almeno
  quando è stato scritto. Nessun prezzo: cambiano più in fretta del file, e una
  cifra vecchia è peggio di nessuna cifra.
- **`channels` — per che via ci si parla**, derivata e non dichiarata, quindi
  non può contraddire `connection`: `lan`, `bluetooth`, `usb`, `serial`, `api`,
  `webhook`, `printer_port`. `by_channel()` e `einvoice pos --channel` per
  filtrare. Un **sistema chiuso non espone nessun canale** anche se sta nel
  cloud: «raggiungibile via cloud» e «integrabile via API» non sono la stessa
  affermazione.
- **`capabilities` sui terminali** — cosa un sistema esterno può davvero fare:
  `start_payment`, `cancel`, `refund`, `status`, `webhook`. Verificate sulle
  documentazioni dei fornitori: la Cloud API di SumUp sul lettore Solo, le
  Payment Bridge API di Nexi, la Terminal API di Adyen, il callback S2S di
  Satispay (che segnala il **cambio** di stato, non lo stato: chi lo tratta da
  conferma registra un incasso che potrebbe essere annullato). `programmable`,
  `result_is_pushed`, `public_docs`, più `programmable_terminals()`,
  `drivable_devices()` e la vista `integrable_devices()` che tiene insieme i due
  mondi e **nomina chi resta fuori**. CLI `einvoice pos --integrable`.
- **I cassetti portavalori a catalogo**, con la cosa che li riguarda davvero:
  **non si integrano**. Un cassetto a impulso è una serratura che scatta quando
  arrivano 24 V sulla porta DK della stampante — nessun indirizzo, nessun
  protocollo, nessuna risposta. Non si integra il cassetto, si integra la
  stampante che lo apre, ed è per questo che `drawer` resta una capacità delle
  stampanti. `addressable` lo dichiara, `integrable_devices()` lo tiene in un
  elenco a parte per non farlo cercare fra i pilotabili, e `DEVICE_KINDS`
  separa finalmente le quattro cose che il catalogo teneva mescolate
  (`fiscal_printer`, `receipt_printer`, `security_module`, `cash_drawer`).
- **Flatpay a catalogo**, con una categoria nuova: `vendor_pos` — **sistema
  chiuso**, il terminale si comanda solo dal POS del fornitore. Non è una
  lacuna del catalogo, è il prodotto: alcuni vendono deliberatamente terminale
  e cassa come un blocco solo. Ometterlo lo farebbe ricercare alla prossima
  domanda; metterlo senza dirlo farebbe pianificare un'integrazione che non
  esiste. Un test vieta a un `vendor_pos` di dichiarare `lan` fra le
  connessioni: sono affermazioni opposte.
- **`needs_unicode_font()`**, `locales_without_font()` e
  `system_unicode_font()` — la domanda «per stampare in questa lingua mi serve
  un font, e ce n'è uno?» si può fare in configurazione invece di scoprirla
  quando il cliente chiede la copia.

### Fixed

- **Un lotto FatturaPA perdeva ogni fattura dopo la prima, in silenzio.**
  `parse_invoice()` leggeva il primo `FatturaElettronicaBody` e ignorava gli
  altri: su un flusso di fatture ricevute significa che non entrano in
  contabilità e nessuno se ne accorge — il file è valido, il parsing non
  fallisce, e mancano dei soldi. Ora `parse_invoices()` le legge tutte, e la
  versione singolare **solleva** nominando il numero di fatture trovate invece
  di troncare. Restituire la prima con un avviso sarebbe stata ancora perdita
  di dati per chiunque non legga i log.
- **Rileggere una fattura le spostava imponibile fra aliquote.** Lo
  `ScontoMaggiorazione` di documento, nello schema FatturaPA, non ha
  `AliquotaIVA`: il formato non trasporta a quale aliquota lo sconto è stato
  applicato. Rileggendo il file lo sconto restava senza aliquota e alla
  riemissione cadeva nel bucket della prima riga — cinque euro nati sull'esente
  rinascevano sul 22%, con 1,10 € di IVA inventati e il totale del documento
  cambiato. L'informazione però nel file c'è, nei `DatiRiepilogo`: la
  differenza fra l'imponibile dichiarato per aliquota e la somma delle righe
  *è* lo sconto, e ora si legge da lì. L'attribuzione avviene solo su
  corrispondenza esatta o quando un solo bucket si è mosso; nel dubbio resta
  `None`, perché un'attribuzione inventata sarebbe lo stesso spostamento di
  imponibile con l'aggravante di sembrare intenzionale.
- **Il PDF stampava punti interrogativi al posto degli alfabeti non latini.**
  Le etichette esistono in trentuno lingue e i font base di ReportLab coprono
  Latin-1: una copia di cortesia greca, russa o polacca usciva col nome del
  cliente sostituito da `???`, e non falliva niente. Ora il pacchetto **cerca
  da sé un font di sistema** quando il documento esce da Latin-1, e lo sceglie
  **per copertura, non per disponibilità**: DejaVu, che quasi ogni immagine
  Linux ha, non copre CJK né thai, e prendere il primo font trovato avrebbe
  stampato caselle vuote in giapponese — lo stesso difetto con un passaggio in
  più. `PdfBranding(font_path=…)` ha la precedenza; se nessun font disponibile
  basta si solleva `PdfFontUnavailable`, che nomina i caratteri mancanti, i
  font provati e i pacchetti da installare — **prima** di aprire la pagina,
  perché un errore a metà lascerebbe un PDF troncato. Il controllo copre anche
  i dati del chiamante, non solo le etichette: un nome cirillico su una fattura
  italiana è lo stesso problema. Quattordici lingue su trentuno stampano coi
  font base, e italiano e inglese sono fra quelle.

### Known limitations

- **L'arabo ha i glifi ma non la resa.** ReportLab non fa shaping né
  bidirezionale: le lettere escono isolate e da sinistra a destra. Il PDF non
  sbaglia i numeri, ma per un lettore arabo non è leggibile. Dichiarato invece
  che nascosto: per quel mercato conviene emettere in un'altra lingua finché
  non c'è un motore di shaping.
- **Giapponese e cinese nel PDF** richiedono `fonts-noto-cjk`, che pesa circa
  duecento megabyte: è una scelta di immagine, non un default. Senza, il
  documento solleva dicendo quale pacchetto installare.

## [0.7.0] — 2026-08-29

Il vocabolario del pacchetto smette di arrivare grezzo sugli schermi, e il
pacchetto smette di sapere solo metà di quello che un punto vendita deve
sapere.

### Added

- **`einvoice.pos`** — il punto in cui la cassa e la fattura si toccano. Un RT
  ragiona per reparti IVA e indici di pagamento, la FatturaPA per aliquote,
  `Natura` e codici `ModalitaPagamento`: nessuno dei due sa dell'altro, e
  finora il pacchetto copriva solo il secondo. Contiene la tabella
  **incasso di cassa → `ModalitaPagamento`** con il campo `exact` che dice
  quando la mappatura è un compromesso (per i buoni pasto un codice dedicato
  **non esiste**), i **reparti IVA** con i rilievi che dicono quando scontrino
  e fattura smetteranno di quadrare, e il **riferimento al documento
  commerciale** che una fattura emessa dopo lo scontrino deve citare.
  Non parla con nessuna stampante: i driver restano nel prodotto, che è
  l'unico a sapere che hardware ha in sala.
- **`einvoice.devices`** — regimi di cassa per i trenta paesi profilati: serve
  un dispositivo omologato (RT, TSE, RKSV, kasa fiskalna, …), come arrivano i
  corrispettivi, se il software va certificato, se c'è la lotteria degli
  scontrini e se il **terminale di pagamento va collegato al dispositivo**
  (Italia dal 1° gennaio 2026, Grecia già oggi). Datato da
  `FISCAL_DEVICES_VERIFIED_AS_OF`, e un paese non verificato dichiara
  `"unknown"` invece di una risposta plausibile — con un test che gli impedisce
  di portare fatti a fianco, perché un dato accanto a un'ammissione di
  ignoranza si legge come un dato.
- **`einvoice.receipt`** — il documento commerciale: righe, riepilogo IVA per
  **scorporo**, pagamenti, resto, lotteria. Rende esplicito che **una cassa e
  una fattura arrotondano in versi opposti**: sulla stessa vendita lo scontrino
  fa 46,00 (quello che il cliente paga) e la fattura 46,01, nessuno dei due
  sbaglia, e `check_receipt` misura quel centesimo invece di lasciarlo scoprire
  alla chiusura. `print_receipt` guida qualunque stampante con l'interfaccia di
  python-escpos **senza importarla** — niente dipendenze nuove, e le code page
  restano a chi le sa gestire: reimplementare ESC/POS a byte significa mojibake
  sugli accenti di un documento fiscale.
- **Lo scontrino parla la lingua del paese di fatturazione.** `country` sul
  documento, `locale` per forzarla. Sedici chiavi nuove nel catalogo (voci del
  documento, metodi di pagamento, intestazioni) nelle stesse 31 lingue: i
  metodi arrivavano sulla carta come `card` e `meal_voucher`, chiavi di
  programma in mano a un cliente.
- **`einvoice.pdf`** — `invoice_pdf()` e `receipt_pdf()`, con **logo** (percorso
  o byte) e lingua. Restituiscono byte, non scrivono file. Un logo illeggibile
  non ferma il documento, incluso il caso meno ovvio di un PNG con
  l'intestazione giusta e il flusso dati rotto, che si costruisce e fallisce al
  disegno. Lo scontrino PDF riusa le righe della termica invece di comporre un
  secondo layout. ReportLab è l'extra `[pdf]`; `PdfUnavailable` distingue «non
  installato» da «documento rotto», come `SigningUnavailable`. CLI:
  `einvoice pdf`.
- **Catalogo del ferro** in `einvoice.devices`: `FISCAL_DEVICE_MODELS` (Epson
  FP-81II/FP-90III, Custom Q3X/KUBE II, RCH, Ditron, Olivetti, le TSE tedesche
  Swissbit e fiskaly, più la famiglia ESC/POS generica) e `POS_TERMINALS`
  (Stripe, SumUp, Nexi, Adyen, Worldline, PAX, Verifone, Zettle, Satispay), con
  protocollo, collegamento, mercati e documentazione. `devices_for_country`
  non offre un RT italiano a un negozio tedesco: l'omologazione è nazionale.
  Viste `fiscal_device_catalogue` / `pos_terminal_catalogue`, CLI
  `einvoice devices --models` e `einvoice pos --terminals`.

  Il pacchetto **non parla con nessuna stampante e con nessun terminale**, e
  nessuna voce dichiara di essere implementata: sarebbe una promessa che non
  può mantenere, e chi lo incorpora la leggerebbe come propria. La famiglia
  ESC/POS è a catalogo marcata `fiscal=False`, con un test che le impedisce di
  dichiarare `receipt` fra le capacità — scambiarla per un RT è l'errore che
  costa una sanzione.
- **`country_reference()` porta `fiscal_device`**, così le schermate che già
  mostrano le regole del paese rispondono anche a «mi serve un registratore?»
  senza un secondo endpoint. Nuove viste `device_reference`,
  `all_device_references`, `pos_payment_reference`; CLI `einvoice devices
  [PAESE]` e `einvoice pos`.

- **`rate_kind.*` e `mandate.*` nel catalogo i18n**, trentuno lingue come il
  resto: `standard`, `reduced`, `super_reduced`, `parking`, `zero` e
  `mandatory`, `voluntary`, `phased`. Il vocabolario è quello della direttiva
  IVA, che è pubblicata in tutte le lingue ufficiali dell'Unione — quindi sono
  ricerche, non invenzioni.
- **`country_reference(code, locale)` e `all_country_references(locale)`**
  aggiungono `kind_label` a ogni aliquota e `b2b_label` / `b2g_label` al
  regime. Il parametro è opzionale e omesso dà inglese: la firma resta
  compatibile.

### Why

I due prodotti che incorporano il pacchetto stampavano questi valori così
com'erano: «22% · super_reduced» accanto a etichette tradotte in quattordici
lingue, «mandatory» sotto un'intestazione che diceva *Obbligo B2B*. Ognuno si
era poi costruito la propria tabella di traduzioni — che è esattamente il modo
in cui due parole polacche diverse per l'aliquota ridotta finiscono in due basi
di codice che dovrebbero concordare, com'era già successo alla tabella dei
paesi prima che esistesse `einvoice.reference`.

**L'identificatore resta accanto all'etichetta.** `kind` è ciò su cui il codice
si dirama, `kind_label` è ciò che legge una persona: sostituire il primo col
secondo era la modifica facile e quella sbagliata.

Un'etichetta assente torna `None` e non l'identificatore, perché chi consuma
deve poter distinguere «non tradotto» da «tradotto» — un'etichetta che copia la
chiave è indistinguibile da un'etichetta mancante.

## [0.6.0] — 2026-08-27

Il rilascio che riempie il buco fra «il pacchetto sa parlare con
sessantacinque piattaforme» e «una persona riesce a configurarne una».

### Added

- **`einvoice.i18n`** — catalogo di etichette in **31 lingue**: le lingue
  ufficiali dei trenta paesi profilati (UE-27 + UK + CH + US) più le locale
  d'interfaccia che i prodotti ospitanti spediscono. Un paese di cui
  dichiariamo le regole, in una lingua che i suoi contribuenti non leggono, è
  supportato a metà. `translate()`, `normalize_locale()` (`pt-BR` → `pt`, e la
  spazzatura degrada all'inglese invece di sollevare: sta dietro un query
  parameter), `locale_for_country()`.
- **`einvoice.onboarding`** — guide di configurazione per **ogni** preset:
  passi ordinati, i campi credenziali che *quella* piattaforma vuole davvero, e
  le avvertenze tenute fuori dall'elenco numerato. **Composte, non scritte**:
  ogni preset nomina una sequenza di chiavi di passo e la sequenza è derivata
  dai campi del preset, quindi una piattaforma aggiunta come voce di dizionario
  arriva con la guida completa in tutte le lingue, e la guida non può divergere
  dal preset che descrive.
- **`einvoice.formats.catalog`** — cosa *è* ogni renderer, che la chiave del
  registry non dice: sintassi sottostante, alias risolti (`zugferd` e `facturx`
  producono gli stessi byte), profili nazionali (XRechnung, NLCIUS, CIUS-RO,
  Factur-X, Chorus Pro), mime, opzioni del costruttore.
  `renderers_for_country()` **esclude** il formato nazionale di un altro paese:
  offrire FatturaPA a un cedente francese è offrire un rifiuto garantito.
- **`ProviderPreset.setup_flags`** e **`.incompatible_national_format`** — i
  fatti che nessuna tupla di credenziali rivela: credenziali a contratto,
  OAuth2, certificato qualificato; e il canale che accetta *solo* una sintassi
  nazionale che non generiamo (KSeF vuole `FA(2)`, FACe vuole
  `Facturae 3.2.x`). Il secondo era sepolto in una nota in italiano.
- **`einvoice.reference`** cresce di sei viste JSON-safe —
  `provider_reference`, `all_provider_references` (filtrabile per paese e
  categoria), `provider_kind_reference`, `renderer_reference`,
  `all_renderer_references`, `locale_reference` — così una schermata di setup
  ha un import solo.
- **CLI**: `providers <key> --setup --lang xx`, `renderers` (ora descrive
  invece di elencare, con `--country` e `--lang`), `locales`.
- **Sette piattaforme italiane in più** (65 → 72), quelle che un esercente
  incontra davvero cercando: **Fattura24**, **Libero SiFattura**, **Fattura per
  tutti**, **FatturaElettronicaAPP** sull'hub REST configurabile, con
  `base_url` a carico del chiamante come vuole la regola sugli endpoint non
  verificati; e **Agenzia delle Entrate (Fatture e Corrispettivi)**, **SdI via
  PEC**, **AssoInvoice** come *canali manuali*.
- **`ProviderPreset.manual_delivery` / `.delivery_target`** — il modo per dire
  «qui non c'è nessuna API». Tre dei canali più usati in Italia non ne hanno
  uno: vestirli da preset REST avrebbe prodotto voci che sembrano integrate e
  falliscono al primo invio, ometterli avrebbe fatto finta che il canale
  ufficiale gratuito non esista. Girano sul trasporto `file`, non chiedono
  credenziali, non mostrano il badge degli endpoint, e dichiarano l'unica cosa
  che costano in silenzio: **nessuno stato torna indietro**.
- **`label.optional`** e i campi `placeholder` / `optional_label` /
  `required` su `credential_fields()`: `base_url` è sempre presente ed è
  **facoltativo** dove l'host è noto. Ogni trasporto legge `config.base_url or
  <default>`, quindi un valore fornito è un override vero; nasconderlo faceva
  di `step.known_base_url` («lascia il campo vuoto, a meno che…») un
  riferimento a un campo che non esisteva.

### Fixed

- `einvoice renderers` stampava sei righe di cui tre alias della stessa classe,
  senza dire quali. Era esattamente la lista che i prodotti mettevano davanti a
  un operatore: «scegli un formato» significava scegliere fra due grafie di CII
  e sperare.
- La guida di KSeF non si contraddice più: dove il canale rifiuta ciò che
  generiamo, il passo «questa piattaforma vuole UBL» sparisce e resta
  l'avvertenza, che è l'affermazione vera.
- Ai portali nazionali non viene più detto di «chiedere l'attivazione delle
  API, di solito spente sui piani base»: è una frase vera su un fornitore e
  falsa su un canale statale.
- **`translate(key, locale="it")` rispondeva in inglese, in silenzio.** Il
  marcatore positional-only faceva finire `locale` dentro `**params`: nessun
  errore, nessun avviso, solo la lingua sbagliata — il peggior modo di
  sbagliare che questo modulo abbia. Ora solo `key` è posizionale, e un test
  vieta i segnaposto `{key}`/`{locale}` che riaprirebbero il buco dall'altro
  lato.
- `einvoice providers --setup` senza piattaforma stampava la tabella normale,
  facendo sembrare che la guida non avesse niente da dire. Ora è un errore
  d'uso (exit 2).

### Note

Nessuna modifica ai formati, ai profili paese o ai trasporti: il rendering, la
validazione e l'invio di 0.5.0 sono invariati byte per byte.

## [0.5.0] — 2026-08-24

The release that makes the package usable **anywhere**: the EU-27, the UK,
Switzerland and the US, in **both** EN 16931 syntaxes, reading as well as
writing, with tax identifiers that are verified rather than pattern-matched and
VAT rates that know what they apply to.

### Added

- **`inspect_p12()` + `SigningCertificate`** — read a signing certificate
  without signing anything: subject, issuer, serial, validity, and the
  questions that matter (`is_expired()`, `days_until_expiry()`,
  `expires_within(30)`). An expired certificate opens fine, signs fine, and
  the result is refused downstream, so the answer belongs at configuration
  time. Both embedding products were reaching into the private `_load_p12`
  for a worse version of this.
- **`SigningUnavailable`** — a dedicated error for "the `[signing]` extra is
  not installed", distinct from "this archive is broken". Collapsing the two
  into one `except Exception` is how a corrupt P12 gets stored as valid; that
  is exactly what both products were doing. It also inherits `RuntimeError`,
  which is what this module raised before, so existing handlers keep working.
- **`einvoice.reference`** — JSON-safe views of the reference data
  (`country_reference`, `all_country_references`, `product_categories`,
  `reference_metadata`) for platforms that expose fiscal setup in a UI. No
  `Decimal`, no `date`, and deliberately **no float**: rates travel as strings.
  Unlike `profile_for()`, which is permissive so rendering never stops,
  `country_reference()` raises on an unsupported country — a setup screen is
  *asking* what the rules are, and a generic profile presented as Portugal's is
  a wrong answer wearing the right flag.
- **Local tax-identifier labels for every country.** 26 of the 30 profiles
  said just `"VAT"`, which is not a label so much as the absence of one: a
  German operator should not have to work out that the field marked "VAT" is
  where the USt-IdNr. goes. Now `NIP`, `DIČ`, `Btw-nummer`, `ΑΦΜ`, `Adószám`,
  `CUI / CIF` and the rest — the vocabulary each country actually prints on
  its own paperwork.

- **Switzerland.** A real `CH` profile replaces the permissive generic fallback
  that accepted any string as a Swiss VAT number: CHE/UID **check-digit
  validation**, Peppol **EAS 0183** routing, CHF, the 8.1 / 3.8 / 2.6 rate set,
  and B2G/eBill/QR-bill guidance. Swiss sellers are also barred from Italian
  `Natura` codes, which describe a VAT regime Switzerland does not have.
- **CII renderer** (`cii`, aliases `facturx` / `zugferd`) — UN/CEFACT Cross
  Industry Invoice, the *other* EN 16931 syntax. This is what France's reform
  and German ZUGFeRD actually exchange, and a receiver takes one syntax or the
  other, so UBL alone could not serve them. Named Factur-X profiles
  (`minimum` … `extended`, plus XRechnung-over-CII) via `FACTURX_PROFILES`.
- **Check-digit tax-id validation** (`einvoice.taxid`) for **20 countries** —
  AT, BE, CH, DE, DK, EE, FI, FR, GB, GR, HR, HU, IE, IT, LU, PL, PT, SE, SI,
  SK. Printed forms normalize (`"CHE-116.281.710 MWST"`, `"FR 40 303 265 045"`).
  Countries without a stable public algorithm stay structural and *say so* via
  `CountryProfile.tax_id_validation` — claiming a check we do not perform would
  be worse than not performing it.
- **E-invoicing regime data** per country (`EInvoicingRegime`): network
  (SdI / Chorus / KSeF / e-Factura / Peppol / myDATA / RTIR), B2G and B2B
  status, and — the important one — `national_format`, which flags the
  countries whose mandate needs a syntax this package does **not** emit
  (Poland's FA(2), Spain's Facturae). Dated by `MANDATES_VERIFIED_AS_OF`.
- **National CIUS selection**: `renderer_for_country(code, b2g=True)` picks
  XRechnung (DE), NLCIUS (NL) or CIUS-RO (RO). Sending plain Peppol BIS where a
  CIUS is expected is a rejection, not a warning.
- **`Invoice.check()`** — non-fatal advisories, separate from `validate()`:
  implausible VAT rate for the country, intra-EU supply carrying domestic VAT,
  export carrying VAT, missing buyer VAT id, due date before issue date,
  unusual currency. Warnings must not block legitimate invoices, so these never
  raise and never fail a render.
- **Known VAT rates** per country, feeding the advisory above.
- **25 platform presets** (`einvoice.transport.providers`) — **Fiscozen**,
  Aruba, FattureInCloud, Zucchetti, InfoCert, Notartel, Wolters Kluwer, Agyo,
  Namirial, OpenAPI.it, Storecove, Pagero, Basware, Tradeshift, Unifiedpost,
  ecosio, B2Brouter, EDICOM, Sovos, Avalara, Chorus Pro, KSeF, e-Factura ANAF,
  FACe, eBill. Each states its transport, its renderer, the credentials it
  needs, and whether its endpoints are `endpoints_verified` — a preset that
  looked integrated but had never been called would be worse than none.
- `FattureInCloudXmlTransport` — uploads a pre-rendered FatturaPA instead of
  letting FIC re-derive one from a simplified payload (which silently drops
  line discounts, bollo, cassa and linked-document references).
- CLI: `check`, `providers`, and a much richer `countries` (regime, rates,
  validation strength, staleness date).
- `naming.safe_filename`, `Party.normalized_vat()`, `Party.postal_address`.
- **Inbound parsing** (`einvoice.parsing`) — `parse_invoice()` autodetects the
  format from the root element and returns a neutral `Invoice`, with dedicated
  `parse_ubl_xml` / `parse_cii_xml` / `parse_fattura_xml`. This was the missing
  half of every integration, and increasingly the mandatory half: Germany has
  required businesses to *accept* structured e-invoices since 2025-01-01 and
  France requires it of everyone from 2026 — you cannot be compliant by sending
  alone.
- **Totals are recomputed, never believed.** A parsed invoice derives its money
  from the lines exactly as an outgoing one does.
  `compare_declared_totals()` puts the supplier's stated total beside the one
  their own lines produce, so a discrepancy is visible instead of imported as
  fact.
- **40 more platform presets — 25 → 65**, filling markets that had none:
  Germany (DATEV, SEEBURGER, SAP Business Network), the Nordics (Visma,
  Maventa, Apix, InExchange, Tickstar, Logiq, OpusCapita, Nemhandel), Benelux
  (Billit, Digipoort, Exact), France (Esker, Cegid, Docaposte, Iopole,
  Pennylane, Generix), Iberia (Voxel, SERES, Saphety), Switzerland (Bexio,
  Abacus, Conextrade), plus Comarch, Coupa, Tungsten, Fonoa, Vertex, SNI,
  Qvalia, Galaxy Gateway, SmartBill and four more Italian intermediaries.
- **The registry is now navigable**: every preset declares a `kind`
  (`access_point`, `sdi_intermediary`, `national_portal`,
  `accounting_platform`, `compliance_suite`), the `countries` it serves — as a
  list, because a platform like B2Brouter covers several — and what it
  `supports` (`send` / `status` / `receive`). `providers_of_kind()` and
  `providers_for_country(..., kind=...)` filter on those.
- CLI: `parse` (received XML → JSON), `inspect` (summarise an inbound document
  and exit non-zero when its stated total contradicts its lines),
  `providers --kind` / `--kinds`.
- **The simplified document family**: `TD07` (fattura semplificata), `TD08`
  (nota di credito semplificata) and `TD09` (nota di debito semplificata) were
  missing from the code list entirely. `TD08` was the one that mattered — a
  credit note the package did not know was one, and so would not have put on
  UBL's `CreditNote` root.
- `DocumentType.is_debit_note` and `.corrects_an_earlier_document`, so the two
  kinds of correction can be told apart without matching on codes.
- Two advisories for corrections: `correction_sign` (a credit or debit note
  whose **total is negative** — the direction is carried by the document type,
  and applying it to the amounts as well produces a credit note that asks the
  customer to pay) and `correction_no_reference` (a correction with no
  `DocumentReference(kind="invoice")`, which the receiver cannot match to
  anything). Both are warnings: SdI accepts either, but neither works
  downstream.
- [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) — credit notes, debit notes and
  the two legitimate shapes of a return.
- **VAT rates by product category** (`einvoice.rates`). A country does not have
  "a VAT rate" — which applies depends on what is sold, and knowing that 4%
  exists is useless next to knowing a book goes there.
  `rate_for("IT", ProductCategory.BOOKS)` answers the question people actually
  have. `ProductCategory` follows Annex III of the VAT Directive; `RateKind`
  distinguishes standard / reduced / super-reduced / parking / **zero** — and
  zero-rated is not exempt, because it preserves the right to deduct input VAT.
- **`FiscalRules` per country**: retention years, simplified-invoice threshold,
  issuing deadline, domestic reverse charge, plus the EU-wide `EU_OSS_THRESHOLD`
  (a *combined* turnover across member states, which is the part people get
  wrong).
- **`LineItem.category`** — optional, never rendered into any format, and used
  only so `check()` can compare the rate you used against the one the country
  applies to that kind of supply (`rate_category`).
- CLI: `einvoice rates CC [--category …]` and `einvoice rules CC`.
- [`docs/TAXES.md`](docs/TAXES.md).

### Fixed

- **UBL dropped six fields it was given.** Document references
  (contract → `ContractDocumentReference`, DDT → `DespatchDocumentReference`,
  invoice → `BillingReference`), attachments, line accounting periods, line
  article codes and line exemption reasons were all accepted by the model and
  silently discarded on render. Credit notes in particular had no
  `BillingReference`, which EN 16931 BR-55 requires — the receiver could not
  tell which invoice was being undone.
- **Filenames containing the literal `"None"`.** A seller without a VAT number
  produced `GBNone_00001-ubl.xml`; a Swiss number leaked its dots and dashes
  into the name. UBL/CII now use a country-neutral `safe_filename`, and the
  FatturaPA renderer refuses to compose a name it cannot form.
- **Tax identifiers leaked their printed decoration into the XML** — spaces,
  dots and the Swiss `MWST` suffix reached `CompanyID` and `EndpointID`, where
  a receiver matches on the exact string.
- **Double country prefixes**: a party stored as `"IT01234567891"` rendered as
  `"ITIT01234567891"`, and Switzerland became `"CHCHE…"` because the UID
  already carries its own `CHE`.
- Shadowed loop variable in the FatturaPA renderer (`ln` bound to both an int
  and a `LineItem`) that produced 13 spurious type errors and hid real ones.
- The package is now **mypy-clean** (43 errors → 0) and CI enforces it rather
  than treating it as advisory — `py.typed` means a type error here is a type
  error in every downstream project.
- **CII stamped a US tax id as a VAT registration.** `SpecifiedTaxRegistration`
  carried `schemeID="VA"` regardless of jurisdiction, asserting a US seller was
  registered for a tax the United States does not levy. Non-VAT schemes now use
  `"FC"`, and the parser reads it back as the primary identifier — without
  that, a US seller's EIN vanished on the return trip.
- **The header-only Factur-X profiles emitted line items.** "BASIC WL" is
  literally *Basic Without Lines*, and MINIMUM is smaller still; declaring
  either while emitting lines produces a document that claims a profile it does
  not satisfy, which a validating receiver rejects. Both are now header-only,
  with the totals still describing the whole invoice.
- **A French VAT key of `FR` was eaten as a country prefix.** France is the only
  country whose bare number can begin with its own ISO code — the 2-character
  key is drawn from `[0-9A-HJ-NP-Z]`, which includes both letters — so
  `FR123456789` lost its key and was rejected as too short.
- **The generic country profile claimed EUR**, so an ordinary USD invoice from
  an unprofiled country raised a spurious currency advisory.
- Dead `currency` parameter on the UBL party renderer.
- **A price quoted per N units was multiplied by N.** Both syntaxes express
  wholesale pricing by pairing the amount with a base quantity
  (`cbc:BaseQuantity` / `ram:BasisQuantity`), and the parser read the amount
  while ignoring the base — "50.00 per 10" with a quantity of 10 came back as
  500.00. A tenfold error on a perfectly valid supplier document.
- **Unit prices were rendered with two decimals**, so a price of `0.123456`
  was written as `0.12` next to a line total computed from the full value. The
  result was not merely lossy but *internally inconsistent*: EN 16931 requires
  the line net amount to equal quantity × price, and a receiver recomputing it
  got a different answer. Prices now carry up to six decimals (as FatturaPA
  always did), trimmed to two when that is all they need.
- **FatturaPA was not the lossless format it claimed to be.** The renderer
  emitted ritenuta, cassa previdenziale, document discounts, attachments and
  art. 73 — and the parser threw all of them away. A FatturaPA round trip is
  now lossless, pinned by a test over every field the model has, with one
  documented exception: `ScontoMaggiorazione` has no field for the VAT rate a
  document-level charge belongs to, so that rate is assumed on the way back in.
- **FatturaPA omitted fields the format models**: `IscrizioneREA`,
  `Contatti/Email`, and the payment block's `Beneficiario`,
  `IstitutoFinanziario` and `BIC`. `RiferimentoAmministrazione` now carries
  BT-10 (BuyerReference), which had nowhere to go before.
- **UBL dropped the party's tax code** whenever a VAT number was also present —
  which is the normal case in Italy, where the codice fiscale is the identifier
  of a natural person. It also dropped the payee account holder (BT-85) and the
  servicing bank (BT-86).
- **Contact email was dropped by both EN 16931 syntaxes**, although BG-6/BG-9
  model it. That was our gap, not the standard's.
- **Non-finite amounts passed validation.** `NaN` and the infinities are valid
  `Decimal`s and arithmetically contagious: one in a line price used to yield a
  document total of `NaN`, or an `InvalidOperation` raised from inside XML
  generation — both far from the mistake that caused them. Amounts are now
  checked where they enter (`money.D`), which is the single funnel every one of
  them passes through.

### CI

- **The `core-without-extras` job was broken and had been since 0.5.0.** Its
  inline snippet used VAT numbers that stopped validating the day check-digit
  verification landed. The snippet is now `scripts/smoke_core.py` — in the
  repository, covered by the test suite, and refusing to pass when the extras
  *are* installed, so it cannot drift or pass vacuously.
- New `reference-data` job: runs the data-consistency suites and **fails when
  the tax data is over a year old**. Rates and mandates rot silently — nothing
  breaks, the answers just stop being true — so the staleness date is enforced
  rather than decorative.
- The `build` job now installs the built wheel into a clean environment and
  runs the console script, because a wheel that builds but does not install is
  a wheel nobody can use. Artifacts are uploaded.
- New `version-matches-tag` job: a tag that disagrees with `__version__` ships a
  package claiming to be something it is not.
- Least-privilege `permissions`, `concurrency` cancellation (except on main),
  pip caching, `workflow_dispatch`, ruff's GitHub annotation format.
- Added `.github/dependabot.yml` — configured never to widen the runtime
  dependency set, because the zero-dependency core is a property to defend, not
  an accident to be updated away — and a PR template.

### Changed

- **Breaking:** a seller's own VAT number must now pass its country's check
  digit. Previously any correctly-shaped string was accepted. A wrong number
  was always going to be rejected downstream by SdI or the receiving Access
  Point; it now fails locally with a clear message instead. The *buyer's*
  number remains advisory (`check()`), because you are given it and cannot
  always fix it.
- `ProviderPreset.country` is now a property over `countries`; existing call
  sites keep working, and a multi-market platform is findable from every market
  it serves.
- Author metadata is no longer tied to one host application.
- Test suite: 157 → **1640**.

## [0.4.0] — 2026-08-24

The release that makes the package usable **outside** the applications it grew
in: a portable serialization format, a command line, and the packaging metadata
a standalone distribution needs.

### Added

- **JSON serialization** (`einvoice.serde`) — `invoice_to_dict` /
  `invoice_from_dict` / `invoice_to_json` / `invoice_from_json`. One portable
  shape for the domain model, so an invoice can be a fixture, a queue payload or
  an audit record. Money is carried as strings (never floats) and enums as their
  standard codes (`TD01`, `MP05`, `N2.2`). Decode errors name the offending
  path — `lines[1].unit_price` — instead of failing generically.
- **Command line** (`python -m einvoice`, or the `einvoice` script):
  `validate`, `render`, `totals`, `normalize`, `sign`, `countries`,
  `transports`, `renderers`. Exit codes separate *invalid invoice* (`1`) from
  *invalid command* (`2`) so CI can tell a finding from a typo.
- **`GenericHubTransport`** — a REST intermediary driven entirely by
  configuration (`upload_path`, `content_field`, `auth_scheme`, …). Registered
  for **InfoCert**, **Notartel** and **Wolters Kluwer**, which previously had
  no home in the package. Its status map accepts Italian, English and raw SdI
  vocabulary (`consegnato` / `delivered` / `RC`).
- **`py.typed`** marker (PEP 561), so downstream type-checkers read the
  annotations the package already had.
- Packaging metadata for standalone distribution: trove classifiers, project
  URLs, an `all` extra, ruff + mypy configuration, MIT `LICENSE` file,
  `CONTRIBUTING.md`, CI workflow.

### Changed

- Author metadata is no longer tied to one host application.

### Notes

- No breaking changes: every 0.3.x import path still resolves.
- Test suite grew from 103 to 157 cases.

## [0.3.0]

### Added

- **Country profiles** (`einvoice.countries`) for the EU-27, the UK and the US:
  default standard per seller country, tax-id patterns (VIES VAT, GB VAT reg.,
  US EIN), tax scheme (VAT / sales tax) and per-country validation. The Italian
  constraints (RegimeFiscale, CodiceDestinatario, CAP, Natura) apply only to
  Italian sellers, so one neutral `Invoice` validates everywhere.
- **CAdES `.p7m` signing** (`einvoice.signer`) from a PKCS#12 certificate, and
  **conservation packages** (`einvoice.conservation`) — ZIP + manifest hashes +
  IPdA-like index, with a webhook upload provider.
- **UBL/Peppol BIS 3.0** renderer with a dedicated `CreditNote` root, Peppol EAS
  endpoints per country, VAT categories S/Z/E/AE/K/G/O, and the **XRechnung
  3.0** CIUS for German B2G.
- **Transport layer**: FattureInCloud, Aruba, Zucchetti, Peppol Access Point and
  file export behind one registry, with normalized statuses and notifications.
- **`EInvoiceEngine`** tying validate → render → sign → transmit → archive to a
  unified state machine with an audit trail.

## [0.2.0]

### Added

- Full FatturaPA 1.2.2 code lists: `TipoDocumento` TD01–TD28 (including the
  deferred **TD24**), `Natura` N1–N7 with post-2021 dotted sub-codes,
  `ModalitaPagamento` MP01–MP23, validated `RegimeFiscale`.
- Optional fiscal blocks: ritenuta, bollo virtuale, cassa previdenziale,
  document- and line-level discounts, article codes, accounting periods, VAT
  exigibility, document rounding, art. 73, references (order / contract / DDT /
  linked invoices), attachments.

## [0.1.0]

### Added

- Country-neutral, EN 16931-aligned `Invoice` domain model with exact `Decimal`
  money and VAT summarisation.
- FatturaPA XML builder and SdI file naming (`sdi_filename`, base-36
  progressive).
