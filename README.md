# einvoice

**Motore di e-invoicing multicanale, standalone e riutilizzabile.**

Un dominio fiscale pulito (modello unico + stati + notifiche + audit), separato
dai formati nazionali e dai canali di trasporto. **EN 16931 in entrambe le
sintassi** — UBL (Peppol BIS 3.0) e UN/CEFACT CII (Factur-X / ZUGFeRD / Chorus
Pro) — più **FatturaPA/SdI**, in **scrittura e in lettura**, con **profili paese
per UE-27 + Regno Unito + Svizzera + Stati Uniti** e preset per **65
piattaforme**.

## Tre livelli (mix & match)

```
        ┌──────────────────────── EInvoiceEngine ────────────────────────┐
        │  validate → render → [sign] → transmit → [archive] → state/audit│
        └─────────────────────────────────────────────────────────────────┘
core domain (no deps)        formats / renderers           transport / channels
Invoice + Lifecycle    →     fatturapa                →      file · aruba
+ 30 country profiles        ubl   (Peppol BIS,               fattureincloud[_xml]
+ tax-id checksums            XRechnung/NLCIUS/CIUS-RO)       zucchetti · peppol
+ e-invoicing regimes        cii   (Factur-X, ZUGFeRD,        hub (configurabile)
+ validate() / check()        Chorus Pro)                     25 preset piattaforma
```

