"""Lazy-httpx HTTP helper for the network transports.

``httpx`` is optional (``pip install einvoice[providers]``): imported only when a
transport actually performs I/O, so the core + file export work without it.
"""
from __future__ import annotations

from typing import Any

from ..errors import EInvoiceError, ProviderError


def _import_httpx():
    try:
        import httpx
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise EInvoiceError(
            "httpx non installato — `pip install einvoice[providers]` per i transport di rete."
        ) from exc
    return httpx


async def request_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json: Any = None,
    data: Any = None,
    timeout: float = 30.0,
) -> dict:
    httpx = _import_httpx()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(method, url, headers=headers, json=json, data=data)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Errore di rete verso {url}: {exc}") from exc
    if resp.status_code >= 400:
        raise ProviderError(
            f"HTTP {resp.status_code} da {url}: {resp.text[:300]}",
            status="error",
            raw={"status_code": resp.status_code, "body": resp.text[:1000]},
        )
    try:
        return resp.json()
    except ValueError:
        return {"_raw_text": resp.text}
