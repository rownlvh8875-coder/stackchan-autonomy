"""Read explicitly selected local SCPS inputs without exporting profiles."""

from __future__ import annotations

import ctypes
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from scps_reference import validate_api_key, validate_wifi_credentials

_WLAN_CONNECTED = 1
_WLAN_CURRENT_CONNECTION = 7
_WLAN_PROFILE_GET_PLAINTEXT_KEY = 4
_PROFILE_NS = {"w": "http://www.microsoft.com/networking/WLAN/profile/v1"}
_Guid = ctypes.c_uint32 * 4


class _Interface(ctypes.Structure):
    _fields_ = [
        ("guid", _Guid),
        ("description", ctypes.c_wchar * 256),
        ("state", ctypes.c_uint32),
    ]


class _ConnectionPrefix(ctypes.Structure):
    """WLAN_CONNECTION_ATTRIBUTES through wlanAssociationAttributes.dot11Ssid."""

    _fields_ = [
        ("state", ctypes.c_uint32),
        ("mode", ctypes.c_uint32),
        ("profile_name", ctypes.c_wchar * 256),
        ("ssid_size", ctypes.c_uint32),
        ("ssid", ctypes.c_ubyte * 32),
    ]


def load_openai_key(path: Path) -> str | None:
    try:
        from dotenv import dotenv_values

        with path.open(encoding="utf-8-sig") as config:
            key = dotenv_values(stream=config, interpolate=False).get("OPENAI_API_KEY")
        if key is not None:
            validate_api_key(key)
        return key
    except (ImportError, OSError, ValueError):
        return None


def parse_wlan_key(ssid: bytes, profile_xml: str) -> tuple[bytes, str] | None:
    try:
        profile = ET.fromstring(profile_xml)
    except ET.ParseError:
        return None
    security = profile.find("w:MSM/w:security", _PROFILE_NS)
    if security is None:
        return None
    auth = security.findtext("w:authEncryption/w:authentication", namespaces=_PROFILE_NS)
    one_x = security.findtext("w:authEncryption/w:useOneX", namespaces=_PROFILE_NS)
    protected = security.findtext("w:sharedKey/w:protected", namespaces=_PROFILE_NS)
    password = security.findtext("w:sharedKey/w:keyMaterial", namespaces=_PROFILE_NS)
    if (
        auth not in {"WPA2PSK", "WPA3SAE"}
        or one_x == "true"
        or protected != "false"
        or not password
    ):
        return None
    try:
        validate_wifi_credentials(ssid, password)
    except ValueError:
        return None
    return ssid, password


def _connected_profile(*, reveal_key: bool) -> tuple[bytes, str] | None:
    if sys.platform != "win32":
        return None
    wlan = ctypes.WinDLL("wlanapi.dll", winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    byref = ctypes.byref
    version, handle = ctypes.c_uint32(), ctypes.c_void_p()
    if wlan.WlanOpenHandle(2, None, byref(version), byref(handle)) != 0:
        return None
    try:
        interfaces = ctypes.c_void_p()
        if wlan.WlanEnumInterfaces(handle, None, byref(interfaces)) != 0 or not interfaces.value:
            return None
        try:
            count = ctypes.c_uint32.from_address(interfaces.value).value
            # WLAN_INTERFACE_INFO_LIST has two DWORDs before the inline array.
            items = (_Interface * count).from_address(interfaces.value + 8)
            connected = [item for item in items if item.state == _WLAN_CONNECTED]
            if len(connected) != 1:
                return None
            guid = _Guid.from_buffer_copy(connected[0].guid)
        finally:
            wlan.WlanFreeMemory(interfaces)

        size, data = ctypes.c_uint32(), ctypes.c_void_p()
        if (
            wlan.WlanQueryInterface(
                handle, byref(guid), _WLAN_CURRENT_CONNECTION, None, byref(size), byref(data), None
            )
            != 0
            or not data.value
        ):
            return None
        try:
            if size.value < ctypes.sizeof(_ConnectionPrefix):
                return None
            current = _ConnectionPrefix.from_address(data.value)
            if current.state != _WLAN_CONNECTED or not 1 <= current.ssid_size <= 32:
                return None
            name = current.profile_name
            ssid = bytes(current.ssid[: current.ssid_size])
            if not name:
                return None
        finally:
            wlan.WlanFreeMemory(data)

        xml = ctypes.c_void_p()
        flags = ctypes.c_uint32(_WLAN_PROFILE_GET_PLAINTEXT_KEY if reveal_key else 0)
        if (
            wlan.WlanGetProfile(
                handle, byref(guid), ctypes.c_wchar_p(name), None, byref(xml), byref(flags), None
            )
            != 0
            or not xml.value
        ):
            return None
        try:
            return ssid, ctypes.wstring_at(xml.value)
        finally:
            wlan.WlanFreeMemory(xml)
    finally:
        wlan.WlanCloseHandle(handle, None)


def load_connected_wifi() -> tuple[bytes, str] | None:
    try:
        profile = _connected_profile(reveal_key=True)
    except OSError:
        return None
    return parse_wlan_key(*profile) if profile is not None else None