| Livello | Dipendenze | Cosa fa |
|---|---|---|
| **Core** | nessuna | Modello fattura unico (EN 16931-aligned) + **30 profili paese** (UE-27/UK/CH/US: regole, aliquote note, regimi e-invoicing) + **validazione tax-id con check digit** + **macchina a stati** + notifiche normalizzate (esiti SdI/PEPPOL) + audit trail. |
| **Formats** | nessuna | **FatturaPA** (IT/SdI), **UBL** (Peppol BIS 3.0 + CIUS XRechnung/NLCIUS/CIUS-RO, sales tax US), **CII** (EN 16931 UN/CEFACT: Factur-X, ZUGFeRD, Chorus Pro). Ogni formato si **genera e si legge**. |
| **Parsing** | nessuna | `parse_invoice()` riconosce il formato dalla radice e restituisce un `Invoice` neutro; i totali vengono **ricalcolati dalle righe**, non creduti. |
| **Transport** | `httpx` (opz.) | Canali: file export, Aruba, FattureInCloud (strutturato **e** upload XML), Zucchetti, **PEPPOL Access Point**, hub REST configurabile, + **65 preset di piattaforma** (Fiscozen, DATEV, Storecove, Chorus Pro, …). |
| **Signing** | `cryptography` (opz.) | Firma **CAdES `.p7m`** (PKCS#7/CMS attached, SHA-256) da certificato PKCS#12 + pacchetto di **conservazione** (ZIP + manifest hash + indice IPdA-like). |

### Cosa è supportato

**Italia (FatturaPA 1.2.2 / SdI)** — liste codici complete: `TipoDocumento`
TD01–TD06 + TD16–TD28 (inclusa la **TD24 differita** per la ristorazione),
`Natura` N1–N7 con i sotto-codici puntati post-2021, `ModalitaPagamento`
MP01–MP23, `RegimeFiscale` validato (RF01–RF20). Blocchi: ritenuta, bollo,
**cassa previdenziale**, sconto/maggiorazione di documento **e di linea**,
codice articolo, periodo di competenza, esigibilità I/D/S, arrotondamento,
Art73, riferimento normativo nei riepiloghi, riferimenti (ordine/contratto/
DDT/fatture collegate), allegati con formato/descrizione, convenzioni per
destinatari esteri (`XXXXXXX`, CAP `00000`).

**Europa (EN 16931 / UBL Peppol BIS 3.0)** — root dedicata **CreditNote** per
le note di credito, `BuyerReference`/`OrderReference` sempre presenti
(PEPPOL-EN16931-R003), `EndpointID` con schema EAS derivato dalla P.IVA per
paese (tutta l'UE: IT 0211, DE 9930, FR 9957, … + GB 9932; Grecia con prefisso
VIES `EL` automatico), categorie IVA S/Z/E/AE/K/G/O mappate dalla `Natura` con
`TaxExemptionReason`, allowance/charge di documento e di linea, bollo e cassa
resi come charge per far quadrare BR-CO-10/13/15, `PayableRoundingAmount`,
`PaymentID` e `PaymentTerms`. **Germania B2G**: CIUS **XRechnung 3.0** via
`renderer_for_country("DE", xrechnung=True)`.

**Francia e Germania (CII / Factur-X / ZUGFeRD)** — EN 16931 ha **due** sintassi
ammesse, e un destinatario ne accetta una sola. Il renderer `cii` produce la
seconda: è quella che la riforma francese e ZUGFeRD scambiano davvero.
`renderer_for_country("FR", standard="cii")`, oppure un profilo Factur-X
esplicito (`minimum` … `extended`, e XRechnung-su-CII).

**Profili paese (`einvoice.countries`)** — un `CountryProfile` per i **27 stati
UE + UK + Svizzera + US**: standard di default del venditore, **validazione del
tax-id con check digit** dove esiste, **aliquote IVA note**, **regime di
e-invoicing** (rete, obbligo B2G/B2B, CIUS nazionale) e regole di validazione
per-paese — i vincoli italiani (RegimeFiscale, CodiceDestinatario, CAP, Natura)
si applicano SOLO ai venditori IT, quindi lo stesso `Invoice` neutro valida
anche per un venditore tedesco, britannico, svizzero o americano.

**Svizzera** — profilo `CH` completo: UID **CHE con check digit**, EAS Peppol
**0183** (l'identificativo si usa così com'è, ha già il suo prefisso `CHE`),
CHF, aliquote 8.1 / 3.8 / 2.6. Fuori dall'UE: nessuna cessione
intracomunitaria, e le `Natura` italiane sono rifiutate perché descrivono un
regime IVA che in Svizzera non esiste. B2G obbligatorio sopra CHF 5'000; il
**QR-bill è uno standard di pagamento**, non di fatturazione, e resta separato.

**Regno Unito** — fattura UBL EN 16931 con VAT GB **verificata (mod-97)**;
nessun obbligo e-invoice (MTD copre i registri IVA); Peppol via EAS 9932.

**Stati Uniti** — fattura UBL/CII in stile EN 16931 con **sales tax** (UN/ECE
5153 `STT`), EIN come identificativo (prefisso di campus verificato), nessuna
Natura IVA ammessa; pronta per l'interscambio DBNAlliance.

**Dove NON basta questo pacchetto** — e lo dice invece di implicarlo: Polonia
(KSeF vuole il formato nazionale FA(2)) e Spagna (FACe vuole Facturae 3.2.x)
richiedono sintassi che qui non generiamo. `profile_for("PL").regime.national_format`
lo dichiara, e `covered_by_this_package` è `False`. Ungheria e Grecia hanno
adempimenti di *reporting* (NAV RTIR, myDATA) separati dalla fattura.

## Installazione

```bash
pip install einvoice                # core + formats (export XML) — ZERO dipendenze
pip install "einvoice[providers]"   # + transport di rete (httpx)
pip install "einvoice[signing]"     # + firma CAdES .p7m (cryptography)
pip install "einvoice[all]"         # tutto
```

Il core è **stdlib pura**: `pip install einvoice` non tira dentro nulla, e la
CI lo verifica installando il pacchetto nudo e generando un XML con `httpx` e
`cryptography` assenti. L'installazione espone anche il comando `einvoice`.

## Uso 1 — solo XML (qualsiasi sistema)

```python
from datetime import date
from decimal import Decimal
from einvoice import Invoice, Party, Address, LineItem, build_fattura_xml, build_ubl_xml

inv = Invoice(
    number="2026/0001", date=date(2026, 6, 5),
    seller=Party(name="Trattoria da Mario", vat_number="01234567890",
                 address=Address("Via Roma 1", "20100", "Milano", "MI")),
    buyer=Party(name="ACME Srl", vat_number="09876543210",
                address=Address("Via Verdi 9", "00100", "Roma", "RM"), sdi_code="ABCDEF1"),
    lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
)
xml_it = build_fattura_xml(inv)   # FatturaPA (SdI)
xml_eu = build_ubl_xml(inv)       # UBL Peppol BIS (EN 16931)
```

## Uso 2 — profili paese (UE / UK / CH / US)

```python
from einvoice import profile_for, renderer_for_country, validate_tax_id

validate_tax_id("DE", "DE 136 695 976")      # True — check digit verificato
validate_tax_id("DE", "DE136695977")         # False — una cifra sbagliata
validate_tax_id("CH", "CHE-116.281.710 MWST")  # True — forma stampata accettata

renderer_for_country("IT")                     # FatturaPA
renderer_for_country("DE", b2g=True)           # UBL con CIUS XRechnung 3.0
renderer_for_country("NL", b2g=True)           # UBL con NLCIUS
renderer_for_country("FR", standard="cii")     # CII / Factur-X per Chorus Pro
renderer_for_country("US")                     # UBL con TaxScheme STT

ch = profile_for("CH")
ch.tax_id_validation        # "checksum"  (oppure "structural": lo dichiara)
ch.vat_rates                # ("8.1", "3.8", "2.6", "0")
ch.regime.b2g               # "mandatory"
ch.regime.covered_by_this_package   # True
```

### Aliquote per categoria di prodotto

Un paese non ha «un'aliquota»: quale si applica dipende da cosa vendi.

```python
from einvoice import ProductCategory, rate_for

rate_for("IT", ProductCategory.BOOKS)                # Decimal("4")
rate_for("DE", ProductCategory.BOOKS)                # Decimal("7")
rate_for("GB", ProductCategory.CHILDRENS_CLOTHING)   # Decimal("0")
rate_for("BG", ProductCategory.HAIRDRESSING)         # None — non lo sappiamo
```

Dichiarando `LineItem(..., category=ProductCategory.BOOKS)` — campo opzionale,
che non finisce in nessun XML — `check()` confronta l'aliquota usata con quella
del paese e segnala la discrepanza.

Le **regole non-aliquota** stanno in `profile.fiscal_rules`: anni di
conservazione, soglia della fattura semplificata, termine di emissione,
reverse charge interno. Dettagli e avvertenze in [docs/TAXES.md](docs/TAXES.md).

`Invoice.validate()` applica le regole del paese del venditore: un venditore US
o svizzero valida senza Nature/RegimeFiscale; un venditore IT resta vincolato a
tutte le regole SdI.

### Note di credito e resi

Gli importi di una nota di credito sono **positivi**: il verso lo dà il tipo
documento, non il segno. UBL mette le note di credito su una **radice separata**
(`CreditNote`, con `cac:CreditNoteLine`), e il pacchetto la sceglie da sé.

```python
Invoice(document_type=DocumentType.CREDIT_NOTE,
        lines=[LineItem("Reso 2 di 10", 2, Decimal("100"), 22)],   # positivi
        references=[DocumentReference("invoice", "FT-9", date(2026, 7, 1))], …)
```

Un reso si può anche compensare con una **riga negativa** sulla fattura
successiva — forma altrettanto valida, e non è una rettifica. Dettagli, famiglia
semplificata (`TD07`/`TD08`/`TD09`) e i due rilievi che `check()` produce:
[docs/CORRECTIONS.md](docs/CORRECTIONS.md).

### `validate()` vs `check()`

Due livelli, e la distinzione è deliberata.

```python
invoice.validate()   # solleva: il documento è SBAGLIATO
for finding in invoice.check():
    print(finding)   # non solleva: il documento è SOSPETTO
    # [intra_eu_vat] Cessione intracomunitaria DE→FR con IVA esposta su 1 riga/e…
```

`validate()` blocca ciò che rende il documento invalido. `check()` segnala ciò
che merita un occhio umano — un'aliquota che quel paese non usa (2,2 al posto di
22), una cessione intra-UE con IVA esposta, un'esportazione tassata, un
committente estero senza partita IVA, una scadenza anteriore alla data, una nota
di credito con totale negativo o senza la fattura che rettifica.
Rifiutare questi casi bloccherebbe fatture legittime, quindi `check()` non
solleva mai e non impedisce il rendering.

