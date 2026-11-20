"""SCPS crypto code may be linked but never execute from HOLD app_main."""

from pathlib import Path


def test_secure_setup_is_dormant_and_separate_from_scfg():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    cmake = (root / "esp_app" / "main" / "CMakeLists.txt").read_text()
    crypto = (root / "esp_app" / "main" / "k151_secure_pc_setup.cpp").read_text()
    defaults = (root / "esp_app" / "sdkconfig.defaults").read_text()
    scfg = (root / "esp_app" / "main" / "k151_usb_scfg.cpp").read_text()
    assert "K151SecurePcSetup::compiled_link_marker()" in boot
    assert '"k151_secure_pc_setup.cpp"' in cmake
    assert "K151SecurePcSetup pairing" not in boot
    assert "psa_crypto_init(" not in boot
    assert "psa_generate_key(" not in boot
    assert "open_sealed(" not in boot
    assert "psa_raw_key_agreement(" in crypto
    assert "psa_aead_decrypt(" in crypto
    assert "PSA_ALG_HKDF(PSA_ALG_SHA_256)" in crypto
    assert "private_key_" in crypto
    assert "KSE1" not in scfg  # SCFG cannot handle secret bundles.
    assert "password=" not in defaults.lower()
    assert "sk-" not in defaults


def test_sas_display_is_separately_gated_without_lcd_init():
    root = Path(__file__).resolve().parents[1]
    header = (root / "esp_app" / "main" / "k151_setup_lvgl.hpp").read_text()
    view = (root / "esp_app" / "main" / "k151_setup_lvgl.cpp").read_text()
    assert "present_pairing_sas(" in header
    assert "trusted_display" in view
    assert "lvgl_lock_held" in view
    assert "lv_label_set_text(first_, digits.data())" in view
    assert "esp_lcd_panel_init(" not in view
    assert "esp_lcd_panel_reset(" not in view
