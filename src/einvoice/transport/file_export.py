"""File export transport — the portal-independent "give me the file" channel.

Writes the rendered document (FatturaPA, UBL, …) to ``extra['output_dir']`` (if
set) and returns the bytes + SDI/UBL filename. Upload it anywhere — commercialista
software, the AdE portal, a generic SDI intermediary — or archive it.
"""
from __future__ import annotations

import os

from ..formats.base import RenderedDocument
from ..models import Invoice
from .base import STATUS_EXPORTED, STATUS_UNKNOWN, SubmissionResult, Transport, TransportStatus


class FileExportTransport(Transport):
    name = "file"

    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult:
        out_dir = self.config.extra.get("output_dir")
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, rendered.filename), "wb") as fh:
                fh.write(rendered.content)
        return SubmissionResult(
            transport=self.name,
            status=STATUS_EXPORTED,
            filename=rendered.filename,
            message=f"{rendered.standard.upper()} esportato"
            + (f" in {out_dir}" if out_dir else ""),
        )

    async def fetch_status(self, provider_id: str) -> TransportStatus:
        return TransportStatus(
            transport=self.name, provider_id=provider_id, status=STATUS_UNKNOWN,
            message="L'export su file non traccia lo stato SDI/PEPPOL.",
        )