### Validazione dei tax-id: cosa garantiamo davvero

Il **check digit è verificato per 20 paesi** (AT BE CH DE DK EE FI FR GB GR HR
HU IE IT LU PL PT SE SI SK): un refuso viene intercettato. Per gli altri la
verifica è **strutturale** e il profilo lo dichiara —
`profile.tax_id_validation` risponde `"checksum"` o `"structural"`. Nessuno dei
due livelli prova che il numero *esista*: per quello serve una lookup VIES /
HMRC / registro UID, cioè una chiamata di rete, deliberatamente fuori da questo
pacchetto.

Ogni algoritmo è ancorato in `tests/test_taxid.py` a un numero reale e
pubblicato: **rifiutare la partita IVA di un cliente vero è molto peggio che
accettare un refuso**, e quattro di questi algoritmi erano sbagliati al primo
tentativo — quei test sono ciò che li ha smascherati.

## Uso 3 — CII / Factur-X / ZUGFeRD (Francia, Germania)

EN 16931 ammette **due** sintassi e un destinatario ne accetta una sola: chi
parla solo UBL non può servire Chorus Pro né ZUGFeRD.

```python
from einvoice import build_cii_xml
from einvoice.formats import get_renderer

xml = build_cii_xml(inv)                          # profilo EN 16931 ("COMFORT")
get_renderer("cii", profile="extended").render(inv)
get_renderer("cii", profile="xrechnung").render(inv)   # XRechnung su CII
get_renderer("zugferd").render(inv)               # alias: ZUGFeRD È CII
```

