"""v1.27.0 — JSON Schema artifact for the manifest (generate + validation guard).

Falsify-first: fails against v1.26.0 (the schema/CLI surface doesn't exist), passes
once v1.27.0 lands.

Two drift-guards (RFC §5):
  (a) the committed docs/manifest.schema.json == the regenerated schema;
  (b) a real scan's manifest VALIDATES against the committed schema — the correctness
      proof a generator alone can't give.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from file_observer.scanner import (
    manifest_json_schema, manifest_json_schema_str,
    Scanner, ScannerConfig, manifest_to_json,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

jsonschema = pytest.importorskip("jsonschema")  # dev-only dep (the validation guard)

REPO = Path(__file__).resolve().parent.parent
COMMITTED = REPO / "docs" / "manifest.schema.json"


def _scan(d: Path, **cfg):
    return json.loads(manifest_to_json(Scanner(source_dir=Path(d), config=ScannerConfig(**cfg)).scan()))


# ---- the schema itself --------------------------------------------------------

def test_schema_is_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(manifest_json_schema())


def test_committed_schema_matches_generated():
    # drift-guard (a): regenerate on any manifest dataclass change (the docs/SCHEMA.md pattern)
    assert COMMITTED.exists(), "run: file-observer --schema --schema-format json-schema > docs/manifest.schema.json"
    assert COMMITTED.read_text(encoding="utf-8") == manifest_json_schema_str() + "\n", \
        "docs/manifest.schema.json is stale — regenerate it"


def test_schema_versioned_by_schema_version():
    s = manifest_json_schema()
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA_VERSION in s["$id"]
    assert SCHEMA_VERSION in s["title"]
    assert s["$ref"] == "#/$defs/ScanManifest"


# ---- (b) real manifests validate ----------------------------------------------

@pytest.fixture(scope="module")
def validator():
    return jsonschema.Draft202012Validator(json.loads(COMMITTED.read_text(encoding="utf-8")))


def _build(d: Path):
    (d / "doc.md").write_text("---\ntitle: T\nauthor: A\n---\n# H\n\nbody\n")
    (d / "data.txt").write_text("plain text\n")
    (d / "obj.json").write_text('{"k": 1}\n')


@pytest.mark.parametrize("cfg,label", [
    ({}, "specialists-off"),
    ({"enable_specialists": True}, "specialists-on"),
    ({"signing_key": "k"}, "signed"),
])
def test_real_manifest_validates(tmp_path, validator, cfg, label):
    _build(tmp_path)
    errs = list(validator.iter_errors(_scan(tmp_path, **cfg)))
    assert not errs, f"{label}: {[(list(e.path), e.message) for e in errs[:5]]}"


def test_empty_dir_manifest_validates(tmp_path, validator):
    assert not list(validator.iter_errors(_scan(tmp_path)))


def test_chatlog_manifest_validates(tmp_path, validator):
    (tmp_path / "chat.txt").write_text("User: hi there friend\nAssistant: hello, how are you\nUser: bye now\n" * 3)
    assert not list(validator.iter_errors(_scan(tmp_path, enable_specialists=True)))


def test_delta_manifest_validates(tmp_path, validator):
    (tmp_path / "x.txt").write_text("one\n")
    m1 = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()
    prev = tmp_path / "prev.json"
    prev.write_text(manifest_to_json(m1))
    (tmp_path / "y.txt").write_text("two\n")
    assert not list(validator.iter_errors(_scan(tmp_path, previous_manifest=str(prev))))


# ---- coverage shape: strict core, open provisional ----------------------------

def test_stable_core_required_and_typed():
    fr = manifest_json_schema()["$defs"]["FileRecord"]
    assert fr["additionalProperties"] is False  # closed structural record
    for f in ("path", "checksum_sha256", "size_bytes", "is_binary", "modified_at"):
        assert f in fr["required"], f
    assert fr["properties"]["path"]["type"] == "string"
    assert fr["properties"]["size_bytes"]["type"] == "integer"
    assert fr["properties"]["is_binary"]["type"] == "boolean"
    # honest-null fields are nullable, not required-omitted
    assert fr["properties"]["created_at"]["type"] == ["string", "null"]
    assert "created_at" in fr["required"]


def test_open_dicts_accept_arbitrary_keys(validator, tmp_path):
    # the provisional/namespace-keyed dicts are open objects (additionalProperties not false)
    fr = manifest_json_schema()["$defs"]["FileRecord"]
    sm = fr["properties"]["specialist_metadata"]
    # nullable open object: type is ["object","null"], no additionalProperties:false
    assert "object" in (sm["type"] if isinstance(sm["type"], list) else [sm["type"]])
    assert sm.get("additionalProperties") is not False


# ---- CLI surface --------------------------------------------------------------

def test_cli_emits_json_schema():
    out = subprocess.run([sys.executable, "-m", "file_observer.scanner",
                          "--schema", "--schema-format", "json-schema"],
                         capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    parsed = json.loads(out.stdout)
    assert parsed["$ref"] == "#/$defs/ScanManifest"
    assert parsed == manifest_json_schema()


# ---- version surfaces ---------------------------------------------------------

def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 27, 0), SCANNER_VERSION  # floor (superseded)
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 14, 1)  # floor — was 1.14.1 at v1.27; 1.15.0 at v1.29.0
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 16)  # floor — 1.16 held through v1.30.x; 1.17 at the v1.31 promotion pass
