# Piattaforme di e-invoicing

Un **preset** raccoglie in un posto solo ciò che serve per parlare con una
piattaforma: quale trasporto, quali credenziali, quale formato renderizzare.

```python
from einvoice import transport_for_provider

t = transport_for_provider("fiscozen", api_key="…", base_url="https://…")
result = await t.transmit(rendered, invoice)
```

```bash
einvoice providers               # tutte
einvoice providers --country IT  # solo quelle italiane + gli aggregatori
einvoice providers fiscozen      # dettaglio in JSON
```

## Il campo che conta: `endpoints_verified`

| valore | significa |
|---|---|
| `True` | Il flusso è implementato su contratto pubblico ed è esercitato dai test del pacchetto. |
| `False` | La **forma** è giusta — questo trasporto, queste credenziali, questo formato — ma i path vanno confermati sulla documentazione del tuo account. |

Quasi tutti i preset sono `False`, e questo è deliberato. La maggior parte di
questi fornitori pubblica il contratto API solo ai titolari di account, e
diversi cambiano i path fra piani tariffari. Spedire una URL dall'aria
convinta per un endpoint che nessuno ha mai chiamato produrrebbe una libreria
che **sembra** integrata e fallisce al primo invio — peggio di una che dice
apertamente «passami `base_url` e controlla questi due nomi di campo». È anche
il motivo per cui quasi tutti richiedono `base_url` dal chiamante.

## Le categorie

Con sessantacinque voci una lista piatta smette di essere navigabile, e le
categorie differiscono in modi che cambiano l'integrazione:

| Categoria | Cosa significa per te |
|---|---|
| `access_point` | Instrada un documento che hai già renderizzato. Tu produci UBL/CII, loro lo consegnano. |
| `sdi_intermediary` | Come sopra, ma per SdI: vogliono **FatturaPA**. |
| `national_portal` | Il canale obbligatorio di un paese. Può imporre una sintassi propria (KSeF, FACe). |
| `accounting_platform` | Possiede l'intero ciclo di vita della fattura; spesso l'e-invoicing è un effetto collaterale. |
| `compliance_suite` | Copertura multi-paese, inclusi i regimi CTC fuori UE. |

```bash
einvoice providers --kinds
einvoice providers --kind national_portal
einvoice providers --country CH
```

Ogni preset dichiara anche i **mercati** che serve — più d'uno quando è il caso:
B2Brouter copre ES e IT, e cercando l'uno o l'altro lo trovi — e cosa **sa
fare** (`send`, `status`, `receive`). `receive` è quello che conta se devi
adempiere all'obbligo di ricezione tedesco o francese.

## I preset

