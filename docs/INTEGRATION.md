# Integrazione in una piattaforma

Il lavoro lato piattaforma è **mappare i tuoi dati su `Invoice`**, scegliere
formato e canale, e **persistere `provider_id` + stato** del ciclo di vita.

## 1. Installazione

```bash
pip install -e /path/to/einvoice            # core + formats
pip install -e "/path/to/einvoice[providers]"  # + transport di rete
```

## 2. Mappatura (il pattern)

```python
from einvoice import Invoice, Party, Address, LineItem, Payment, PaymentMeans

def to_invoice(order, customer, company) -> Invoice:
    return Invoice(
        number=order.invoice_number, date=order.date,
        seller=Party(name=company.name, vat_number=company.vat, tax_code=company.tax_code,
                     address=Address(company.street, company.cap, company.city, company.province),
                     tax_regime="RF01"),
        buyer=Party(name=customer.legal_name, vat_number=customer.vat, tax_code=customer.tax_code,
                    address=Address(customer.street, customer.cap, customer.city, customer.province),
                    sdi_code=customer.sdi, pec=customer.pec),
        lines=[LineItem.from_gross(li.name, li.qty, li.gross_unit_price, li.vat_rate)
               for li in order.items],     # from_gross = scorporo IVA da prezzo lordo (POS)
        payments=[Payment(means=PaymentMeans.CARD)],
    )
```

## 3. Motore + persistenza ciclo di vita

```python
from einvoice import EInvoiceEngine, Lifecycle, InvoiceState
from einvoice.formats import get_renderer
from einvoice.transport import get_transport, TransportConfig, FileArchive

def build_engine(cfg) -> EInvoiceEngine:
    return EInvoiceEngine(
        renderer=get_renderer(cfg["format"]),                 # "fatturapa" | "ubl"
        transport=get_transport(cfg["channel"], TransportConfig(
            name=cfg["channel"], api_key=cfg.get("api_key"),
            username=cfg.get("username"), password=cfg.get("password"),
            company_id=cfg.get("company_id"), base_url=cfg.get("base_url"),
            sandbox=cfg.get("sandbox", True))),
        archive=FileArchive(cfg["archive_dir"]) if cfg.get("archive_dir") else None,
    )

async def submit(order, cfg, store):
    invoice = to_invoice(order, order.customer, order.company)
    lifecycle = Lifecycle(InvoiceState(store.get_state(order.id)) if store.has(order.id) else InvoiceState.DRAFT)
    result = await build_engine(cfg).process(invoice, lifecycle=lifecycle)
    store.save(order.id, provider_id=result.submission.provider_id,
               state=result.lifecycle.state.value, filename=result.rendered.filename,
               audit=result.lifecycle.audit_trail())
    return result
```

Le **notifiche** (webhook del provider / polling) avanzano lo stesso stato:

```python
notif = transport.parse_notification(payload)     # → Notification | None
if notif:
    lc = Lifecycle(InvoiceState(store.get_state(order_id)))
    lc.apply(notif)
    store.save(order_id, state=lc.state.value, audit=lc.audit_trail())
```

## 4. Esempio TableOS

In TableOS la fattura elettronica riguarda **solo** `bill.document_type in
("invoice", "simplified_invoice")** (lo scontrino/RT non è una FatturaPA).

```python
# backend/app/features/einvoice/mapping.py
from datetime import date
from decimal import Decimal
from einvoice import Invoice, Party, Address, LineItem, Payment, PaymentMeans

_PAY = {"cash": PaymentMeans.CASH, "card_pos": PaymentMeans.CARD, "satispay": PaymentMeans.CARD,
        "meal_voucher": PaymentMeans.CASH, "split": PaymentMeans.CARD, "other": PaymentMeans.BANK_TRANSFER}

def fiscal_doc_to_invoice(restaurant, bill, rows, *, number: str) -> Invoice:
    """``rows``: (name, qty, gross_unit_price, vat_rate) — riusa
    fiscal/service.vat_rate_for_item per le aliquote (stessa logica del PDF)."""
    cust = bill.customer_fiscal_data or {}
    return Invoice(
        number=number, date=date.today(),
        seller=Party(name=restaurant.name, vat_number=restaurant.vat_number,
                     address=Address(restaurant.address or "-", "00000", restaurant.city or "-", None)),
        buyer=Party(name=cust.get("legal_name"), vat_number=cust.get("vat_number"),
                    tax_code=cust.get("fiscal_code"),
                    address=Address(cust.get("address", "-"), "00000", "-", None),
                    sdi_code=cust.get("sdi_code"), pec=cust.get("pec")),
        lines=[LineItem.from_gross(n, q, Decimal(str(g)), Decimal(str(r))) for (n, q, g, r) in rows],
        payments=[Payment(means=_PAY.get(bill.payment_method, PaymentMeans.BANK_TRANSFER))],
        causale="Servizio di ristorazione",
    )
```

```python
# backend/app/features/einvoice/router.py
@router.post("/fiscal/documents/{document_id}/einvoice")
async def emit_einvoice(document_id: UUID, restaurant=Depends(...), db=Depends(get_db)):
    doc = await _load_owned_document(db, restaurant, document_id)
    bill = await _load_bill(db, doc.bill_id)
    if bill.document_type == "receipt":
        raise HTTPException(409, "Lo scontrino non genera fattura elettronica")
    rows = await _einvoice_rows(db, bill)
    invoice = fiscal_doc_to_invoice(restaurant, bill, rows,
                                    number=f"{doc.year}/{doc.progressive_number:04d}")
    cfg = (restaurant.settings or {}).get("einvoice", {"format": "fatturapa", "channel": "file"})
    result = await build_engine(cfg).process(invoice)
    # persisti su einvoice_submissions(fiscal_document_id, provider_id, sdi_id, state, filename, audit)
    return {"state": result.lifecycle.state.value,
            "provider_id": result.submission.provider_id,
            "filename": result.rendered.filename}
```

### Persistenza consigliata

Tabella `einvoice_submissions(fiscal_document_id, format, channel, provider_id,
sdi_id, state, filename, audit JSONB, created_at)` + un worker che fa polling di
`fetch_status` / consuma i webhook e applica le `Notification` al `Lifecycle`.

## Checklist

- [ ] `to_invoice(...)` (mappa dati → `Invoice`)
- [ ] scelta `format` + `channel` da settings; credenziali da secrets
- [ ] `EInvoiceEngine.process` + persistenza `provider_id` / `state` / `audit`
- [ ] worker notifiche/polling → `lifecycle.apply(notification)`
- [ ] firma (delega al portale o `Signer`) + conservazione (`ArchiveStore`)
- [ ] test in `sandbox=True` prima della produzione
