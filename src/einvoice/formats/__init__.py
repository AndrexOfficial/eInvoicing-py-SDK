"""Country / format renderers."""
from .base import (
    InvoiceRenderer,
    RenderedDocument,
    available_renderers,
    get_renderer,
    register_renderer,
)
from .cii import FACTURX_PROFILES, CiiRenderer, build_cii_xml
from .fatturapa import FatturaPARenderer, build_fattura_xml
from .ubl import UblRenderer, build_ubl_xml

register_renderer("fatturapa", FatturaPARenderer)
register_renderer("ubl", UblRenderer)
register_renderer("peppol", UblRenderer)   # alias
register_renderer("cii", CiiRenderer)
register_renderer("facturx", CiiRenderer)  # alias — Factur-X is CII
register_renderer("zugferd", CiiRenderer)  # alias — ZUGFeRD is CII

__all__ = [
    "InvoiceRenderer",
    "RenderedDocument",
    "get_renderer",
    "register_renderer",
    "available_renderers",
    "FatturaPARenderer",
    "UblRenderer",
    "CiiRenderer",
    "FACTURX_PROFILES",
    "build_fattura_xml",
    "build_ubl_xml",
    "build_cii_xml",
]