Profili in `FACTURX_PROFILES`: `minimum`, `basicwl`, `basic`, `en16931`,
`extended`, `xrechnung`. UBL e CII producono **gli stessi totali** — è una
proprietà verificata su tutti e 30 i paesi in `tests/test_all_countries.py`.

> **Limite dichiarato**: qui si genera l'**XML**. *Factur-X* propriamente detto è
> quell'XML incorporato in un PDF/A-3; l'incapsulamento richiede un toolkit PDF
> ed è un confine deliberato di questo pacchetto.

## Uso 4 — leggere una fattura ricevuta

Metà di ogni integrazione, e ormai la metà obbligatoria: la Germania impone di
**accettare** fatture strutturate dal 2025-01-01, la Francia da tutti nel 2026,
l'Italia da anni. Non si è conformi solo emettendo.

```python
from einvoice import parse_invoice, detect_standard, compare_declared_totals

detect_standard(xml)          # 'fatturapa' | 'ubl' | 'cii', dalla radice
inv = parse_invoice(xml)      # → Invoice neutro, qualunque fosse il formato
inv.seller.vat_number
inv.total_document()          # RICALCOLATO dalle righe, non letto dal documento
```

**I totali si ricalcolano, non si credono.** Un documento ricevuto dichiara i
propri totali; qui si estraggono le **righe** e si lascia che sia `Invoice` a
derivare gli importi, esattamente come per una fattura in uscita. Così una
divergenza fra quello che il fornitore afferma e quello che le sue stesse righe
producono si **vede**, invece di entrare in contabilità come un fatto:

```python
r = compare_declared_totals(xml)
if r["difference"]:
    ...   # dichiarato 9999.00, dalle righe 1220.00 → chiedere prima di pagare
```

```bash
einvoice inspect ricevuta.xml    # chi, quanto, e se torna (exit 1 se non torna)
einvoice parse   ricevuta.xml    # → JSON, riutilizzabile con validate/render
```

**Cosa sopravvive al viaggio.** Tutto ciò che EN 16931 modella: parti,
indirizzi, identificativi fiscali, righe con quantità e aliquote, sconti,
pagamenti, riferimenti, periodi. I blocchi italiani (ritenuta, cassa, bollo, e i
sotto-codici `Natura`) tornano interi solo da **FatturaPA**, che ha elementi
dedicati: attraverso UBL e CII arrivano come oneri generici, perché è tutto
quello che quelle sintassi conservano. Una perdita **dichiarata**, non
silenziosa — `N6.3` che diventa `N6.9` è documentato e testato.

## Uso 5 — piattaforme di e-invoicing (Fiscozen, DATEV, Storecove, …)

Un preset raccoglie in un posto solo trasporto, credenziali e formato di una
piattaforma:

```python
from einvoice import (transport_for_provider, preset_for,
                      providers_for_country, providers_of_kind)

t = transport_for_provider("fiscozen", api_key="…", base_url="https://…")
await t.transmit(rendered, invoice)

preset_for("fiscozen").renderer            # "fatturapa" — SdI non prende UBL
preset_for("fiscozen").endpoints_verified  # False → conferma i path sul contratto
[p.key for p in providers_for_country("IT")]
[p.key for p in providers_for_country("FR", kind="national_portal")]
[p.key for p in providers_of_kind("accounting_platform")]
```

