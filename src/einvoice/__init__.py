"""einvoice — multichannel electronic-invoicing engine (standalone, reusable).

Three layers, mix and match:

  * **Core domain** (zero deps): one country-neutral, EN 16931-aligned
    :class:`Invoice` model + a unified state machine (:class:`Lifecycle`).
  * **Format renderers** (zero deps): turn the model into a standard's bytes —
    ``fatturapa`` (Italy/SdI, full 1.2.2 code lists: TD01–TD28, N1–N7 dotted,
    MP01–MP23, cassa previdenziale, sconti di linea, art. 73 …) and ``ubl``
    (Peppol BIS Billing 3.0 / EN 16931, Invoice + CreditNote roots, Peppol
    EAS endpoints, VAT categories S/Z/E/AE/K/G/O). Add more.
  * **Transport channels** (optional ``httpx``): deliver the document — SdI via
    provider (FattureInCloud / Aruba / Zucchetti), PEPPOL Access Point, or a
    plain file export — with normalized notifications, signing and archival hooks.

Glue them with the :class:`EInvoiceEngine`, or use any layer standalone.

Quick start (one-call XML)::

    from einvoice import Invoice, Party, Address, LineItem, build_fattura_xml
    xml = build_fattura_xml(invoice)        # FatturaPA bytes, ready to upload

Quick start (engine)::

    from einvoice import EInvoiceEngine
    from einvoice.formats import get_renderer
    from einvoice.transport import get_transport, TransportConfig
    engine = EInvoiceEngine(get_renderer("fatturapa"),
                            get_transport("file", TransportConfig(name="file")))
    result = await engine.process(invoice)
"""
from .conservation import (
    ConservationProvider,
    WebhookConservationProvider,
    build_conservation_package,
)
from .countries import (
    COUNTRY_PROFILES,
    EU_COUNTRIES,
    XRECHNUNG_CUSTOMIZATION,
    CountryProfile,
    profile_for,
    renderer_for_country,
    validate_tax_id,
)
from .engine import EInvoiceEngine, EngineResult
from .enums import (
    REGIMI_FISCALI,
    DocumentType,
    InvoiceState,
    NotificationType,
    PaymentMeans,
    TransmissionFormat,
    VatExigibility,
    VatNature,
    WithholdingType,
)
from .errors import (
    EInvoiceError,
    IllegalTransition,
    ProviderConfigError,
    ProviderError,
    RenderError,
    TransportError,
    ValidationError,
)
from .formats import (
    FatturaPARenderer,
    InvoiceRenderer,
    RenderedDocument,
    UblRenderer,
    available_renderers,
    build_fattura_xml,
    build_ubl_xml,
    get_renderer,
    register_renderer,
)
from .lifecycle import Lifecycle, LifecycleEvent, Notification
from .models import (
    PEPPOL_EAS_BY_COUNTRY,
    Address,
    AllowanceCharge,
    Attachment,
    BankAccount,
    DocumentReference,
    Invoice,
    LineItem,
    Party,
    Payment,
    SocialSecurityFund,
    VatSummary,
    WithholdingTax,
)
from .naming import sdi_filename, to_base36
from .serde import (
    invoice_from_dict,
    invoice_from_json,
    invoice_to_dict,
    invoice_to_json,
)
from .signer import P12Signer, sign_cades, sign_filename
from .transport import (
    ArchiveStore,
    FileArchive,
    GenericHubTransport,
    ProviderConfig,
    Signer,
    SubmissionResult,
    Transport,
    TransportConfig,
    TransportStatus,
    available_transports,
    get_transport,
    register_transport,
)

__version__ = "0.4.0"

__all__ = [
    # domain
    "Invoice", "Party", "Address", "LineItem", "Payment", "VatSummary",
    "AllowanceCharge", "WithholdingTax", "SocialSecurityFund",
    "DocumentReference", "Attachment", "BankAccount", "PEPPOL_EAS_BY_COUNTRY",
    # countries
    "CountryProfile", "COUNTRY_PROFILES", "EU_COUNTRIES", "profile_for",
    "renderer_for_country", "validate_tax_id", "XRECHNUNG_CUSTOMIZATION",
    # signing + conservation
    "P12Signer", "sign_cades", "sign_filename",
    "ConservationProvider", "WebhookConservationProvider", "build_conservation_package",
    # enums
    "DocumentType", "TransmissionFormat", "VatNature", "VatExigibility",
    "PaymentMeans", "WithholdingType", "InvoiceState", "NotificationType",
    "REGIMI_FISCALI",
    # lifecycle
    "Lifecycle", "LifecycleEvent", "Notification",
    # formats
    "build_fattura_xml", "build_ubl_xml", "get_renderer", "register_renderer",
    "available_renderers", "RenderedDocument", "InvoiceRenderer",
    "FatturaPARenderer", "UblRenderer",
    # transport
    "get_transport", "register_transport", "available_transports",
    "TransportConfig", "ProviderConfig", "SubmissionResult", "TransportStatus",
    "Transport", "Signer", "ArchiveStore", "FileArchive", "GenericHubTransport",
    # engine
    "EInvoiceEngine", "EngineResult",
    # naming + serde + errors
    "sdi_filename", "to_base36",
    "invoice_to_dict", "invoice_from_dict", "invoice_to_json", "invoice_from_json",
    "EInvoiceError", "ValidationError", "ProviderConfigError", "ProviderError",
    "TransportError", "RenderError", "IllegalTransition",
    "__version__",
]
