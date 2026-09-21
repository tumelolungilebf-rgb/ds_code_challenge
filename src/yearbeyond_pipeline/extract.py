"""Extract H3 resolution-8 features through Amazon S3 Select."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .sources import BUCKET, MIXED_RESOLUTION_OBJECT

LEVEL_8_SELECT_SQL = (
    "SELECT * FROM S3Object[*].features[*] AS s "
    "WHERE s.properties.resolution = 8"
)


class ExtractionError(RuntimeError):
    """Raised when an S3 Select response cannot be consumed safely."""


@dataclass(frozen=True)
class SelectExtraction:
    """Features and service statistics returned by one completed S3 Select call."""

    features: list[dict[str, Any]]
    statistics: dict[str, int]

    def as_feature_collection(self) -> dict[str, Any]:
        """Return the extracted records as a GeoJSON FeatureCollection."""
        return {"type": "FeatureCollection", "features": self.features}


def _parse_line(line: str, record_number: int) -> dict[str, Any]:
    """Parse and type-check one newline-delimited JSON record."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise ExtractionError(
            f"S3 Select record {record_number} is not valid JSON"
        ) from error
    if not isinstance(record, dict):
        raise ExtractionError(f"S3 Select record {record_number} is not an object")
    return record


def consume_select_events(events: Iterable[dict[str, Any]]) -> SelectExtraction:
    """Consume the event stream, including byte and UTF-8 splits between events."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    text_buffer = ""
    features: list[dict[str, Any]] = []
    statistics: dict[str, int] = {}
    completed = False

    for event in events:
        if "Records" in event:
            payload = event["Records"].get("Payload", b"")
            if not isinstance(payload, bytes):
                raise ExtractionError("S3 Select record payload is not bytes")
            text_buffer += decoder.decode(payload, final=False)
            lines = text_buffer.split("\n")
            text_buffer = lines.pop()
            for line in lines:
                if line.strip():
                    features.append(_parse_line(line, len(features) + 1))
        elif "Stats" in event:
            details = event["Stats"].get("Details", {})
            if isinstance(details, dict):
                statistics = {
                    str(key): int(value)
                    for key, value in details.items()
                    if isinstance(value, int) and not isinstance(value, bool)
                }
        elif "End" in event:
            completed = True
        elif "Progress" in event or "Cont" in event:
            continue
        else:
            raise ExtractionError(
                f"Unexpected S3 Select event: {', '.join(sorted(event)) or 'empty'}"
            )

    try:
        text_buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError as error:
        raise ExtractionError("S3 Select ended inside a UTF-8 character") from error

    if text_buffer.strip():
        features.append(_parse_line(text_buffer, len(features) + 1))
    if not completed:
        raise ExtractionError("S3 Select response ended without an End event")
    return SelectExtraction(features=features, statistics=statistics)


def extract_level8_features(client: Any) -> SelectExtraction:
    """Run the required server-side resolution-8 query and consume it fully."""
    response = client.select_object_content(
        Bucket=BUCKET,
        Key=MIXED_RESOLUTION_OBJECT,
        ExpressionType="SQL",
        Expression=LEVEL_8_SELECT_SQL,
        InputSerialization={"JSON": {"Type": "DOCUMENT"}},
        OutputSerialization={"JSON": {"RecordDelimiter": "\n"}},
    )
    payload = response["Payload"]
    try:
        return consume_select_events(payload)
    finally:
        close = getattr(payload, "close", None)
        if callable(close):
            close()
