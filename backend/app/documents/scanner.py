"""Antivirus scanning of uploads.

`ClamdScanner` speaks clamd's INSTREAM protocol over TCP (no extra
dependency). It fails CLOSED: if the scanner is configured but unreachable,
the upload is refused rather than accepted unscanned.
"""

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Protocol

from fastapi import status

from app.core.config import Settings
from app.core.exceptions import AppError, ServiceUnavailableError

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class MalwareDetectedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "malware_detected"


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None
    scanner: str = "none"


class VirusScanner(Protocol):
    name: str

    async def scan(self, data: bytes) -> ScanResult: ...


class NoopScanner:
    name = "none"

    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=True, scanner=self.name)


class ClamdScanner:
    name = "clamd"

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    async def _scan(self, data: bytes) -> str:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), _CHUNK):
                chunk = data[i : i + _CHUNK]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!L", 0))
            await writer.drain()
            reply = await reader.readuntil(b"\0")
            return reply.rstrip(b"\0").decode("utf-8", "replace")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def scan(self, data: bytes) -> ScanResult:
        try:
            reply = await asyncio.wait_for(self._scan(data), self.timeout)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            logger.error("virus scanner unavailable: %s", exc)
            raise ServiceUnavailableError(
                "The virus scanner is unavailable; upload refused. Try again later."
            ) from exc
        # "stream: OK" | "stream: <Signature> FOUND" | "<message> ERROR"
        body = reply.partition(": ")[2] or reply
        if body == "OK":
            return ScanResult(clean=True, scanner=self.name)
        if body.endswith(" FOUND"):
            signature = body.removesuffix(" FOUND")
            return ScanResult(clean=False, signature=signature, scanner=self.name)
        logger.error("virus scanner error: %s", reply)
        raise ServiceUnavailableError("The virus scanner could not scan the file; upload refused.")


def build_scanner(settings: Settings) -> VirusScanner:
    if settings.virus_scanner == "clamd":
        return ClamdScanner(
            settings.clamd_host, settings.clamd_port, settings.clamd_timeout_seconds
        )
    return NoopScanner()
