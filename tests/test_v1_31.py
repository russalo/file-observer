"""v1.31 — promotion pass: capture-metadata (`image` EXIF + `video`) → stable (falsify-first).

Designation-only: the v1.16 image-EXIF fields and the whole v1.17–1.20 `video` namespace
graduate provisional → stable (settled logic since ship + exiftool-oracle-validated + corpus-proven
+ red-teamed). The scan manifest is byte-identical except the version stamps — stability lives only
in `--schema` (the v1.14/v1.23 pattern). The held sets STAY provisional (not swept up): the chatlog
family, `presentation` (v1.24, too young), `audio` (v1.25, too young), and format_signatures/
is_polyglot (held-by-design).

SCHEMA 1.16→1.17 (promotion = contract change); LOGIC unchanged (1.15.3); SCANNER 1.30.2→1.31.0.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    PROVISIONAL_SPECIALIST_FIELDS,
    build_schema_document,
    manifest_to_json,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"

IMAGE_EXIF = ("make", "model", "orientation", "datetime_original", "gps_present", "xmp_present")
VIDEO_FIELDS = ("codec", "duration_s", "width", "height", "creation_date",
                "creation_date_qt", "make", "model", "gps_present", "gps_source")


def _schema():
    return build_schema_document()


def _ns_stability(doc, ns):
    return {f["name"]: f["stability"] for f in doc["specialists"]["fields"][ns]}


def test_version_surfaces():
    # floors, not exact — a later patch may supersede this release.
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 31, 0), f"got {SCANNER_VERSION!r}"
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 17), SCHEMA_VERSION
    # LOGIC is UNCHANGED by a designation-only promotion (v1.14/v1.23 precedent).
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 15, 3), f"LOGIC: {LOGIC_VERSION!r}"


class TestPromotedToStable:
    def test_image_namespace_fully_stable(self):
        img = _ns_stability(_schema(), "image")
        for f in IMAGE_EXIF:
            assert img[f] == "stable", f"image.{f} should be stable after v1.31"
        # dimensions were already stable (since 0.5) — the whole namespace is now stable
        for f in ("width", "height", "bit_depth"):
            assert img[f] == "stable", f"image.{f}"
        assert set(v for v in img.values()) == {"stable"}, "image namespace must be ALL stable"

    def test_video_namespace_fully_stable(self):
        vid = _ns_stability(_schema(), "video")
        for f in VIDEO_FIELDS:
            assert vid[f] == "stable", f"video.{f} should be stable after v1.31"
        assert set(v for v in vid.values()) == {"stable"}, "video namespace must be ALL stable"

    def test_promoted_tuples_out_of_provisional_registry(self):
        for f in IMAGE_EXIF:
            assert ("image", f) not in PROVISIONAL_SPECIALIST_FIELDS, f"image.{f} still provisional"
        for f in VIDEO_FIELDS:
            assert ("video", f) not in PROVISIONAL_SPECIALIST_FIELDS, f"video.{f} still provisional"


class TestHeldSetsStayProvisional:
    """The promotion must not sweep up the young or alpha-locked namespaces."""

    def test_chatlog_family_held(self):
        cl = _ns_stability(_schema(), "chatlog")
        for f in ("content_shape", "speaker_turn_counts", "speaker_turn_chars", "alternation"):
            assert cl[f] == "provisional", f"chatlog.{f} must stay provisional (alpha-locked)"

    def test_presentation_and_audio_held_too_young(self):
        doc = _schema()
        pres = _ns_stability(doc, "presentation")
        aud = _ns_stability(doc, "audio")
        for f in ("slide_count", "title", "author", "application"):
            assert pres[f] == "provisional", f"presentation.{f} (v1.24, too young) must stay provisional"
        for f in ("format", "bitrate", "duration_s", "title", "artist", "album", "year"):
            assert aud[f] == "provisional", f"audio.{f} (v1.25, too young) must stay provisional"

    def test_held_by_design_stays_provisional(self):
        fr = {x["name"]: x["stability"] for x in _schema()["manifest"]["FileRecord"]}
        assert fr["format_signatures"] == "provisional"
        assert fr["is_polyglot"] == "provisional"


# The emitted shape of EVERY promoted field (bounded-observation `null` is always allowed).
# Types per the extraction contract: string-or-null, except the bool presence flags and the
# numeric dims/duration. A designation-only promotion must not change any of these.
IMAGE_FIELD_TYPES = {
    "make": (str,), "model": (str,), "orientation": (str, int),
    "datetime_original": (str,), "gps_present": (bool,), "xmp_present": (bool,),
}
VIDEO_FIELD_TYPES = {
    "codec": (str,), "duration_s": (int, float), "width": (int,), "height": (int,),
    "creation_date": (str,), "creation_date_qt": (str,), "make": (str,), "model": (str,),
    "gps_present": (bool,), "gps_source": (str,),
}


class TestDesignationOnly:
    """Promotion changes the stability promise, not scan output."""

    @pytest.fixture(scope="class")
    def manifest(self):
        # scan once for the whole class (scanning fixtures + extracting is expensive)
        return Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()

    def test_stability_does_not_leak_into_manifest(self, manifest):
        blob = manifest_to_json(manifest)
        assert '"stability"' not in blob, "stability is a --schema-only surface, not the manifest"

    def test_promoted_field_shapes_unchanged(self, manifest):
        # where the image/video namespaces appear, EVERY promoted field keeps its emitted shape
        # (promotion is designation-only — no value/type change).
        def check(ns_val, types, label):
            for f, ok in types.items():
                if f in ns_val:
                    v = ns_val[f]
                    assert v is None or isinstance(v, ok), f"{label}.{f}={v!r} (want {ok} or None)"
        for r in manifest.files:
            img = (r.specialist_metadata or {}).get("image")
            if img:
                check(img, IMAGE_FIELD_TYPES, "image")
            vid = (r.specialist_metadata or {}).get("video")
            if vid:
                check(vid, VIDEO_FIELD_TYPES, "video")

    def test_manifest_deterministic(self):
        # genuinely needs TWO independent scans — do not share the cached fixture
        a = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()
        b = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()
        assert a.manifest_checksum == b.manifest_checksum
