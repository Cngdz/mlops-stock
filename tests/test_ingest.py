"""Ingest must reject mixed source versions before making catalog changes."""
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.catalog import load_catalog

from scripts.day3_write_iceberg import TABLE_NAMES, ingest_sources, normalize_timestamp_precision


class IngestTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in TABLE_NAMES:
            pq.write_table(pa.table({"id": [1]}), self.root / f"{name}.parquet")
        self.catalog = Mock()
        self.catalog.namespace_exists.return_value = False

    def test_missing_last_file_creates_no_tables(self):
        (self.root / f"{TABLE_NAMES[-1]}.parquet").unlink()
        with self.assertRaises(FileNotFoundError):
            ingest_sources(self.catalog, self.root, "raw_new")
        self.catalog.create_namespace.assert_not_called()
        self.catalog.create_table.assert_not_called()

    def test_corrupt_last_footer_creates_no_tables(self):
        (self.root / f"{TABLE_NAMES[-1]}.parquet").write_bytes(b"not parquet")
        with self.assertRaises(pa.ArrowInvalid):
            ingest_sources(self.catalog, self.root, "raw_new")
        self.catalog.create_namespace.assert_not_called()
        self.catalog.create_table.assert_not_called()

    def test_partly_existing_namespace_cannot_mix_sources(self):
        self.catalog.namespace_exists.return_value = True
        self.catalog.table_exists.side_effect = lambda name: name == "raw_old.margin_cash_flow"
        with self.assertRaisesRegex(FileExistsError, "Use a new namespace"):
            ingest_sources(self.catalog, self.root, "raw_old")
        self.catalog.create_table.assert_not_called()

    def test_complete_batch_is_appended_once(self):
        ingest_sources(self.catalog, self.root, "raw_new")
        self.catalog.create_namespace.assert_called_once_with("raw_new")
        self.assertEqual(self.catalog.create_table.call_count, 4)
        self.assertEqual(self.catalog.create_table.return_value.append.call_count, 4)

    def test_real_sqlite_iceberg_roundtrip_and_retry(self):
        warehouse = self.root / "warehouse"
        warehouse.mkdir()
        catalog = load_catalog("test", **{
            "type": "sql", "uri": f"sqlite:///{(self.root / 'catalog.db').as_posix()}",
            "warehouse": str(warehouse),
        })
        try:
            source = pa.table({
                "id": [1], "stamp": pa.array([datetime(2025, 1, 1, tzinfo=timezone.utc)],
                                              type=pa.timestamp("ns", tz="UTC")),
            })
            for name in TABLE_NAMES:
                pq.write_table(source, self.root / f"{name}.parquet")
            ingest_sources(catalog, self.root, "raw_test")
            expected = normalize_timestamp_precision(source)
            for name in TABLE_NAMES:
                actual = catalog.load_table(f"raw_test.{name}").scan().to_arrow()
                self.assertTrue(actual.equals(expected, check_metadata=False))
            with self.assertRaises(FileExistsError):
                ingest_sources(catalog, self.root, "raw_test")
            for name in TABLE_NAMES:
                self.assertEqual(catalog.load_table(f"raw_test.{name}").scan().to_arrow().num_rows, 1)
        finally:
            catalog.engine.dispose()


if __name__ == "__main__":
    unittest.main()
