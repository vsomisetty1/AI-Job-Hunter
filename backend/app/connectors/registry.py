"""Connector registry: source name -> connector class."""

from app.connectors.ashby import AshbyConnector
from app.connectors.base import Connector
from app.connectors.greenhouse import GreenhouseConnector
from app.connectors.http import HttpFetcher
from app.connectors.lever import LeverConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.source: c for c in (GreenhouseConnector, LeverConnector, AshbyConnector)
}
SOURCES = tuple(CONNECTORS)


class UnknownSourceError(ValueError):
    pass


def build_connectors(http: HttpFetcher) -> dict[str, Connector]:
    return {source: cls(http) for source, cls in CONNECTORS.items()}


def get_connector(connectors: dict[str, Connector], source: str) -> Connector:
    try:
        return connectors[source]
    except KeyError as exc:
        raise UnknownSourceError(f"unknown job board source: {source}") from exc
