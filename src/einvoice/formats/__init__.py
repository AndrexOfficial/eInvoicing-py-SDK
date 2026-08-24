"""Country / format renderers."""
from .base import (
    InvoiceRenderer,
    RenderedDocument,
    available_renderers,
    get_renderer,
    register_renderer,
)
from .fatturapa import FatturaPARenderer, build_fattura_xml
from .ubl import UblRenderer, build_ubl_xml

register_renderer("fatturapa", FatturaPARenderer)
register_renderer("ubl", UblRenderer)
register_renderer("peppol", UblRenderer)  # alias

__all__ = [
    "InvoiceRenderer",
    "RenderedDocument",
    "get_renderer",
    "register_renderer",
    "available_renderers",
    "FatturaPARenderer",
    "UblRenderer",
    "build_fattura_xml",
    "build_ubl_xml",
]
