"""Tiny public-format fixtures; no model download or device in the test suite."""

import hashlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def fixture_assets(tmp_path, monkeypatch):
    import prepare_wakenet_assets as assets

    files = []
    offset = 160
    for name, payload in (
        ("_MODEL_INFO_", b"test"),
        ("wn9_index", b"index"),
        ("wn9_data", b"data"),
    ):
        (tmp_path / name).write_bytes(payload)
        files.append(
            {
                "file": name,
                "offset": offset,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        offset += len(payload)
    monkeypatch.setattr(assets, "FILES", files)
    monkeypatch.setattr(assets, "PACK_BYTES", offset)
    # Independent format fixture, fixed little endian and canonical ordering.
    expected = struct.pack("<I32sI", 1, b"wn9l_histackchan_tts3", 3)
    expected += b"".join(
        struct.pack("<32sII", f["file"].encode(), f["offset"], f["bytes"]) for f in files
    )
    expected += b"testindexdata"
    monkeypatch.setattr(assets, "PACK_SHA256", hashlib.sha256(expected).hexdigest())
    return assets, expected


def test_exact_sdk_pack_and_integrity(tmp_path, monkeypatch):
    assets, expected = fixture_assets(tmp_path, monkeypatch)
    assert assets.build_pack(tmp_path) == expected
    (tmp_path / "wn9_data").write_bytes(b"bad!")
    with pytest.raises(ValueError):
        assets.build_pack(tmp_path)


def test_wrong_pack_hash_missing_and_oversized_files_rejected(tmp_path, monkeypatch):
    assets, _ = fixture_assets(tmp_path, monkeypatch)
    monkeypatch.setattr(assets, "PACK_SHA256", "0" * 64)
    with pytest.raises(ValueError):
        assets.build_pack(tmp_path)
    (tmp_path / "wn9_data").write_bytes(b"extra-data")
    with pytest.raises(ValueError):
        assets.build_pack(tmp_path)
    (tmp_path / "wn9_index").unlink()
    with pytest.raises((OSError, ValueError)):
        assets.build_pack(tmp_path)


def test_pack_output_is_exclusive_and_manifest_cannot_authorize_install(
    tmp_path, monkeypatch, capsys
):
    assets, expected = fixture_assets(tmp_path, monkeypatch)
    out = tmp_path / "model.bin"
    assert assets.main(["--source", str(tmp_path), "--out", str(out)]) == 0
    assert out.read_bytes() == expected
    assert '"install_authorized":false' in capsys.readouterr().out
    out.write_bytes(b"preserve-local-file")
    assert assets.main(["--source", str(tmp_path), "--out", str(out)]) == 2
    assert out.read_bytes() == b"preserve-local-file"
