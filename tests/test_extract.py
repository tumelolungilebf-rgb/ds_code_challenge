"""Tests for safe S3 Select event-stream consumption."""

from __future__ import annotations

import json
import unittest

from yearbeyond_pipeline.extract import ExtractionError, consume_select_events


class ConsumeSelectEventsTests(unittest.TestCase):
    def test_reassembles_json_and_multibyte_characters_across_events(self) -> None:
        records = [
            {"type": "Feature", "properties": {"label": "Café"}},
            {"type": "Feature", "properties": {"label": "two"}},
        ]
        encoded = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records).encode(
            "utf-8"
        )
        accented_byte = encoded.index("é".encode("utf-8"))
        chunks = [
            encoded[: accented_byte + 1],
            encoded[accented_byte + 1 : len(encoded) - 3],
            encoded[len(encoded) - 3 :],
        ]
        events = [
            {"Records": {"Payload": chunks[0]}},
            {"Cont": {}},
            {"Records": {"Payload": chunks[1]}},
            {"Records": {"Payload": chunks[2]}},
            {
                "Stats": {
                    "Details": {
                        "BytesScanned": 100,
                        "BytesProcessed": 100,
                        "BytesReturned": len(encoded),
                    }
                }
            },
            {"End": {}},
        ]

        result = consume_select_events(events)

        self.assertEqual(result.features, records)
        self.assertEqual(result.statistics["BytesScanned"], 100)
        self.assertEqual(result.statistics["BytesReturned"], len(encoded))

    def test_rejects_response_without_end_event(self) -> None:
        events = [{"Records": {"Payload": b'{"type":"Feature"}\n'}}]

        with self.assertRaisesRegex(ExtractionError, "without an End event"):
            consume_select_events(events)

    def test_rejects_malformed_json(self) -> None:
        events = [{"Records": {"Payload": b'{broken}\n'}}, {"End": {}}]

        with self.assertRaisesRegex(ExtractionError, "not valid JSON"):
            consume_select_events(events)

    def test_rejects_unknown_event(self) -> None:
        with self.assertRaisesRegex(ExtractionError, "Unexpected S3 Select event"):
            consume_select_events([{"Mystery": {}}])


if __name__ == "__main__":
    unittest.main()
