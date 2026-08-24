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
]