| Chiave | Nome | Mercati | Categoria | Formato | Credenziali | Verificato |
|---|---|---|---|---|---|---|
| `abacus` | Abacus | CH | accounting_platform | ubl | api_key + base_url | — |
| `agyo` | Agyo (TeamSystem) | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `apix` | Apix Messaging | FI | access_point | ubl | api_key + base_url | — |
| `aruba` | Aruba Fatturazione Elettronica | IT | sdi_intermediary | fatturapa | username, password | ✅ |
| `avalara` | Avalara E-Invoicing | global | compliance_suite | ubl | api_key + base_url | — |
| `b2brouter` | B2Brouter | ES,IT,EU | access_point | ubl | api_key | — |
| `basware` | Basware | global | access_point | ubl | api_key + base_url | — |
| `bexio` | Bexio | CH | accounting_platform | ubl | api_key | — |
| `billit` | Billit | BE,NL | access_point | ubl | api_key | — |
| `cegid` | Cegid | FR,ES | accounting_platform | ubl | api_key + base_url | — |
| `chorus_pro` | Chorus Pro | FR | national_portal | cii | api_key | — |
| `comarch` | Comarch e-Invoicing | PL,DE,EU | compliance_suite | ubl | api_key + base_url | — |
| `coupa` | Coupa | global | compliance_suite | ubl | api_key + base_url | — |
| `credemtel` | Credemtel | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `danea` | Danea Easyfatt | IT | accounting_platform | fatturapa | api_key + base_url | — |
| `datev` | DATEV | DE | accounting_platform | ubl | api_key + base_url | — |
| `digipoort` | Digipoort | NL | national_portal | ubl | api_key + base_url | — |
| `docaposte` | Docaposte | FR | compliance_suite | ubl | api_key + base_url | — |
| `ebill_ch` | eBill (SIX) | CH | national_portal | ubl | api_key + base_url | — |
| `ecosio` | ecosio | AT,DE,EU | access_point | ubl | api_key + base_url | — |
| `edicom` | EDICOM | global | compliance_suite | ubl | api_key + base_url | — |
| `efactura_anaf` | e-Factura (ANAF) | RO | national_portal | ubl | api_key | — |
| `esker` | Esker | FR,EU | compliance_suite | ubl | api_key + base_url | — |
| `exact` | Exact Online | NL,BE | accounting_platform | ubl | api_key + base_url | — |
| `face` | FACe | ES | national_portal | ubl | api_key + base_url | — |
| `fattureincloud` | Fatture in Cloud (TeamSystem) | IT | accounting_platform | fatturapa | api_key, company_id | ✅ |
| `fiscozen` | Fiscozen | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `fonoa` | Fonoa | global | compliance_suite | ubl | api_key + base_url | — |
| `galaxygw` | Galaxy Gateway | EU | access_point | ubl | api_key + base_url | — |
| `generix` | Generix Group | FR,EU | compliance_suite | ubl | api_key + base_url | — |
| `inexchange` | InExchange | SE | access_point | ubl | api_key + base_url | — |
| `infocert` | InfoCert Legalinvoice HUB | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `iopole` | Iopole | FR | access_point | ubl | api_key + base_url | — |
| `ksef` | KSeF | PL | national_portal | ubl | api_key | — |
| `logiq` | Logiq | NO,EU | access_point | ubl | api_key + base_url | — |
| `maventa` | Maventa (Visma) | FI,SE | access_point | ubl | api_key + base_url | — |
| `namirial` | Namirial | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `nemhandel` | Nemhandel | DK | national_portal | ubl | api_key + base_url | — |
| `notartel` | Notartel | IT | sdi_intermediary | fatturapa | username, password + base_url | — |
| `openapi_it` | OpenAPI.it Fatturazione | IT | sdi_intermediary | fatturapa | api_key | — |
| `opuscapita` | OpusCapita | FI,SE,NO,EU | access_point | ubl | api_key + base_url | — |
| `pagero` | Pagero | global | access_point | ubl | api_key + base_url | — |
| `passepartout` | Passepartout | IT | accounting_platform | fatturapa | api_key + base_url | — |
| `pennylane` | Pennylane | FR | accounting_platform | ubl | api_key + base_url | — |
| `qvalia` | Qvalia | SE,EU | access_point | ubl | api_key + base_url | — |
| `register_it` | Register.it Fatturazione | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `sage` | Sage | GB,FR,ES,DE | accounting_platform | ubl | api_key + base_url | — |
| `sap_business_network` | SAP Business Network (Ariba) | global | accounting_platform | ubl | api_key + base_url | — |
| `saphety` | Saphety | PT,ES | compliance_suite | ubl | api_key + base_url | — |
| `seeburger` | SEEBURGER BIS | DE,EU | compliance_suite | ubl | api_key + base_url | — |
| `seres` | SERES | ES,FR | compliance_suite | ubl | api_key + base_url | — |
| `smartbill` | SmartBill | RO | accounting_platform | ubl | api_key + base_url | — |
| `sni` | SNI | global | compliance_suite | ubl | api_key + base_url | — |
| `sovos` | Sovos | global | compliance_suite | ubl | api_key + base_url | — |
| `storecove` | Storecove | EU | access_point | ubl | api_key | — |
| `swisscom_conextrade` | Conextrade (Swisscom) | CH | access_point | ubl | api_key + base_url | — |
| `tickstar` | Tickstar (Basware) | SE,EU | access_point | ubl | api_key + base_url | — |
| `tradeshift` | Tradeshift | global | access_point | ubl | api_key + base_url | — |
| `tungsten` | Tungsten Automation (ex Kofax) | global | compliance_suite | ubl | api_key + base_url | — |
| `unifiedpost` | Unifiedpost / Banqup | BE,NL,EU | access_point | ubl | api_key + base_url | — |
| `vertex` | Vertex | global | compliance_suite | ubl | api_key + base_url | — |
| `visma` | Visma | NO,SE,FI,DK,NL | accounting_platform | ubl | api_key + base_url | — |
| `voxel` | Voxel (Amadeus) | ES | compliance_suite | ubl | api_key + base_url | — |
| `wolters_kluwer` | Wolters Kluwer Fattura SMART | IT | sdi_intermediary | fatturapa | api_key + base_url | — |
| `zucchetti` | Zucchetti Digital Hub | IT | sdi_intermediary | fatturapa | api_key + base_url | — |

