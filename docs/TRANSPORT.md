# Transport (canali)

Un transport consegna un `RenderedDocument` su un canale e normalizza gli esiti.

```python
from einvoice.transport import get_transport, TransportConfig, available_transports
available_transports()   # ['aruba','fattureincloud','file','hub','infocert','notartel',
                         #  'peppol','sdi','wolters_kluwer','xml_export','zucchetti', ...]
t = get_transport("aruba", TransportConfig(name="aruba", username=..., password=..., sandbox=True))
res = await t.transmit(rendered, invoice)       # SubmissionResult
st  = await t.fetch_status(res.provider_id)     # TransportStatus
```

Interfaccia:

```python
class Transport(ABC):
    name: str
    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult: ...
    async def fetch_status(self, provider_id: str) -> TransportStatus: ...
    def parse_notification(self, payload: dict) -> Notification | None: ...   # webhook → esito
```

## Canali inclusi

| Canale | Config richiesta | Note |
|---|---|---|
| `file` (`file_export`) | — | scrive in `extra['output_dir']`; ritorna i byte. Zero rete. |
| `fattureincloud` | `api_key`, `company_id` | API strutturata: mappa l'`Invoice` (ignora il rendered). |
| `aruba` | `username`, `password` | upload XML base64; `sandbox=True` host demo; firma lato Aruba. |
| `zucchetti` | `api_key`, `base_url` | upload XML base64 sul Digital Hub. |
| `peppol` | `base_url`, `api_key` | **Access Point** gateway: invia **UBL** (non FatturaPA). |
| `sdi` | (= fattureincloud) | alias del canale SdI di default; sovrascrivibile. |
| `hub` · `infocert` · `notartel` · `wolters_kluwer` | `base_url` + `api_key` **o** `username`+`password` | Hub REST **configurabile** — vedi sotto. |

`extra` porta override specifici (es. `auth_url`, `sender_id`, `receiver_scheme`).

## Hub configurabile (`GenericHubTransport`)

L'Italia ha una coda lunga di intermediari SdI — InfoCert Legalinvoice HUB,
Notartel, Wolters Kluwer Fattura SMART, più ogni software house regionale — e
hanno tutti la stessa forma: autenticarsi con un token, fare POST dell'XML in
base64 sotto *qualche* nome di campo, interrogare un endpoint documento per
l'esito SdI. Cambiano solo i **nomi**.

Scrivere un modulo per fornitore significa pubblicare codice contro contratti
che non possiamo testare né tenere allineati al ciclo di rilascio di ciascun
vendor. Questo transport prende quei nomi da `extra`, così **integrarne uno è
configurazione, non un rilascio**:

```python
get_transport("infocert", TransportConfig(
    name="infocert",
    base_url="https://hub.legalinvoice.it/api/v1",
    api_key="…",
    extra={"upload_path": "/documents", "content_field": "fileContent"},
))
```

| chiave di `extra` | default | significato |
|---|---|---|
| `upload_path` | `/invoices` | path in POST, appeso a `base_url` |
| `status_path` | `/invoices/{id}` | path di stato; `{id}` viene sostituito |
| `content_field` | `content` | campo che porta l'XML base64 |
| `filename_field` | `filename` | campo che porta il nome file |
| `auth_scheme` | `bearer` | `bearer` \| `apikey` \| `basic` |
| `auth_header` | `X-API-Key` | header usato quando lo schema è `apikey` |
| `extra_fields` | `{}` | unito al body di upload così com'è |

Ogni chiave ha un default che segue la convenzione più diffusa: un hub che la
rispetta ha bisogno solo di `base_url` e di una credenziale.

La mappa degli stati accetta vocabolario **italiano, inglese e codici SdI grezzi**
(`consegnato` / `delivered` / `RC` → `accepted`), e la dicitura originale del
fornitore resta in `sdi_status` per il supporto.

Scrivere un adapter dedicato ha senso solo quando il flusso è davvero diverso
(autenticazione multi-step, API a documento strutturato invece che upload XML).

## Stati normalizzati

`exported · submitted · pending · delivered · accepted · rejected · not_delivered · error · unknown`
(i codici nativi restano in `raw` / `sdi_status`).

## Notifiche (esiti) → macchina a stati

I provider mandano notifiche asincrone (webhook/polling). `parse_notification`
le normalizza in `Notification`; applicarle avanza il `Lifecycle`:

```python
notif = transport.parse_notification(webhook_payload)   # es. Aruba "CONS" → DELIVERED
if notif:
    lifecycle.apply(notif)        # state → delivered, evento in audit_trail()
```

Tipi normalizzati: `DELIVERED` (RC), `REJECTED` (NS), `NOT_DELIVERED` (MC),
`OUTCOME`/`CUSTOMER_OUTCOME` (NE/EC), `DEADLINE_PASSED` (DT), `RECEIPT`.

## Firma e conservazione (pluggable)

```python
class Signer(Protocol):
    def sign(self, content: bytes, *, filename: str) -> tuple[bytes, str]: ...   # → CAdES .p7m

class ArchiveStore(Protocol):
    async def store(self, rendered, invoice, *, result=None) -> str: ...         # conservazione/audit
```

Passali all'`EInvoiceEngine`; `FileArchive("/dir")` è un default per dev/audit
(NON conservazione a norma certificata). La firma reale richiede certificato
qualificato (HSM/smart card/servizio) — oppure la delega al portale.

## Aggiungere un canale

```python
from einvoice.transport import Transport, TransportConfig, SubmissionResult, TransportStatus, register_transport
from einvoice.transport._http import request_json

class MyApTransport(Transport):
    name = "myap"
    async def transmit(self, rendered, invoice):
        resp = await request_json("POST", f"{self.config.base_url}/send",
                                  headers={"Authorization": f"Bearer {self.config.api_key}"},
                                  json={"xml": rendered.content.decode()})
        return SubmissionResult(transport=self.name, status="submitted", provider_id=str(resp.get("id")), raw=resp)
    async def fetch_status(self, provider_id):
        ...

register_transport("myap", MyApTransport)
```

## ⚠️ Endpoint reali

`file`, `fattureincloud` seguono API documentate; **Aruba/Zucchetti/PEPPOL** hanno
la struttura corretta (auth → upload base64 → stato) ma i path esatti vanno
confermati sul contratto API del tuo account. Testa sempre in `sandbox=True`.
