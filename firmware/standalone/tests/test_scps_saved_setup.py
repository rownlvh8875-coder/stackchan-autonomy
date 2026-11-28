"""Validate local setup sources with synthetic secret values."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from scps_saved_setup import load_openai_key, parse_wlan_key  # noqa: E402


def test_only_selected_file_supplies_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-environment-key")
    path = tmp_path / ".env"
    assert load_openai_key(path) is None
    path.write_text('OPENAI_API_KEY="synthetic-configured-key"\nANOTHER_KEY=unused\n')
    assert load_openai_key(path) == "synthetic-configured-key"
    path.write_text('OPENAI_API_KEY=""\n')
    assert load_openai_key(path) is None


@pytest.mark.parametrize(
    ("authentication", "protected", "key", "expected"),
    [
        ("WPA2PSK", "false", "synthetic-password", (b"test", "synthetic-password")),
        ("WPA2PSK", "true", "synthetic-encrypted", None),
        ("WPA2PSK", "", "synthetic-password", None),
        ("WPA2PSK", "false", "short", None),
        ("WPA2", "false", "synthetic-password", None),
    ],
)
def test_only_usable_personal_profile_supplies_wifi(authentication, protected, key, expected):
    profile = (
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
        "<MSM><security><authEncryption>"
        f"<authentication>{authentication}</authentication><useOneX>false</useOneX>"
        "</authEncryption><sharedKey>"
        f"<protected>{protected}</protected><keyMaterial>{key}</keyMaterial>"
        "</sharedKey></security></MSM></WLANProfile>"
    )
    assert parse_wlan_key(b"test", profile) == expected
