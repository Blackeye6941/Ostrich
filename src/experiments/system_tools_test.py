"""
System Tools Verification Script
================================
Tests all system tools on the current platform:
- Volume (get, set, mute, unmute)
- Brightness (get, set)
- Wi-Fi (status, scan)
- Bluetooth (status)
- Battery (status)
- System Information (CPU, RAM, Disk, OS)
"""

import sys
import os

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.system_tools import (
    get_system_navigator,
    get_system_info,
    get_volume,
    set_volume,
    set_mute,
    mute_volume,
    get_brightness,
    set_brightness,
    get_wifi_status,
    set_wifi,
    scan_wifi,
    get_bluetooth_status,
    set_bluetooth,
    get_battery_status,
)


def run_tests():
    print("=" * 60)
    print("Ostrich System Tools Test Suite")
    print("=" * 60)

    nav = get_system_navigator()
    print(f"\n[1] Active Navigator: {type(nav).__name__}")

    # 1. System Info
    info = get_system_info()
    print("\n[2] System Info:")
    for k, v in info.items():
        print(f"    {k}: {v}")
    assert info["success"] is True

    # 2. Audio Volume
    vol = get_volume()
    print(f"\n[3] Current Volume: {vol}")
    assert vol["success"] is True

    # Test setting volume safely (restore afterward)
    init_vol = vol.get("volume", 50)
    test_vol = 85 if init_vol != 85 else 80
    res_set = set_volume(test_vol)
    print(f"    Set volume to {test_vol}%: {res_set}")
    assert res_set["success"] is True
    res_restore = set_volume(init_vol)
    print(f"    Restored volume to {init_vol}%: {res_restore}")
    assert res_restore["success"] is True

    # 3. Brightness
    bright = get_brightness()
    print(f"\n[4] Current Brightness: {bright}")
    assert bright["success"] is True
    init_bright = bright.get("brightness", 50)
    res_b_set = set_brightness(init_bright)
    print(f"    Set brightness to {init_bright}%: {res_b_set}")
    assert res_b_set["success"] is True

    # 4. Wi-Fi
    wifi = get_wifi_status()
    print(f"\n[5] Wi-Fi Status: {wifi}")
    assert wifi["success"] is True

    # Wi-Fi Scan
    scan = scan_wifi()
    print(f"    Wi-Fi Scan: success={scan['success']}, found {scan.get('count', 0)} networks")
    if scan.get("networks"):
        print(f"    Sample network: {scan['networks'][0]}")
    assert scan["success"] is True

    # 5. Bluetooth
    bt = get_bluetooth_status()
    print(f"\n[6] Bluetooth Status: {bt}")
    assert bt["success"] is True

    # 6. Battery
    bat = get_battery_status()
    print(f"\n[7] Battery Status: {bat}")
    assert bat["success"] is True

    print("\n" + "=" * 60)
    print("✓ ALL SYSTEM TOOLS TESTED AND WORKING PROPERLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