## Personalizzare un preset

I nomi dei campi cambiano fra fornitori e fra piani. `extra` del chiamante
vince sui default del preset, che sopravvivono per il resto:

```python
t = transport_for_provider(
    "fiscozen",
    api_key="…", base_url="https://api.fiscozen.example",
    extra={"content_field": "documentXml", "upload_path": "/v2/documents"},
)
```

Chiavi disponibili sull'hub configurabile: `upload_path`, `status_path`,
`content_field`, `filename_field`, `auth_scheme` (`bearer` | `apikey` |
`basic`), `auth_header`, `extra_fields`. Tabella completa in
[TRANSPORT.md](TRANSPORT.md).

## Scegliere il formato giusto

Un preset dichiara il renderer da usare, e **non è intercambiabile**:

- **SdI (Italia)** vuole FatturaPA. Mandare UBL a Fiscozen, Aruba o Fatture in
  Cloud è uno scarto.
- **Peppol** vuole UBL (o CII). Mandare FatturaPA a un Access Point è uno scarto.
- **Chorus Pro** prende CII/Factur-X e UBL; il preset punta su CII perché è ciò
  che la riforma francese scambia davvero.
- **KSeF (PL)** e **FACe (ES)** vogliono formati nazionali — FA(2) e Facturae —
  che questo pacchetto **non genera**. I preset esistono per completezza e lo
  dicono nelle note: serve un convertitore, o un provider che lo produca al
  posto tuo (B2Brouter, EDICOM).

## E per ricevere?

L'obbligo tedesco (dal 2025) e quello francese (dal 2026) riguardano la
**ricezione**, non solo l'emissione. I preset che dichiarano `receive` fra i
`supports` sono quelli che possono consegnarti i documenti in arrivo; quello che
poi ne fai è
[`parse_invoice`](PARSING.md) — che legge tutti e tre i formati e ricalcola i
totali invece di crederli.

```bash
einvoice providers --country DE     # chi copre il mercato
einvoice inspect ricevuta.xml       # cosa è arrivato, e se torna
```

## Aggiungere una piattaforma

Se il fornitore segue la forma comune — autenticarsi con un token, fare POST
dell'XML in base64, interrogare un endpoint documento — **è una voce di
dizionario, non un modulo**:

```python
"nuovo_hub": _hub(
    "nuovo_hub", "Nuovo Hub", "IT", renderer="fatturapa",
    docs="https://…",
    extra={"upload_path": "/documents", "content_field": "fileContent"},
    notes="…",
),
```

Scrivi un `Transport` dedicato solo quando il flusso è **davvero** diverso:
autenticazione multi-step (Aruba), API a documento strutturato invece di un
upload XML (Fatture in Cloud), mTLS con certificato qualificato (ANAF, Chorus
Pro in produzione).

E se implementi un flusso contro un contratto pubblico e lo copri con i test,
allora — e solo allora — metti `endpoints_verified=True`.

## Istruzioni di configurazione

Ogni preset produce una guida di setup completa — passi, campi credenziali
etichettati, avvertenze — in **31 lingue**, generata dal preset stesso:

```bash
einvoice providers fattureincloud --setup --lang de
```

```python
from einvoice.onboarding import setup_guide
setup_guide("fattureincloud", "de")["credentials"]   # solo api_key + company_id
```

Non c'è niente da tradurre quando aggiungi una piattaforma: la sequenza dei
passi è derivata dai campi che hai già compilato. Restano due campi opzionali
per i fatti che una tupla di credenziali non rivela:

| Campo | A cosa serve |
|---|---|
| `setup_flags` | `contract` (credenziali a contratto, non da form), `oauth2` (registri un'applicazione), `certificate` (serve un certificato qualificato per la connessione). |
| `incompatible_national_format` | Il canale accetta **solo** una sintassi nazionale che non generiamo — `"FA(2)"` per KSeF, `"Facturae 3.2.x"` per FACe. Diventa un'avvertenza in cima alla guida, e sopprime il passo «renderizza X», che altrimenti contraddirebbe l'avvertenza stessa. |

Dettagli e regole di composizione: [SETUP.md](SETUP.md).
