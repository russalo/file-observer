"""Golden-file tests — determinism verification by comparing JSON output across repeated scans."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scanner.scanner import Scanner, manifest_to_json


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestDeterminism:
    def test_repeated_scans_identical(self) -> None:
        """Two consecutive scans of the same directory produce semantically identical output."""
        scanner1 = Scanner(source_dir=FIXTURES)
        scanner2 = Scanner(source_dir=FIXTURES)

        m1 = scanner1.scan()
        m2 = scanner2.scan()

        j1 = json.loads(manifest_to_json(m1))
        j2 = json.loads(manifest_to_json(m2))

        # generated_at will differ — normalize it
        j1["generated_at"] = ""
        j2["generated_at"] = ""

        assert j1 == j2

    def test_file_order_deterministic(self) -> None:
        """Files appear in the same sorted order across scans."""
        s1 = Scanner(source_dir=FIXTURES)
        s2 = Scanner(source_dir=FIXTURES)

        paths1 = [f.path for f in s1.scan().files]
        paths2 = [f.path for f in s2.scan().files]

        assert paths1 == paths2
        assert paths1 == sorted(paths1)

    def test_tags_sorted(self) -> None:
        """Tags arrays are sorted within each record."""
        scanner = Scanner(source_dir=FIXTURES)
        manifest = scanner.scan()
        for f in manifest.files:
            assert f.tags == sorted(f.tags), f"{f.filename}: tags not sorted"

    def test_asset_matches_sorted(self) -> None:
        """Asset match arrays are sorted."""
        scanner = Scanner(source_dir=FIXTURES)
        manifest = scanner.scan()
        for f in manifest.files:
            assert f.asset_matches == sorted(f.asset_matches), f"{f.filename}: assets not sorted"

    def test_frontmatter_keys_sorted(self) -> None:
        """Frontmatter key arrays are sorted."""
        scanner = Scanner(source_dir=FIXTURES)
        manifest = scanner.scan()
        for f in manifest.files:
            if f.frontmatter.exists:
                assert f.frontmatter.keys == sorted(f.frontmatter.keys), (
                    f"{f.filename}: frontmatter keys not sorted"
                )

    def test_document_keys_sorted_for_json(self) -> None:
        """JSON document keys are sorted."""
        scanner = Scanner(source_dir=FIXTURES)
        manifest = scanner.scan()
        for f in manifest.files:
            if f.extension == ".json" and f.structural.document_keys:
                assert f.structural.document_keys == sorted(f.structural.document_keys)

    def test_checksum_stable(self) -> None:
        """Same file produces the same checksum across scans."""
        s1 = Scanner(source_dir=FIXTURES)
        s2 = Scanner(source_dir=FIXTURES)
        m1 = {f.path: f.checksum_sha256 for f in s1.scan().files}
        m2 = {f.path: f.checksum_sha256 for f in s2.scan().files}
        assert m1 == m2