**65 preset**, in cinque categorie (`einvoice providers --kinds`):

| Categoria | N | Esempi |
|---|---:|---|
| `access_point` | 18 | Storecove, Pagero, Tickstar, Billit, Logiq, Maventa, Qvalia, Conextrade |
| `compliance_suite` | 16 | Sovos, Avalara, Vertex, Fonoa, SNI, EDICOM, Esker, Seeburger, Voxel |
| `accounting_platform` | 13 | **DATEV**, Visma, Sage, Cegid, Pennylane, Bexio, Exact, Passepartout |
| `sdi_intermediary` | 11 | **Fiscozen**, Aruba, Fatture in Cloud, Zucchetti, InfoCert, Credemtel |
| `national_portal` | 7 | Chorus Pro (FR), KSeF (PL), e-Factura (RO), FACe (ES), Digipoort (NL), Nemhandel (DK), eBill (CH) |

Un preset dichiara anche i **mercati** che copre (più d'uno: B2Brouter serve
ES *e* IT, e si trova cercando l'uno o l'altro) e cosa **sa fare**
(`send` / `status` / `receive`).

Ogni preset dichiara `endpoints_verified`. **`True`** solo dove il flusso è
implementato su contratto pubblico e coperto dai test (oggi: Aruba, Fatture in
Cloud). Altrimenti la *forma* è giusta — questo trasporto, queste credenziali —
ma i path vanno confermati sulla documentazione del tuo account, ed è per questo
che quasi tutti chiedono `base_url`. Un preset che sembrasse integrato senza
essere mai stato chiamato sarebbe peggio di nessun preset.

## Uso 6 — motore (render + invio + stato)

```python
from einvoice import EInvoiceEngine
from einvoice.formats import get_renderer
from einvoice.transport import get_transport, TransportConfig

engine = EInvoiceEngine(
    renderer=get_renderer("fatturapa"),                 # o "ubl" per PEPPOL
    transport=get_transport("aruba", TransportConfig(   # o "peppol", "file", …
        name="aruba", username="...", password="...", sandbox=True)),
)
result = await engine.process(inv)
result.lifecycle.state            # sent / delivered / accepted / rejected …
result.lifecycle.audit_trail()    # storia immutabile per audit
```

Cambiare formato o canale = cambiare una stringa. Le notifiche asincrone (esiti)
avanzano la stessa macchina a stati: `lifecycle.apply(notification)`.

## Uso 7 — JSON e riga di comando

Il modello è il confine d'integrazione: una piattaforma ci mappa sopra le sue
tabelle. `einvoice.serde` dà a quel modello **una forma JSON portabile**, così
una fattura può essere una fixture, un payload di coda o un record di audit —
e la CLI lavora direttamente su quel formato.

```python
from einvoice import invoice_to_json, invoice_from_json

payload = invoice_to_json(inv)        # importi come stringhe, enum come codici
same = invoice_from_json(payload)     # round-trip senza perdite
```

