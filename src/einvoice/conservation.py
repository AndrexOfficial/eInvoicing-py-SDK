"""Conservazione digitale a norma — export package + provider-upload scaffold.

Italian law (CAD art. 43-44, DPCM 3/12/2013, linee guida AgID) requires
e-invoices to be preserved for 10 years by an accredited *conservatore*
(Aruba DocFly, InfoCert, Namirial, …) with signed + timestamped preservation
packages. **This module is NOT that service.** It produces an honest,
verifiable export bundle — every invoice file plus a ``manifest.json`` and a
minimal IPdA-like ``pdd_index.xml`` (inspired by UNI SInCRO 11386, *not* a
conformant IPdA: no signature, no timestamp) — ready to be handed to an
accredited provider, which re-indexes/re-signs on ingestion.

:class:`ConservationProvider` is the pluggable upload interface;
:class:`WebhookConservationProvider` POSTs the ZIP to a configured URL
(e.g. an internal bridge that forwards to DocFly's SFTP/API).
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

__all__ = [
    "build_conservation_package",
    "ConservationProvider",
    "WebhookConservationProvider",
]


def _record_bytes(record: dict) -> bytes:
    if record.get("content") is not None:
        content = record["content"]
        return content.encode("utf-8") if isinstance(content, str) else content
    path = record.get("path")
    if not path:
        raise ValueError(f"record {record.get('filename')!r}: serve 'content' o 'path'")
    return Path(path).read_bytes()


def _pdd_index_xml(entries: list[dict], created: str) -> bytes:
    """Minimal IPdA-like index (UNI SInCRO 11386-inspired, NOT conformant)."""
    docs = "\n".join(
        "  <Documento>\n"
        f"    <NomeFile>{escape(e['filename'])}</NomeFile>\n"
        f"    <Impronta algoritmo=\"SHA-256\">{e['sha256']}</Impronta>\n"
        f"    <NumeroFattura>{escape(e.get('invoice_number') or '')}</NumeroFattura>\n"
        f"    <DataFattura>{escape(e.get('invoice_date') or '')}</DataFattura>\n"
        f"    <IdFiscaleControparte>{escape(e.get('counterpart_vat') or '')}</IdFiscaleControparte>\n"
        "  </Documento>"
        for e in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Indice IPdA-like (ispirato a UNI SInCRO 11386). NON è un IPdA conforme:\n"
        "     manca firma e marca temporale del responsabile della conservazione. -->\n"
        f'<PacchettoDiDistribuzione generato="{created}" documenti="{len(entries)}">\n'
        f"{docs}\n"
        "</PacchettoDiDistribuzione>\n"
    ).encode()


def build_conservation_package(
    records: list[dict],
    out_dir: str | os.PathLike,
    *,
    package_name: str | None = None,
) -> Path:
    """Build a conservazione export ZIP and return its path.

    Each *record* is a dict with:

    * ``filename`` (required) — name inside the package (``….xml`` / ``….xml.p7m``)
    * ``content`` (bytes) **or** ``path`` (filesystem path to read)
    * ``invoice_number``, ``invoice_date`` (ISO string), ``counterpart_vat`` — metadata

    The ZIP contains every file, a ``manifest.json`` index (filename, SHA-256,
    invoice number/date, counterpart VAT) and a minimal ``pdd_index.xml``
    (IPdA-like — see module docstring for what it is *not*).
    """
    if not records:
        raise ValueError("nessun documento da conservare")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = package_name or f"conservazione_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.zip"
    if not name.endswith(".zip"):
        name += ".zip"
    zip_path = out / name

    entries: list[dict] = []
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rec in records:
            filename = rec.get("filename")
            if not filename:
                raise ValueError("record senza 'filename'")
            if filename in seen:
                raise ValueError(f"filename duplicato nel pacchetto: {filename!r}")
            seen.add(filename)
            content = _record_bytes(rec)
            entry = {
                "filename": filename,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "invoice_number": rec.get("invoice_number"),
                "invoice_date": str(rec["invoice_date"]) if rec.get("invoice_date") else None,
                "counterpart_vat": rec.get("counterpart_vat"),
            }
            entries.append(entry)
            zf.writestr(filename, content)

        manifest = {
            "format": "einvoice-conservation/1",
            "created": created,
            "algorithm": "SHA-256",
            "documents": entries,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("pdd_index.xml", _pdd_index_xml(entries, created))
    return zip_path


class ConservationProvider(ABC):
    """Upload interface towards an accredited conservazione service.

    Concrete adapters (Aruba DocFly, InfoCert, …) implement :meth:`upload`
    and return a provider-side reference (ticket/package id).
    """

    @abstractmethod
    async def upload(self, package_path: str | os.PathLike) -> str:
        """Upload the package; return a provider reference id."""
        ...


class WebhookConservationProvider(ConservationProvider):
    """POSTs the ZIP (multipart) to a configured URL — honest scaffold.

    Useful as a bridge: point it at an internal endpoint that forwards to the
    real conservatore (DocFly API/SFTP, …). Requires ``httpx``
    (``pip install einvoice[providers]``).
    """

    def __init__(self, url: str, *, headers: dict | None = None, timeout: float = 60.0):
        if not url:
            raise ValueError("URL webhook conservazione mancante")
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    async def upload(self, package_path: str | os.PathLike) -> str:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "l'upload conservazione richiede 'httpx': pip install einvoice[providers]"
            ) from exc

        path = Path(package_path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    self.url,
                    headers=self.headers,
                    files={"package": (path.name, fh, "application/zip")},
                )
        resp.raise_for_status()
        try:
            data = resp.json()
            ref = data.get("id") or data.get("reference")
            if ref:
                return str(ref)
        except Exception:
            pass
        return f"{resp.status_code}:{path.name}"
