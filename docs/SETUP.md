# Istruzioni di configurazione, in 31 lingue

Un preset dice **cosa** mandare e **dove**. Non diceva come entrare dalla porta:
quale account aprire, quali fra i cinque campi credenziali quel fornitore
vuole davvero, se esiste una sandbox, e cosa ti morderà.

I due prodotti che incorporano il pacchetto mostravano gli stessi cinque input
per ogni fornitore e nessuna istruzione. «Configura Fatture in Cloud»
significava compilare un *Base URL* che Fatture in Cloud non usa e lasciare
vuoto il *Company ID* senza il quale non funziona.

```python
from einvoice.onboarding import setup_guide

guide = setup_guide("fattureincloud", "de")
[f["key"] for f in guide["credentials"]]   # ['api_key', 'company_id'] — solo quelli
[s["text"] for s in guide["steps"]]        # in tedesco
guide["caveats"]                           # cosa ti morderà, separato
```

```bash
einvoice providers aruba --setup --lang de
einvoice renderers --country FR --lang fr
einvoice locales
```

## Composte, non scritte

Scrivere sessantacinque guide in prosa le avrebbe risolte **in una lingua sola**.
Invece ogni preset nomina una sequenza ordinata di **chiavi di passo**
(`einvoice.i18n`), e la sequenza è in gran parte **derivata**: dalle credenziali
che il preset dichiara, dal fatto che il suo host sia conoscibile in anticipo,
dall'esistenza di una sandbox.

Ne seguono due proprietà che la prosa non ha:

1. una piattaforma aggiunta come voce di dizionario arriva con la guida
   completa in **tutte** le lingue, senza che nessuno traduca niente;
2. la guida **non può divergere** dal preset che descrive, perché è generata
   da quello. Il caso classico — le credenziali cambiano e le istruzioni no —
   qui non è possibile.

Ordine dei passi (quelli che non si applicano spariscono):

| # | Passo | Quando |
|---|---|---|
| 1 | `step.create_account` | sempre |
| 2 | `step.contract_required` / `step.request_api_access` | flag `contract`; il secondo salta sui portali nazionali |
| 3 | `step.certificate_required` | flag `certificate` |
| 4 | `step.oauth2_required` | flag `oauth2` |
| 5 | `step.copy_api_key` · `step.copy_company_id` · `step.copy_username_password` | dalle credenziali dichiarate |
| 6 | `step.ask_base_url` / `step.known_base_url` | a seconda di `needs_base_url` |
| 7 | `step.render_format` | salta se il canale rifiuta ciò che generiamo |
| 8 | `step.receive_inbound` | se il preset supporta `receive` |
| 9 | `step.sandbox_url` / `step.sandbox_missing` | a seconda di `sandbox_url` |
| 10 | `step.test_before_live` · `step.store_credentials` | sempre |

## Passi e avvertenze sono due cose diverse

Le **avvertenze** (`caveats`) stanno fuori dall'elenco numerato di proposito.
Un avviso dentro una checklist si legge come un passo da spuntare, e «questo
canale non accetterà ciò che generiamo» non è un passo: è un motivo per
fermarsi.

Ne esistono due:

- **`step.national_format_warning`** — il canale accetta *solo* una sintassi
  nazionale che questo pacchetto non genera. Oggi: KSeF (`FA(2)`) e FACe
  (`Facturae 3.2.x`). Dichiarata come campo `incompatible_national_format`, non
  sepolta in `notes`, perché è l'unico fatto che decide se il preset è
  utilizzabile — e un avviso che solo un lettore italiano riesce a trovare è un
  avviso che verrà mancato.
- **`step.confirm_paths`** — `endpoints_verified=False`. Vedi
  [PROVIDERS.md](PROVIDERS.md#il-campo-che-conta-endpoints_verified).

## I flag di setup

Tre fatti che nessuna tupla di credenziali rivela, dichiarati sul preset:

| Flag | Significa |
|---|---|
| `contract` | Le credenziali arrivano con una firma, non da un form di registrazione. Si parte dal referente commerciale, non dal portale sviluppatori. |
| `oauth2` | Si registra un'applicazione e si conservano le credenziali client, non una chiave statica. |
| `certificate` | La connessione stessa richiede un certificato qualificato (mTLS, PKI nazionale). Va procurato **prima** di configurare il resto. |

## Le lingue

Trentuno: le lingue ufficiali dei paesi che il pacchetto profila (UE-27 + Regno
Unito + Svizzera + Stati Uniti — ventiquattro) più le locale d'interfaccia che i
prodotti ospitanti spediscono (`ar`, `fil`, `id`, `ja`, `ru`, `th`, `zh`).

Un paese di cui dichiariamo le regole, in una lingua che i suoi contribuenti non
leggono, è supportato a metà.

```python
from einvoice.i18n import locale_for_country, normalize_locale

locale_for_country("BE")     # 'nl' — prima lingua ufficiale
normalize_locale("pt-BR")    # 'pt'
normalize_locale("klingon")  # 'en' — degrada, non solleva
```

`normalize_locale` è deliberatamente permissiva: sta dietro un query parameter,
e una locale scritta male dal chiamante deve degradare all'inglese, non
restituire 400 a una pagina di impostazioni.

### Cosa **non** viene tradotto

I nomi delle piattaforme (`Fatture in Cloud`, `Chorus Pro`), quelli dei formati
(`FatturaPA`, `Peppol BIS 3.0`, `XRechnung`) e le chiavi delle credenziali
(`api_key`). Sono nomi propri e identificatori: tradurli renderebbe le
istruzioni **più difficili** da seguire, perché l'operatore deve ritrovare
quella parola esatta nella console del fornitore.

Il campo `notes` del preset è prosa italiana scritta a mano e resta fuori dal
catalogo. Viene esposto con `notes_language: "it"` accanto, così un client può
etichettarlo invece di spacciarlo per la lingua dell'operatore.

## Le due garanzie meccaniche

Entrambi i modi di rompere un catalogo di traduzioni sono invisibili a chi
legge il file, quindi sono test:

- **`test_every_key_exists_in_every_language`** — una lingua mancante non la
  nota nessuno: `translate()` ripiega sull'inglese e la schermata sembra a
  posto a chi la sta provando, che di solito non è la persona che aveva bisogno
  del bulgaro.
- **`test_every_translation_carries_the_same_placeholders`** — un `{base_url}`
  perso lascia una frase che si legge benissimo e non dice più l'host. È tutto
  il contenuto del passo, sparito in silenzio.

## Servirle da una piattaforma

`einvoice.reference` è l'unico import che serve a una schermata di setup:

```python
from einvoice.reference import (
    all_provider_references,   # elenco piattaforme + guide, filtrabile per paese
    provider_reference,        # una piattaforma
    provider_kind_reference,   # le categorie, etichettate
    all_renderer_references,   # i formati, alias collassati
    locale_reference,          # lingue disponibili + default per paese
)

all_provider_references("pl", country="PL")
all_renderer_references("de", country="DE")
```

Tutto è già JSON-safe: `Decimal` diventa stringa, le date diventano ISO, e il
risultato passa da `json.dumps` senza encoder personalizzati.
