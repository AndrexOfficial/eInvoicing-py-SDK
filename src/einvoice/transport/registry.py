"""Transport registry — resolve a channel by name."""
from __future__ import annotations

from ..errors import ProviderConfigError
from .aruba import ArubaTransport
from .base import Transport, TransportConfig
from .fattureincloud import FattureInCloudTransport, FattureInCloudXmlTransport
from .file_export import FileExportTransport
from .generic_hub import GenericHubTransport
from .peppol import PeppolTransport
from .zucchetti import ZucchettiTransport

_REGISTRY: dict[str, type[Transport]] = {
    "file": FileExportTransport,
    "file_export": FileExportTransport,
    "xml_export": FileExportTransport,
    "fattureincloud": FattureInCloudTransport,
    # Same vendor, but uploads a pre-rendered FatturaPA instead of
    # letting FIC build one — for hosts that already persisted the XML.
    "fattureincloud_xml": FattureInCloudXmlTransport,
    "aruba": ArubaTransport,
    "zucchetti": ZucchettiTransport,
    "peppol": PeppolTransport,
    "sdi": FattureInCloudTransport,  # default SdI channel = via provider; override as needed
    # Intermediaries with no bespoke adapter. They share one REST shape, so they
    # run on the configurable hub rather than on vendor modules written against
    # contracts we cannot test — see ``generic_hub`` for the ``extra`` knobs.
    # Each needs at least ``base_url`` + a credential.
    "hub": GenericHubTransport,
    "infocert": GenericHubTransport,
    "notartel": GenericHubTransport,
    "wolters_kluwer": GenericHubTransport,
}


def available_transports() -> list[str]:
    return sorted(_REGISTRY)


def register_transport(name: str, cls: type[Transport]) -> None:
    _REGISTRY[name.lower()] = cls


def get_transport(name: str, config: TransportConfig | None = None) -> Transport:
    key = (name or "").lower()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ProviderConfigError(
            f"Transport sconosciuto: {name!r}. Disponibili: {', '.join(available_transports())}"
        )
    # The hub reads its own identity from the config, so a registry alias like
    # "infocert" keeps its name in results and error messages instead of "hub".
    return cls(config or TransportConfig(name=key))
