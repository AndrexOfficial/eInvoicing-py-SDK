"""Transport adapters (channels)."""
from .aruba import ArubaTransport
from .base import (
    ArchiveStore,
    FileArchive,
    InvoiceStatus,
    ProviderConfig,
    Signer,
    SubmissionResult,
    Transport,
    TransportConfig,
    TransportStatus,
)
from .fattureincloud import FattureInCloudTransport, FattureInCloudXmlTransport
from .file_export import FileExportTransport
from .generic_hub import GenericHubTransport
from .peppol import PeppolTransport
from .providers import (
    PROVIDER_KINDS,
    PROVIDER_PRESETS,
    ProviderPreset,
    available_providers,
    preset_for,
    providers_for_country,
    providers_of_kind,
    transport_for_provider,
)
from .registry import available_transports, get_transport, register_transport
from .zucchetti import ZucchettiTransport

__all__ = [
    "Transport", "TransportConfig", "ProviderConfig",
    "SubmissionResult", "TransportStatus", "InvoiceStatus",
    "Signer", "ArchiveStore", "FileArchive",
    "FileExportTransport", "FattureInCloudTransport", "FattureInCloudXmlTransport",
    "ArubaTransport",
    "ZucchettiTransport", "PeppolTransport", "GenericHubTransport",
    "get_transport", "register_transport", "available_transports",
    "ProviderPreset", "PROVIDER_PRESETS", "PROVIDER_KINDS",
    "available_providers", "preset_for",
    "providers_for_country", "providers_of_kind", "transport_for_provider",
]
