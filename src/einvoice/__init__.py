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
from .business import (
    BusinessType,
    VatScheme,
    business_profile,
    business_schemes,
    business_supplies,
    business_types,
)
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
from .devices import (
    CONNECTIONS,
    DEVICE_CAPABILITIES,
    DEVICE_KINDS,
    FISCAL_DEVICE_MODELS,
    FISCAL_DEVICE_REGIMES,
    FISCAL_DEVICES_VERIFIED_AS_OF,
    INTEGRATION_CHANNELS,
    POS_TERMINALS,
    REPORTING_KINDS,
    REQUIREMENT_KINDS,
    TERMINAL_CAPABILITIES,
    FiscalDeviceModel,
    FiscalDeviceRegime,
    PosTerminal,
    by_channel,
    countries_requiring_a_device,
    device_regime,
    devices_for_country,
    devices_of_kind,
    drivable_devices,
    fiscal_device_model,
    pos_terminal,
    programmable_terminals,
    terminals_for_country,
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
from .i18n import (
    DEFAULT_LOCALE,
    LOCALES,
    LOCALES_BY_COUNTRY,
    available_locales,
    catalog_for,
    locale_for_country,
    normalize_locale,
    translate,
    translation_keys,
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
from .notifications import (
    SDI_RECEIPT_TYPES,
    SdiError,
    SdiReceipt,
    parse_sdi_receipt,
    receipt_kind_from_filename,
)
from .onboarding import (
    SETUP_FLAGS,
    SetupStep,
    all_setup_guides,
    credential_fields,
    setup_caveats,
    setup_guide,
    setup_steps,
)
from .parsing import (
    compare_declared_totals,
    detect_standard,
    parse_cii_xml,
    parse_fattura_batch,
    parse_fattura_xml,
    parse_invoice,
    parse_invoices,
    parse_ubl_xml,
)
from .pdf import (
    PdfBranding,
    PdfFontUnavailable,
    PdfUnavailable,
    font_for_text,
    invoice_pdf,
    locales_without_font,
    needs_unicode_font,
    receipt_pdf,
    system_unicode_font,
)
from .pos import (
    LOTTERY_CODE_PATTERN,
    PAYMENT_MEANS_BY_POS,
    DepartmentTable,
    PaymentMeansMapping,
    PosPaymentMethod,
    ReceiptReference,
    VatDepartment,
    check_pos_alignment,
    link_receipt,
    payment_means_for,
    validate_lottery_code,
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
from .receipt import (
    CommercialDocument,
    ReceiptPayment,
    check_receipt,
    print_receipt,
    receipt_lines,
)
from .reference import (
    all_country_references,
    all_device_references,
    all_provider_references,
    all_renderer_references,
    country_reference,
    device_reference,
    fiscal_device_catalogue,
    integrable_devices,
    locale_reference,
    pos_payment_reference,
    pos_terminal_catalogue,
    product_categories,
    provider_kind_reference,
    provider_reference,
    reference_metadata,
    renderer_reference,
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

__version__ = "0.9.0"

__all__ = [
    "business_types",
    "business_supplies",
    "business_schemes",
    "business_profile",
    "VatScheme",
    "BusinessType",
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
    # reference views (JSON-safe, for a host's fiscal-setup UI)
    "country_reference", "all_country_references", "product_categories",
    "reference_metadata",
    "device_reference", "all_device_references", "pos_payment_reference",
    # punto cassa: RT, reparti IVA, documento commerciale
    "PosPaymentMethod", "PaymentMeansMapping", "PAYMENT_MEANS_BY_POS",
    "payment_means_for", "VatDepartment", "DepartmentTable", "ReceiptReference",
    "link_receipt", "check_pos_alignment", "validate_lottery_code",
    # il documento commerciale e la sua copia stampabile
    "CommercialDocument", "ReceiptPayment", "receipt_lines", "print_receipt",
    "check_receipt", "invoice_pdf", "receipt_pdf", "PdfBranding", "PdfUnavailable",
    "PdfFontUnavailable", "needs_unicode_font", "locales_without_font", "system_unicode_font", "font_for_text",
    "LOTTERY_CODE_PATTERN", "REQUIREMENT_KINDS", "REPORTING_KINDS",
    "CONNECTIONS", "DEVICE_CAPABILITIES", "LOCALES_BY_COUNTRY", "catalog_for",
    "translation_keys", "SETUP_FLAGS", "setup_steps", "setup_caveats",
    "FiscalDeviceRegime", "FISCAL_DEVICE_REGIMES", "FISCAL_DEVICES_VERIFIED_AS_OF",
    "device_regime", "countries_requiring_a_device",
    # catalogo del ferro: chi produce cosa, che protocollo parla
    "FiscalDeviceModel", "PosTerminal", "FISCAL_DEVICE_MODELS", "POS_TERMINALS",
    "fiscal_device_model", "pos_terminal", "devices_for_country",
    "terminals_for_country", "fiscal_device_catalogue", "pos_terminal_catalogue",
    "TERMINAL_CAPABILITIES", "INTEGRATION_CHANNELS", "DEVICE_KINDS",
    "programmable_terminals", "drivable_devices", "by_channel", "devices_of_kind",
    "integrable_devices",
    "provider_reference", "all_provider_references", "provider_kind_reference",
    "renderer_reference", "all_renderer_references", "locale_reference",
    # setup guides + localized labels
    "SetupStep", "setup_guide", "all_setup_guides", "credential_fields",
    "translate", "available_locales", "normalize_locale", "locale_for_country",
    "LOCALES", "DEFAULT_LOCALE",
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
    "parse_invoice", "parse_invoices", "parse_fattura_batch",
    # ricevute SdI: leggere la risposta, non solo mandare la domanda
    "SdiReceipt", "SdiError", "SDI_RECEIPT_TYPES", "parse_sdi_receipt",
    "receipt_kind_from_filename", "detect_standard", "parse_ubl_xml", "parse_cii_xml",
    "parse_fattura_xml", "compare_declared_totals",
    # naming + serde + errors
    "sdi_filename", "to_base36",
    "invoice_to_dict", "invoice_from_dict", "invoice_to_json", "invoice_from_json",
    "EInvoiceError", "ValidationError", "ProviderConfigError", "ProviderError",
    "TransportError", "RenderError", "IllegalTransition", "SigningUnavailable",
    "__version__",
]