Gli importi viaggiano come **stringhe**, mai float (`0.1 + 0.2` è esattamente
l'errore che una fattura non può contenere), e gli enum come il loro codice di
standard: `TD01`, `MP05`, `N2.2`. Gli errori di decodifica indicano il punto
esatto — `lines[1].unit_price` — invece di fallire genericamente.

```bash
einvoice validate fattura.json          # valida + stampa i totali
einvoice check fattura.json             # rilievi non bloccanti (--strict per exit 1)
einvoice inspect ricevuta.xml           # riepiloga un documento RICEVUTO (exit 1 se i conti non tornano)
einvoice parse   ricevuta.xml -o x.json # XML ricevuto → JSON
einvoice totals fattura.json            # riepiloghi IVA calcolati (JSON)
einvoice render fattura.json -o IT.xml  # FatturaPA
einvoice render fattura.json --country DE --xrechnung
einvoice render fattura.json --standard cii -o FR.xml   # Factur-X / Chorus Pro
einvoice normalize fattura.json         # forma canonica, per diffare fixture
einvoice sign IT.xml --p12 cert.p12 --passphrase ...
einvoice countries                      # tutti i paesi: standard, obblighi, forza della verifica
einvoice countries CH --tax-id CHE-116.281.710
einvoice providers --kinds              # le cinque categorie
einvoice providers --country IT         # piattaforme per mercato
einvoice providers --kind national_portal
einvoice providers fiscozen             # dettaglio: credenziali, renderer, verificato?
einvoice transports / renderers
```

Serve a controllare la risposta del motore contro le attese di un
commercialista **senza tirare su un'applicazione**: stampa esattamente i byte
che un transport spedirebbe. Gli exit code separano *fattura non valida* (`1`)
da *comando sbagliato* (`2`), così in CI un rilievo non si confonde con un typo.

## Firma CAdES + conservazione

```python
from einvoice import sign_cades, build_conservation_package

p7m = sign_cades(xml_it, p12_bytes, passphrase)   # .p7m attached, SHA-256
zip_bytes = build_conservation_package(documents) # ZIP + manifest + pdd_index
```

### Controllare il certificato **prima** di usarlo

Un certificato scaduto si apre benissimo, firma benissimo, e il documento
viene rifiutato a valle. `inspect_p12()` legge l'archivio senza firmare nulla,
così una configurazione sbagliata è un errore di form e non una fattura
respinta settimane dopo:

```python
from einvoice import SigningUnavailable, inspect_p12

try:
    cert = inspect_p12(p12_bytes, passphrase)
except SigningUnavailable:
    ...                      # qui non possiamo controllare: manca l'extra
except ValueError:
    ...                      # l'archivio o la passphrase sono sbagliati

cert.subject                 # "CN=Studio Rossi,C=IT"
cert.valid_until             # date(2027, 3, 14)
cert.is_expired()            # False
cert.expires_within(30)      # True → è ora di rinnovarlo
```

`SigningUnavailable` esiste per una ragione precisa: distingue «non posso
controllare» da «questo certificato è rotto». Chi le collassa in un solo
`except Exception` finisce per salvare come valido un archivio che non lo è.

## Dati di riferimento per una UI

Una piattaforma che espone il setup fiscale ha bisogno degli stessi dati in
JSON. `einvoice.reference` li serve già pronti — nessun `Decimal`, nessuna
`date`, niente `float`:

```python
from einvoice.reference import all_country_references, country_reference

country_reference("DE")["tax_id_label"]   # "USt-IdNr." — come lo chiama il paese
all_country_references()                   # tutti e 30, stessa forma
```

A differenza di `profile_for()`, che è permissivo apposta perché il rendering
non deve mai fermarsi, `country_reference()` è **stretto**: un paese non
supportato solleva `KeyError`. Una schermata di setup sta *chiedendo* quali
sono le regole, e un profilo generico spacciato per quelle del Portogallo è
una risposta sbagliata con la bandiera giusta.

### Fornitori, formati e istruzioni — in 31 lingue

Lo stesso vale un livello sopra. Un elenco di fornitori scritto a mano nel
frontend mostra chiavi di registro grezze (`wolters_kluwer`) e gli stessi
cinque campi credenziali per tutti, quindi «configura Fatture in Cloud»
significa compilare un *Base URL* che non usa e lasciare vuoto il *Company ID*
senza cui non funziona.

```python
from einvoice.reference import all_provider_references, all_renderer_references

guide = all_provider_references("pl", country="PL")[0]
[f["key"] for f in guide["credentials"]]   # solo i campi che quel fornitore usa
[s["text"] for s in guide["steps"]]        # istruzioni di setup, in polacco
guide["caveats"]                           # e cosa ti morderà, separato

all_renderer_references("de", country="DE")   # niente FatturaPA per un cedente DE
```

```bash
einvoice providers fattureincloud --setup --lang de
einvoice renderers --country FR --lang fr
einvoice locales
```

Le guide sono **composte** dai preset, non scritte: una piattaforma aggiunta
come voce di dizionario arriva con le istruzioni complete in tutte le lingue, e
non possono divergere dal preset che descrivono. Le lingue sono quelle ufficiali
dei trenta paesi profilati più le locale d'interfaccia dei prodotti ospitanti —
un paese di cui dichiariamo le regole, in una lingua che i suoi contribuenti non
leggono, è supportato a metà. Dettagli in [docs/SETUP.md](docs/SETUP.md).

## Documentazione

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — i 3 livelli, engine, stati, matrice EU, roadmap
- [docs/RENDERERS.md](docs/RENDERERS.md) — formati (FatturaPA, UBL/EN16931), come aggiungerne
- [docs/TRANSPORT.md](docs/TRANSPORT.md) — canali, firma, conservazione, notifiche
- [docs/FATTURAPA.md](docs/FATTURAPA.md) — mappatura IT, campi, codici
- [docs/INTEGRATION.md](docs/INTEGRATION.md) — integrazione in una piattaforma
- [docs/CLI.md](docs/CLI.md) — riga di comando e formato JSON (riferimento campi)
- [docs/COUNTRIES.md](docs/COUNTRIES.md) — matrice paese per paese: formati, obblighi, tax-id
- [docs/TAXES.md](docs/TAXES.md) — aliquote IVA **per categoria di prodotto** e regole fiscali (conservazione, soglie, termini)
- [docs/PROVIDERS.md](docs/PROVIDERS.md) — le 65 piattaforme e come collegarne una nuova
- [docs/SETUP.md](docs/SETUP.md) — istruzioni di configurazione per ogni piattaforma e formato, in 31 lingue
- [docs/PARSING.md](docs/PARSING.md) — leggere una fattura ricevuta: cosa sopravvive e cosa no
- [docs/CORRECTIONS.md](docs/CORRECTIONS.md) — note di credito, note di debito e resi
- [docs/SIGNING.md](docs/SIGNING.md) — firma CAdES, certificati, scadenze, conservazione
- [CONTRIBUTING.md](CONTRIBUTING.md) — regole di progetto (core senza dipendenze, Decimal, profili paese)
- [CHANGELOG.md](CHANGELOG.md) — cronologia versioni

## Test

```bash
pip install -e ".[dev]"
pytest -q          # 1618 test, ~1.7 s
mypy               # pulito, ed è imposto in CI
ruff check .
```

## Avvertenze

- **Firma CAdES** `.p7m`: `sign_cades(...)` produce PKCS#7 SignedData DER
  *attached* SHA-256 da un PKCS#12 di **firma qualificata**. Nota: manca
  l'attributo ETSI `signing-certificate-v2` di CAdES-BES — per conformità
  garantita usare un servizio di firma accreditato (vedi `einvoice/signer.py`).
- **Conservazione a norma**: `build_conservation_package(...)` genera lo ZIP
  di export (file + `manifest.json` con hash + `pdd_index.xml` IPdA-like) da
  consegnare a un **conservatore accreditato**; `WebhookConservationProvider`
  lo POSTa a un URL configurato. `FileArchive` resta un default dev/audit, NON
  conservazione certificata.
- I pattern tax-id dei profili paese sono **strutturali** (formato VIES/EIN),
  non verificano il checksum né l'esistenza: per quello serve una lookup VIES /
  IRS.
- I path API dei provider vanno **confermati sul tuo account**: solo Aruba e
  Fatture in Cloud sono `endpoints_verified=True`. Gli altri girano sul
  `GenericHubTransport`, configurabile (`upload_path`, `content_field`,
  `auth_scheme`, …), perché sono tutti la stessa forma REST con nomi diversi e
  la configurazione batte un modulo scritto contro un contratto non testabile.
- **Polonia e Spagna non sono coperte** dal rendering: KSeF vuole FA(2) e FACe
  vuole Facturae 3.2.x, sintassi nazionali che questo pacchetto non genera. I
  profili lo dichiarano (`regime.national_format`), non lo lasciano scoprire in
  produzione.
- I **dati normativi** (obblighi, scadenze, reti) sono datati da
  `MANDATES_VERIFIED_AS_OF` e sono **guida operativa, non consulenza legale**:
  le regole si muovono, verificare presso l'autorità fiscale nazionale. Le parti
  meccaniche (tax-id, aliquote, CIUS, regole di rendering) non invecchiano
  allo stesso modo.
- Le **aliquote IVA note** servono solo a `check()` come avviso: un'aliquota
  fuori elenco non blocca nulla, perché regimi speciali e transitori esistono.
- *Factur-X* completo = XML **dentro** un PDF/A-3. Qui si genera l'XML;
  l'incapsulamento in PDF è fuori perimetro.

MIT.
