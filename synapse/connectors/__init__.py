"""CDC / source connector plane."""

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.connectors.csv_drop import CsvDropConnector
from synapse.connectors.file_jsonl import JsonlFileConnector
from synapse.connectors.fhir_file import FhirDirectoryConnector
from synapse.connectors.hl7_file import Hl7DirectoryConnector
from synapse.connectors.mock_cdc import MockCdcConnector
from synapse.connectors.registry import ConnectorRegistry, build_default_registry
from synapse.connectors.saas_stub import (
    CrmStubConnector,
    MetricsStubConnector,
    SlackStubConnector,
)
from synapse.connectors.webhook_inbox import WebhookInboxConnector

__all__ = [
    "ChangeEvent",
    "Connector",
    "ConnectorWatermark",
    "CsvDropConnector",
    "JsonlFileConnector",
    "Hl7DirectoryConnector",
    "FhirDirectoryConnector",
    "MockCdcConnector",
    "WebhookInboxConnector",
    "CrmStubConnector",
    "SlackStubConnector",
    "MetricsStubConnector",
    "ConnectorRegistry",
    "build_default_registry",
]
