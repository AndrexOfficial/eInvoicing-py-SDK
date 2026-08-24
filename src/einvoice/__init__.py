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
    CIUS_RO_CUSTOMIZATION,
    COUNTRY_PROFILES,
    EU_COUNTRIES,
    EU_OSS_THRESHOLD,
    MANDATES_VERIFIED_AS_OF,
    NLCIUS_CUSTOMIZATION,
    PEPPOL_CUSTOMIZATION,
    XRECHNUNG_CUSTOMIZATION,
    CountryProfile,
    EInvoicingRegime,
    FiscalRules,
    profile_for,
    renderer_for_country,
    supported_countries,
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
    SigningUnavailable,
    TransportError,
    ValidationError,
)
from .formats import (
    FACTURX_PROFILES,
    CiiRenderer,
    FatturaPARenderer,
    InvoiceRenderer,
    RenderedDocument,
    UblRenderer,
    available_renderers,
    build_cii_xml,
    build_fattura_xml,
    build_ubl_xml,
    get_renderer,
    register_renderer,
)
from .lifecycle import Lifecycle, LifecycleEvent, Notification
from .models import (
    PEPPOL_EAS_BY_COUNTRY,
    Address,
    Advisory,
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
from .parsing import (
    compare_declared_totals,
    detect_standard,
    parse_cii_xml,
    parse_fattura_xml,
    parse_invoice,
    parse_ubl_xml,
)
from .rates import (
    ALWAYS_STANDARD_RATED,
    COMMONLY_EXEMPT,
    COUNTRY_RATES,
    NO_NATIONAL_VAT,
    RATES_VERIFIED_AS_OF,
    ProductCategory,
    RateKind,
    VatRate,
    categories_for,
    rate_for,
    rates_for,
    standard_rate,
)
from .reference import (
    all_country_references,
    country_reference,
    product_categories,
    reference_metadata,
)
from .serde import (
    invoice_from_dict,
    invoice_from_json,
    invoice_to_dict,
    invoice_to_json,
)
from .signer import (
    P12Signer,
    SigningCertificate,
    inspect_p12,
    sign_cades,
    sign_filename,
)
from .taxid import CHECKSUM_COUNTRIES, normalize_tax_id, validation_level
from .transport import (
    PROVIDER_KINDS,
    PROVIDER_PRESETS,
    ArchiveStore,
    FileArchive,
    GenericHubTransport,
    ProviderConfig,
    ProviderPreset,
    Signer,
    SubmissionResult,
    Transport,
    TransportConfig,
    TransportStatus,
    available_providers,
    available_transports,
    get_transport,
    preset_for,
    providers_for_country,
    providers_of_kind,
    register_transport,
    transport_for_provider,
)

__version__ = "0.5.0"

__all__ = [
    # domain
    "Invoice", "Party", "Address", "LineItem", "Payment", "VatSummary", "Advisory",
    "AllowanceCharge", "WithholdingTax", "SocialSecurityFund",
    "DocumentReference", "Attachment", "BankAccount", "PEPPOL_EAS_BY_COUNTRY",
    # countries
    "CountryProfile", "EInvoicingRegime", "FiscalRules", "EU_OSS_THRESHOLD",
    "COUNTRY_PROFILES", "EU_COUNTRIES",
    # VAT rates by product category
    "ProductCategory", "RateKind", "VatRate", "COUNTRY_RATES", "NO_NATIONAL_VAT",
    "COMMONLY_EXEMPT", "ALWAYS_STANDARD_RATED", "RATES_VERIFIED_AS_OF",
    "rates_for", "rate_for", "standard_rate", "categories_for",
    "profile_for", "renderer_for_country", "supported_countries",
    "validate_tax_id", "normalize_tax_id", "validation_level",
    "CHECKSUM_COUNTRIES", "MANDATES_VERIFIED_AS_OF",
    "XRECHNUNG_CUSTOMIZATION", "PEPPOL_CUSTOMIZATION", "NLCIUS_CUSTOMIZATION",
    "CIUS_RO_CUSTOMIZATION",
    # signing + conservation
    "P12Signer", "sign_cades", "sign_filename", "inspect_p12", "SigningCertificate",
    "country_reference", "all_country_references", "product_categories",
    "reference_metadata",
    "ConservationProvider", "WebhookConservationProvider", "build_conservation_package",
    # enums
    "DocumentType", "TransmissionFormat", "VatNature", "VatExigibility",
    "PaymentMeans", "WithholdingType", "InvoiceState", "NotificationType",
    "REGIMI_FISCALI",
    # lifecycle
    "Lifecycle", "LifecycleEvent", "Notification",
    # formats
    "build_fattura_xml", "build_ubl_xml", "build_cii_xml",
    "get_renderer", "register_renderer",
    "available_renderers", "RenderedDocument", "InvoiceRenderer",
    "FatturaPARenderer", "UblRenderer", "CiiRenderer", "FACTURX_PROFILES",
    # transport
    "get_transport", "register_transport", "available_transports",
    "TransportConfig", "ProviderConfig", "SubmissionResult", "TransportStatus",
    "Transport", "Signer", "ArchiveStore", "FileArchive", "GenericHubTransport",
    "ProviderPreset", "PROVIDER_PRESETS", "PROVIDER_KINDS",
    "available_providers", "preset_for",
    "providers_for_country", "providers_of_kind", "transport_for_provider",
    # engine
    "EInvoiceEngine", "EngineResult",
    # parsing (inbound)
    "parse_invoice", "detect_standard", "parse_ubl_xml", "parse_cii_xml",
    "parse_fattura_xml", "compare_declared_totals",
    # naming + serde + errors
    "sdi_filename", "to_base36",
    "invoice_to_dict", "invoice_from_dict", "invoice_to_json", "invoice_from_json",
    "EInvoiceError", "ValidationError", "ProviderConfigError", "ProviderError",
    "TransportError", "RenderError", "IllegalTransition", "SigningUnavailable",
    "__version__",
]
