"""
BOM-driven current profiling and battery life analyzer.

Matches components to a built-in database of typical IoT part current
consumption, then estimates per-mode power draw and battery life.

Designed for IoT / SOM designs where battery life analysis is critical:
sleep, idle, TX, RX, sensor sampling, GNSS acquisition, etc.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# =============================================================================
# Part current consumption database
# =============================================================================
# Each entry is keyed by a regex-matchable prefix of a part number.
# Current values are typical datasheet values (not absolute worst-case).
#
# Fields vary by type:
#   MCU/SoC:   sleep_ua, idle_ma, active_ma, peak_ma
#   Radio:     sleep_ua, idle_ma, tx_ma, rx_ma
#   GNSS:      sleep_ua, tracking_ma, acquisition_ma
#   PMIC/Reg:  quiescent_ua, efficiency_pct
#   Memory:    active_ma, self_refresh_ma / idle_ma
#   PHY:       active_ma, sleep_ma

PART_DATABASE: Dict[str, Dict[str, Any]] = {
    # ── MCUs / SoCs ─────────────────────────────────────────────────────
    "MIMXRT1[0-9]": {
        "type": "mcu", "sleep_ua": 25, "idle_ma": 10, "active_ma": 150,
        "peak_ma": 500, "description": "NXP i.MX RT10xx crossover MCU",
    },
    "MIMX8MM": {
        "type": "mcu", "sleep_ua": 40, "idle_ma": 100, "active_ma": 800,
        "peak_ma": 2500, "description": "NXP i.MX 8M Mini",
    },
    "MIMX8MP": {
        "type": "mcu", "sleep_ua": 50, "idle_ma": 120, "active_ma": 1000,
        "peak_ma": 3000, "description": "NXP i.MX 8M Plus",
    },
    "MIMX8UD": {
        "type": "mcu", "sleep_ua": 50, "idle_ma": 15, "active_ma": 500,
        "peak_ma": 1200, "description": "NXP i.MX 8ULP",
    },
    "STM32L0": {
        "type": "mcu", "sleep_ua": 0.5, "idle_ma": 1.5, "active_ma": 8,
        "peak_ma": 30, "description": "STM32L0 ultra-low-power",
    },
    "STM32L4": {
        "type": "mcu", "sleep_ua": 1.0, "idle_ma": 3, "active_ma": 30,
        "peak_ma": 100, "description": "STM32L4 low-power",
    },
    "STM32L5": {
        "type": "mcu", "sleep_ua": 1.2, "idle_ma": 3.5, "active_ma": 35,
        "peak_ma": 110, "description": "STM32L5 secure low-power",
    },
    "STM32H7": {
        "type": "mcu", "sleep_ua": 3.0, "idle_ma": 20, "active_ma": 200,
        "peak_ma": 400, "description": "STM32H7 high-performance",
    },
    "STM32U5": {
        "type": "mcu", "sleep_ua": 0.8, "idle_ma": 2.5, "active_ma": 25,
        "peak_ma": 80, "description": "STM32U5 ultra-low-power",
    },
    "STM32WB": {
        "type": "mcu", "sleep_ua": 2.0, "idle_ma": 3, "active_ma": 30,
        "peak_ma": 100, "description": "STM32WB wireless MCU",
    },
    "ATSAM[DE]": {
        "type": "mcu", "sleep_ua": 2.0, "idle_ma": 3, "active_ma": 20,
        "peak_ma": 60, "description": "Microchip SAM D/E series",
    },
    "RP2040": {
        "type": "mcu", "sleep_ua": 180, "idle_ma": 2.5, "active_ma": 24,
        "peak_ma": 100, "description": "Raspberry Pi RP2040",
    },

    # ── BLE / Short-range radios ────────────────────────────────────────
    "NRF52": {
        "type": "ble", "sleep_ua": 2, "idle_ma": 0.5, "tx_ma": 15,
        "rx_ma": 12, "description": "Nordic nRF52 BLE",
    },
    "NRF53": {
        "type": "ble", "sleep_ua": 3, "idle_ma": 0.8, "tx_ma": 12,
        "rx_ma": 10, "description": "Nordic nRF5340 dual-core BLE",
    },
    "NRF91": {
        "type": "cellular", "sleep_ua": 5, "idle_ma": 6, "tx_ma": 230,
        "rx_ma": 45, "description": "Nordic nRF9160 LTE-M/NB-IoT",
    },
    "CC2652": {
        "type": "ble", "sleep_ua": 1, "idle_ma": 0.6, "tx_ma": 9,
        "rx_ma": 7, "description": "TI CC2652 BLE/Zigbee",
    },
    "CC1352": {
        "type": "ble", "sleep_ua": 1, "idle_ma": 0.6, "tx_ma": 13,
        "rx_ma": 8, "description": "TI CC1352 Sub-GHz + BLE",
    },
    "453-00148": {
        "type": "ble", "sleep_ua": 2, "idle_ma": 0.5, "tx_ma": 12,
        "rx_ma": 10, "description": "Ezurio BLE module",
    },
    "DA1469": {
        "type": "ble", "sleep_ua": 1.5, "idle_ma": 0.5, "tx_ma": 11,
        "rx_ma": 9, "description": "Renesas DA14695 BLE",
    },

    # ── WiFi modules ────────────────────────────────────────────────────
    "ESP32": {
        "type": "wifi", "sleep_ua": 5, "idle_ma": 20, "tx_ma": 240,
        "rx_ma": 95, "description": "ESP32 WiFi/BLE",
    },
    "ESP32S3": {
        "type": "wifi", "sleep_ua": 7, "idle_ma": 25, "tx_ma": 310,
        "rx_ma": 100, "description": "ESP32-S3 WiFi/BLE",
    },
    "ESP32C3": {
        "type": "wifi", "sleep_ua": 5, "idle_ma": 15, "tx_ma": 310,
        "rx_ma": 85, "description": "ESP32-C3 WiFi/BLE RISC-V",
    },
    "LBWA0ZZ": {
        "type": "wifi", "sleep_ua": 10, "idle_ma": 15, "tx_ma": 250,
        "rx_ma": 80, "description": "Murata WiFi module",
    },
    "CYW4373": {
        "type": "wifi", "sleep_ua": 10, "idle_ma": 18, "tx_ma": 300,
        "rx_ma": 90, "description": "Infineon/Cypress WiFi 5 combo",
    },
    "QCA9377": {
        "type": "wifi", "sleep_ua": 10, "idle_ma": 20, "tx_ma": 350,
        "rx_ma": 120, "description": "Qualcomm WiFi 5 module",
    },

    # ── HaLow (802.11ah) ───────────────────────────────────────────────
    "453-00155": {
        "type": "halow", "sleep_ua": 5, "idle_ma": 3, "tx_ma": 280,
        "rx_ma": 60, "description": "Silex/Ezurio HaLow",
    },

    # ── Cellular modems ─────────────────────────────────────────────────
    "SIM7600": {
        "type": "cellular", "sleep_ua": 50, "idle_ma": 10, "tx_ma": 500,
        "rx_ma": 50, "description": "SIM7600 LTE Cat-4",
    },
    "SIM7080": {
        "type": "cellular", "sleep_ua": 3, "idle_ma": 5, "tx_ma": 250,
        "rx_ma": 35, "description": "SIM7080 LTE Cat-M/NB-IoT",
    },
    "BG96": {
        "type": "cellular", "sleep_ua": 10, "idle_ma": 6, "tx_ma": 360,
        "rx_ma": 40, "description": "Quectel BG96 LTE Cat-M/NB",
    },
    "EG25": {
        "type": "cellular", "sleep_ua": 30, "idle_ma": 15, "tx_ma": 600,
        "rx_ma": 80, "description": "Quectel EG25-G LTE Cat-4",
    },
    "SARA-R4": {
        "type": "cellular", "sleep_ua": 8, "idle_ma": 6, "tx_ma": 220,
        "rx_ma": 50, "description": "u-blox SARA-R4 LTE-M/NB-IoT",
    },

    # ── GNSS receivers ──────────────────────────────────────────────────
    "NEO-M8": {
        "type": "gnss", "sleep_ua": 5, "tracking_ma": 29,
        "acquisition_ma": 47, "description": "u-blox NEO-M8",
    },
    "NEO-M9": {
        "type": "gnss", "sleep_ua": 5, "tracking_ma": 25,
        "acquisition_ma": 40, "description": "u-blox NEO-M9N multi-band",
    },
    "MAX-M10": {
        "type": "gnss", "sleep_ua": 2, "tracking_ma": 10,
        "acquisition_ma": 22, "description": "u-blox MAX-M10S low-power",
    },
    "L76": {
        "type": "gnss", "sleep_ua": 3, "tracking_ma": 18,
        "acquisition_ma": 28, "description": "Quectel L76 GNSS",
    },

    # ── LoRa / LPWAN ───────────────────────────────────────────────────
    "SX1276": {
        "type": "lora", "sleep_ua": 1, "idle_ma": 1.5, "tx_ma": 120,
        "rx_ma": 12, "description": "Semtech SX1276 LoRa",
    },
    "SX1262": {
        "type": "lora", "sleep_ua": 0.6, "idle_ma": 1.0, "tx_ma": 120,
        "rx_ma": 5, "description": "Semtech SX1262 LoRa",
    },

    # ── PMICs ───────────────────────────────────────────────────────────
    "PCA9460": {
        "type": "pmic", "quiescent_ua": 20,
        "description": "NXP PCA9460 PMIC",
    },
    "PCA9450": {
        "type": "pmic", "quiescent_ua": 25,
        "description": "NXP PCA9450 PMIC",
    },
    "MAX77[0-9]": {
        "type": "pmic", "quiescent_ua": 15,
        "description": "Maxim MAX77x PMIC",
    },
    "PFUZE": {
        "type": "pmic", "quiescent_ua": 30,
        "description": "NXP PFUZE PMIC",
    },

    # ── Regulators ──────────────────────────────────────────────────────
    "TPS62180": {
        "type": "regulator", "quiescent_ua": 17, "efficiency_pct": 90,
        "description": "TI TPS62180 buck converter",
    },
    "TPS566238": {
        "type": "regulator", "quiescent_ua": 4, "efficiency_pct": 92,
        "description": "TI TPS566238 buck converter",
    },
    "TPS6218[0-9]": {
        "type": "regulator", "quiescent_ua": 17, "efficiency_pct": 90,
        "description": "TI TPS6218x buck converter",
    },
    "TPS622[0-9]": {
        "type": "regulator", "quiescent_ua": 10, "efficiency_pct": 92,
        "description": "TI TPS622x buck converter",
    },
    "TLV713": {
        "type": "regulator", "quiescent_ua": 25, "efficiency_pct": 70,
        "description": "TI TLV713 LDO",
    },
    "AMS1117": {
        "type": "regulator", "quiescent_ua": 5000, "efficiency_pct": 60,
        "description": "AMS1117 LDO (high quiescent)",
    },
    "AP2112": {
        "type": "regulator", "quiescent_ua": 55, "efficiency_pct": 70,
        "description": "Diodes AP2112 LDO",
    },
    "MIC594": {
        "type": "regulator", "quiescent_ua": 30, "efficiency_pct": 70,
        "description": "Microchip MIC594x LDO",
    },

    # ── Memory ──────────────────────────────────────────────────────────
    "MT53D": {
        "type": "memory", "active_ma": 200, "self_refresh_ma": 3,
        "description": "Micron LPDDR4",
    },
    "MT40A": {
        "type": "memory", "active_ma": 300, "self_refresh_ma": 5,
        "description": "Micron DDR4",
    },
    "IS43": {
        "type": "memory", "active_ma": 150, "self_refresh_ma": 2,
        "description": "ISSI DDR/LPDDR",
    },
    "W25Q": {
        "type": "storage", "active_ma": 15, "idle_ma": 0.01,
        "description": "Winbond SPI NOR flash",
    },
    "MX25": {
        "type": "storage", "active_ma": 15, "idle_ma": 0.01,
        "description": "Macronix SPI NOR flash",
    },

    # ── eMMC / Storage ──────────────────────────────────────────────────
    "EMMC": {
        "type": "storage", "active_ma": 100, "idle_ma": 1,
        "description": "eMMC storage",
    },
    "SDINB": {
        "type": "storage", "active_ma": 120, "idle_ma": 1,
        "description": "SanDisk eMMC",
    },
    "KLM": {
        "type": "storage", "active_ma": 110, "idle_ma": 1,
        "description": "Samsung eMMC",
    },

    # ── Ethernet PHYs ───────────────────────────────────────────────────
    "DP83826": {
        "type": "ethernet_phy", "active_ma": 80, "sleep_ma": 0.5,
        "description": "TI DP83826 100M PHY",
    },
    "DP83867": {
        "type": "ethernet_phy", "active_ma": 250, "sleep_ma": 1,
        "description": "TI DP83867 GbE PHY",
    },
    "KSZ9031": {
        "type": "ethernet_phy", "active_ma": 300, "sleep_ma": 2,
        "description": "Microchip KSZ9031 GbE PHY",
    },
    "RTL8211": {
        "type": "ethernet_phy", "active_ma": 280, "sleep_ma": 1.5,
        "description": "Realtek RTL8211 GbE PHY",
    },

    # ── Sensors (common IoT) ────────────────────────────────────────────
    "BME280": {
        "type": "sensor", "sleep_ua": 0.1, "active_ma": 0.7,
        "description": "Bosch BME280 environmental sensor",
    },
    "BMI270": {
        "type": "sensor", "sleep_ua": 3, "active_ma": 0.9,
        "description": "Bosch BMI270 IMU",
    },
    "LIS2D": {
        "type": "sensor", "sleep_ua": 1, "active_ma": 0.2,
        "description": "ST LIS2D accelerometer",
    },
    "SHT4": {
        "type": "sensor", "sleep_ua": 0.1, "active_ma": 0.4,
        "description": "Sensirion SHT4x temp/humidity",
    },
    "INA219": {
        "type": "sensor", "sleep_ua": 2, "active_ma": 1.0,
        "description": "TI INA219 current sensor",
    },

    # ── USB controllers / hubs ──────────────────────────────────────────
    "USB5744": {
        "type": "usb_hub", "active_ma": 60, "sleep_ma": 0.5,
        "description": "Microchip USB5744 4-port USB 3.0 hub",
    },
    "TUSB321": {
        "type": "usb_controller", "active_ma": 5, "sleep_ma": 0.05,
        "description": "TI TUSB321 USB Type-C controller",
    },

    # ── Generic fallback ────────────────────────────────────────────────
    "DEFAULT_IC": {
        "type": "ic", "active_ma": 10, "sleep_ua": 100,
        "description": "Generic IC estimate",
    },
}

# Pre-compile the regex patterns for efficient matching
_COMPILED_PATTERNS: List[tuple[re.Pattern[str], Dict[str, Any]]] = []
for _pattern_str, _profile in PART_DATABASE.items():
    if _pattern_str == "DEFAULT_IC":
        continue
    try:
        _COMPILED_PATTERNS.append((re.compile(_pattern_str, re.IGNORECASE), _profile))
    except re.error:
        # Treat as literal prefix if not valid regex
        _COMPILED_PATTERNS.append(
            (re.compile(re.escape(_pattern_str), re.IGNORECASE), _profile)
        )


# =============================================================================
# Operating mode profiles
# =============================================================================

OPERATING_MODES: Dict[str, Dict[str, Any]] = {
    "deep_sleep": {
        "description": "Deep sleep, RTC only",
        "duty_pct": 0,
    },
    "light_sleep": {
        "description": "Light sleep, RAM retained",
        "duty_pct": 0,
    },
    "idle": {
        "description": "MCU idle, peripherals on",
        "duty_pct": 100,
    },
    "active": {
        "description": "MCU processing, radios off",
        "duty_pct": 100,
    },
    "ble_advertising": {
        "description": "BLE advertising beacon",
        "interval_ms": 1000,
        "tx_duration_ms": 3,
    },
    "ble_connected": {
        "description": "BLE connected, periodic TX",
        "interval_ms": 30,
        "tx_duration_ms": 2,
    },
    "wifi_tx": {
        "description": "WiFi transmit burst",
        "duration_ms": 5,
        "interval_ms": 100,
    },
    "wifi_idle": {
        "description": "WiFi associated, idle",
        "duty_pct": 100,
    },
    "cellular_tx": {
        "description": "LTE data transmission",
        "duration_ms": 10,
        "interval_ms": 1000,
    },
    "gnss_acquisition": {
        "description": "GNSS cold start fix",
        "duration_ms": 30000,
    },
    "gnss_tracking": {
        "description": "GNSS continuous tracking",
        "duty_pct": 100,
    },
    "sensor_read": {
        "description": "Sensor sampling event",
        "duration_ms": 50,
        "interval_ms": 60000,
    },
    "halow_tx": {
        "description": "HaLow data burst",
        "duration_ms": 10,
        "interval_ms": 200,
    },
    "lora_tx": {
        "description": "LoRa packet transmission",
        "duration_ms": 100,
        "interval_ms": 60000,
    },
}


# =============================================================================
# Helpers
# =============================================================================

def _match_part(part_string: str) -> Optional[Dict[str, Any]]:
    """Match a part number string against the database.

    Tries compiled regex patterns in order.  Returns the first match
    or None if nothing matches.
    """
    if not part_string:
        return None
    for compiled_re, profile in _COMPILED_PATTERNS:
        if compiled_re.search(part_string):
            return profile
    return None


def _component_search_string(comp: Any) -> str:
    """Build a combined search string from all available component fields."""
    parts = []
    for attr in ("value", "part_number", "manufacturer"):
        val = getattr(comp, attr, None)
        if val:
            parts.append(str(val))
    # Also check properties dict
    props = getattr(comp, "properties", {}) or {}
    for key in ("MPN", "mpn", "Part_Number", "PartNumber", "PN"):
        if key in props:
            parts.append(str(props[key]))
    return " ".join(parts)


def _current_for_mode(profile: Dict[str, Any], mode: str) -> float:
    """Return estimated current in mA for a matched part in a given mode.

    Returns 0.0 if the part does not contribute in this mode.
    """
    ptype = profile.get("type", "")

    if mode == "deep_sleep":
        # Everything in lowest-power state
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0  # uA → mA

    if mode == "light_sleep":
        # RAM retained: memory at self-refresh, MCU at sleep, radios off
        if ptype == "memory":
            return float(profile.get("self_refresh_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "idle":
        return float(profile.get("idle_ma", 0) or 0.0) or profile.get("active_ma", 0) * 0.3

    if mode == "active":
        return float(profile.get("active_ma", 0) or 0.0) or profile.get("idle_ma", 0) * 2

    # Radio TX modes
    if mode in ("ble_advertising", "ble_connected"):
        if ptype in ("ble",):
            return float(profile.get("tx_ma", 0) or 0.0)
        if ptype in ("mcu",):
            return float(profile.get("idle_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode in ("wifi_tx",):
        if ptype == "wifi":
            return float(profile.get("tx_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "wifi_idle":
        if ptype == "wifi":
            return float(profile.get("idle_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("idle_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode in ("cellular_tx",):
        if ptype == "cellular":
            return float(profile.get("tx_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "gnss_acquisition":
        if ptype == "gnss":
            return float(profile.get("acquisition_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "gnss_tracking":
        if ptype == "gnss":
            return float(profile.get("tracking_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("idle_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "sensor_read":
        if ptype == "sensor":
            return float(profile.get("active_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "halow_tx":
        if ptype == "halow":
            return float(profile.get("tx_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    if mode == "lora_tx":
        if ptype == "lora":
            return float(profile.get("tx_ma", 0) or 0.0)
        if ptype == "mcu":
            return float(profile.get("active_ma", 0) or 0.0)
        ua = float(profile.get("sleep_ua") or 0)
        return ua / 1000.0

    # PMIC / regulator quiescent always present
    if ptype in ("pmic", "regulator"):
        ua = float(profile.get("quiescent_ua") or 0)
        return ua / 1000.0

    # Ethernet PHY
    if ptype == "ethernet_phy":
        if mode in ("deep_sleep", "light_sleep"):
            return float(profile.get("sleep_ma", 0) or 0.0)
        return float(profile.get("active_ma", 0) or 0.0)

    # USB hub/controller
    if ptype in ("usb_hub", "usb_controller"):
        if mode in ("deep_sleep", "light_sleep"):
            return float(profile.get("sleep_ma", 0) or 0.0)
        return float(profile.get("active_ma", 0) or 0.0)

    # Storage
    if ptype == "storage":
        if mode in ("deep_sleep", "light_sleep"):
            return float(profile.get("idle_ma", 0) or 0.0)
        return float(profile.get("active_ma", 0) or 0.0) if mode == "active" else profile.get("idle_ma", 0)

    return 0.0


def _quiescent_current_ma(profile: Dict[str, Any]) -> float:
    """Get always-on quiescent current for PMICs/regulators."""
    if profile.get("type") in ("pmic", "regulator"):
        return float(profile.get("quiescent_ua", 0) or 0.0) / 1000.0
    return 0.0


# =============================================================================
# CurrentProfiler
# =============================================================================

class CurrentProfiler:
    """BOM-driven current profiling and battery life estimator.

    Matches design components against a built-in database of IoT part
    current consumption, then estimates per-mode power draw and
    (optionally) battery life.

    Follows the standard analyzer interface:
        profiler = CurrentProfiler()
        findings = profiler.analyze(design, classified_nets=net_cls)
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Run current profiling analysis.

        1. Match components to PART_DATABASE using part number regex.
        2. Build per-component current estimates.
        3. Calculate aggregate current for each relevant operating mode.
        4. If battery capacity is known (from review_context), estimate battery life.
        5. Generate findings.

        Returns:
            List of finding dicts with keys: category, severity, description,
            recommendation.
        """
        findings: List[Dict[str, Any]] = []

        if not design or not hasattr(design, "components"):
            return findings

        # ----- Step 1: Match components against the database -----
        matched: List[Dict[str, Any]] = []
        unmatched_ics: List[str] = []

        for comp in design.components:
            if getattr(comp, "dnp", False):
                continue

            search_str = _component_search_string(comp)
            profile = _match_part(search_str)

            if profile:
                matched.append({
                    "reference": comp.reference,
                    "search_string": search_str,
                    "profile": profile,
                })
            else:
                # Only flag IC-like components (not passives)
                ref_prefix = re.match(r"^([A-Z]+)", comp.reference or "")
                if ref_prefix and ref_prefix.group(1) in (
                    "U", "IC", "MOD", "Y",
                ):
                    unmatched_ics.append(f"{comp.reference} ({search_str[:40]})")

        if not matched:
            findings.append({
                "category": "Current Profile",
                "severity": "info",
                "description": (
                    "No components matched the current profiling database. "
                    "Current estimates require recognized part numbers in component values."
                ),
                "recommendation": (
                    "Ensure BOM part numbers are populated in component values or properties."
                ),
            })
            return findings

        # ----- Step 2: Determine which modes are relevant -----
        part_types = {m["profile"]["type"] for m in matched}

        relevant_modes: List[str] = ["deep_sleep", "light_sleep", "idle", "active"]
        if "ble" in part_types:
            relevant_modes.extend(["ble_advertising", "ble_connected"])
        if "wifi" in part_types:
            relevant_modes.extend(["wifi_tx", "wifi_idle"])
        if "cellular" in part_types:
            relevant_modes.append("cellular_tx")
        if "gnss" in part_types:
            relevant_modes.extend(["gnss_acquisition", "gnss_tracking"])
        if "sensor" in part_types:
            relevant_modes.append("sensor_read")
        if "halow" in part_types:
            relevant_modes.append("halow_tx")
        if "lora" in part_types:
            relevant_modes.append("lora_tx")
        # deduplicate, preserving order
        relevant_modes = list(dict.fromkeys(relevant_modes))

        # ----- Step 3: Calculate per-mode aggregate current -----
        mode_totals: Dict[str, float] = {}   # mode -> total mA
        mode_details: Dict[str, List[Dict[str, Any]]] = {}  # mode -> per-component list

        # Always-on quiescent from PMICs/regulators
        quiescent_total_ma = sum(
            _quiescent_current_ma(m["profile"]) for m in matched
        )

        for mode in relevant_modes:
            total_ma = 0.0
            details = []
            for m in matched:
                current_ma = _current_for_mode(m["profile"], mode)
                # Add PMIC/regulator quiescent on top for non-sleep modes
                if m["profile"]["type"] not in ("pmic", "regulator"):
                    total_ma += current_ma
                else:
                    # quiescent is always present
                    q_ma = _quiescent_current_ma(m["profile"])
                    total_ma += q_ma
                    current_ma = q_ma

                if current_ma > 0.01:
                    details.append({
                        "reference": m["reference"],
                        "type": m["profile"]["type"],
                        "description": m["profile"]["description"],
                        "current_ma": round(current_ma, 3),
                    })

            mode_totals[mode] = round(total_ma, 3)
            mode_details[mode] = sorted(details, key=lambda d: -d["current_ma"])

        # ----- Step 4: Build summary finding -----
        mode_table_lines = []
        for mode in relevant_modes:
            mode_desc = OPERATING_MODES.get(mode, {}).get("description", mode)
            total = mode_totals.get(mode, 0)
            mode_table_lines.append(f"  {mode:<22s} {total:>8.1f} mA  ({mode_desc})")

        summary_text = (
            f"Current profile for {len(matched)} matched component(s) "
            f"across {len(relevant_modes)} operating modes:\n"
            + "\n".join(mode_table_lines)
        )

        findings.append({
            "category": "Current Profile Summary",
            "severity": "info",
            "description": summary_text,
            "recommendation": (
                "Review per-mode current estimates against your power budget. "
                "Duty-cycle your high-power modes to minimize average current."
            ),
        })

        # ----- Step 5: Identify highest-power components per mode -----
        for mode in relevant_modes:
            details = mode_details.get(mode, [])
            if not details:
                continue
            top = details[0]
            total = mode_totals[mode]
            if total > 0 and top["current_ma"] / total > 0.4:
                pct = 100.0 * top["current_ma"] / total
                findings.append({
                    "category": "Top Power Consumer",
                    "severity": "info",
                    "description": (
                        f"In '{mode}' mode, {top['reference']} ({top['description']}) "
                        f"draws {top['current_ma']:.1f} mA ({pct:.0f}% of {total:.1f} mA total)."
                    ),
                    "recommendation": (
                        f"Consider power-gating or duty-cycling {top['reference']} "
                        f"to reduce average current in this mode."
                    ),
                })

        # ----- Step 6: Power budget warnings -----
        for mode, total_ma in mode_totals.items():
            if total_ma > 500:
                findings.append({
                    "category": "Power Budget Warning",
                    "severity": "warning",
                    "description": (
                        f"'{mode}' mode total current is {total_ma:.0f} mA. "
                        f"Peak current exceeds 500 mA -- verify supply capacity."
                    ),
                    "recommendation": (
                        "Ensure the power supply / battery can deliver the peak "
                        "current with adequate margin. Consider staggering "
                        "high-power operations."
                    ),
                })

        # Check cellular/HaLow TX peaks specifically
        for mode in ("cellular_tx", "halow_tx", "wifi_tx"):
            if mode in mode_totals and mode_totals[mode] > 400:
                findings.append({
                    "category": "Peak Current Alert",
                    "severity": "warning",
                    "description": (
                        f"Radio TX mode '{mode}' draws {mode_totals[mode]:.0f} mA total. "
                        f"Ensure bulk capacitance near the radio module to handle transients."
                    ),
                    "recommendation": (
                        "Place a 100 uF+ bulk capacitor within 5 mm of the radio "
                        "module power pins to supply peak TX current."
                    ),
                })

        # ----- Step 7: Battery life estimate (if capacity known) -----
        battery_mah = self._get_battery_capacity(design)

        if battery_mah and battery_mah > 0:
            # Build a typical IoT duty cycle estimate
            duty_cycles = self._estimate_duty_cycles(part_types, relevant_modes)
            battery_result = self.estimate_battery_life(
                profiles=mode_totals,
                duty_cycles=duty_cycles,
                battery_mah=battery_mah,
            )

            avg_ma = battery_result["average_current_ma"]
            life_days = battery_result["battery_life_days"]
            life_hours = battery_result["battery_life_hours"]

            if life_days < 1:
                severity = "critical"
            elif life_days < 30:
                severity = "warning"
            else:
                severity = "info"

            # Build contribution breakdown
            contrib_lines = []
            for mode, contrib in battery_result["per_mode_contribution"].items():
                if contrib["contribution_ma"] > 0.001:
                    contrib_lines.append(
                        f"  {mode:<22s} {contrib['duty_pct']:>5.1f}% duty  "
                        f"x {contrib['current_ma']:>8.1f} mA  "
                        f"= {contrib['contribution_ma']:>6.3f} mA avg"
                    )

            description = (
                f"Battery life estimate ({battery_mah:.0f} mAh):\n"
                f"  Weighted average current: {avg_ma:.3f} mA\n"
                f"  Estimated battery life: {life_hours:.1f} hours ({life_days:.1f} days)\n"
                f"\nPer-mode contributions:\n"
                + "\n".join(contrib_lines)
            )

            findings.append({
                "category": "Battery Life Estimate",
                "severity": severity,
                "description": description,
                "recommendation": (
                    "Optimize duty cycles for the highest-contributing modes. "
                    "Deep sleep current is the floor; minimize always-on loads."
                ),
            })

        # ----- Step 8: Unmatched ICs -----
        if unmatched_ics:
            max_show = 10
            ic_list = ", ".join(unmatched_ics[:max_show])
            extra = f" (+{len(unmatched_ics) - max_show} more)" if len(unmatched_ics) > max_show else ""
            findings.append({
                "category": "Unmatched Components",
                "severity": "info",
                "description": (
                    f"{len(unmatched_ics)} IC-type component(s) not in the current "
                    f"database: {ic_list}{extra}. Their current draw is not included "
                    f"in the profile."
                ),
                "recommendation": (
                    "Add part-number data to component values or extend the "
                    "current profiler database for project-specific parts."
                ),
            })

        return findings

    # -----------------------------------------------------------------
    # Battery life calculator
    # -----------------------------------------------------------------

    def estimate_battery_life(
        self,
        profiles: Dict[str, float],
        duty_cycles: Dict[str, float],
        battery_mah: float,
    ) -> Dict[str, Any]:
        """Calculate battery life from current profiles and duty cycles.

        Args:
            profiles: Mapping of mode_name -> average current in mA for
                that mode (total system current).
            duty_cycles: Mapping of mode_name -> percentage of time spent
                in that mode (0-100).  Must sum to 100 or will be normalised.
            battery_mah: Battery capacity in mAh.

        Returns:
            Dict with keys:
                average_current_ma: weighted average system current (mA)
                battery_life_hours: estimated hours
                battery_life_days: estimated days
                per_mode_contribution: per-mode breakdown dict
        """
        # Normalise duty cycles to sum to 100
        total_duty = sum(duty_cycles.values())
        if total_duty <= 0:
            return {
                "average_current_ma": 0.0,
                "battery_life_hours": float("inf"),
                "battery_life_days": float("inf"),
                "per_mode_contribution": {},
            }

        scale = 100.0 / total_duty

        contributions: Dict[str, Dict[str, float]] = {}
        average_current = 0.0

        for mode, duty_pct in duty_cycles.items():
            normalised_duty = duty_pct * scale
            current_ma = profiles.get(mode, 0.0)
            contribution = current_ma * (normalised_duty / 100.0)
            average_current += contribution
            contributions[mode] = {
                "current_ma": round(current_ma, 3),
                "duty_pct": round(normalised_duty, 2),
                "contribution_ma": round(contribution, 4),
            }

        if average_current <= 0:
            life_hours = float("inf")
        else:
            life_hours = battery_mah / average_current

        return {
            "average_current_ma": round(average_current, 4),
            "battery_life_hours": round(life_hours, 1),
            "battery_life_days": round(life_hours / 24.0, 1),
            "per_mode_contribution": contributions,
        }

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _get_battery_capacity(design: Any) -> Optional[float]:
        """Extract battery capacity from the design's review_context."""
        ctx = getattr(design, "review_context", None) or {}
        # Direct key
        val = ctx.get("battery_capacity_mah")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        # Also check interactive_answers
        answers = ctx.get("interactive_answers", {})
        val = answers.get("battery_capacity_mah")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _estimate_duty_cycles(
        part_types: set,
        relevant_modes: List[str],
    ) -> Dict[str, float]:
        """Estimate a plausible IoT duty cycle for the detected part types.

        This is a rough heuristic -- the user should refine these values
        for accurate battery life estimation.  The default profile assumes
        a typical low-power IoT device that mostly sleeps.
        """
        cycles: Dict[str, float] = {}

        for mode in relevant_modes:
            if mode == "deep_sleep":
                cycles[mode] = 90.0  # dominant mode
            elif mode == "light_sleep":
                cycles[mode] = 5.0
            elif mode == "idle":
                cycles[mode] = 2.0
            elif mode == "active":
                cycles[mode] = 1.0
            elif mode == "ble_advertising":
                cycles[mode] = 0.5
            elif mode == "ble_connected":
                cycles[mode] = 0.3
            elif mode == "wifi_tx":
                cycles[mode] = 0.1
            elif mode == "wifi_idle":
                cycles[mode] = 0.5
            elif mode == "cellular_tx":
                cycles[mode] = 0.05
            elif mode == "gnss_acquisition":
                cycles[mode] = 0.05
            elif mode == "gnss_tracking":
                cycles[mode] = 0.2
            elif mode == "sensor_read":
                cycles[mode] = 0.1
            elif mode == "halow_tx":
                cycles[mode] = 0.1
            elif mode == "lora_tx":
                cycles[mode] = 0.05
            else:
                cycles[mode] = 0.1

        return cycles
