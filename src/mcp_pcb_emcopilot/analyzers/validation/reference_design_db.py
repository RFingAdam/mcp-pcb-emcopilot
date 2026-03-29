"""Reference design database and comparator for common SoCs."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

REFERENCE_DESIGNS: Dict[str, Dict[str, Any]] = {
    "MIMX8UD": {
        "name": "NXP i.MX 8ULP",
        "recommended_layers": 8,
        "ddr_type": "LPDDR4",
        "ddr_impedance_se": 40, "ddr_impedance_diff": 80,
        "ddr_max_length_mm": 50, "ddr_max_skew_ps": 25,
        "usb_impedance_diff": 90,
        "emmc_max_length_mm": 30, "emmc_speed": "HS400",
        "decoupling": "100nF + 1uF per VDD",
        "pmic": "PCA9460 recommended",
        "reference_stackup_total_mm": 1.6,
    },
    "STM32H7": {
        "name": "STM32H7 High-Performance",
        "recommended_layers": 6,
        "ddr_type": "DDR3L",
        "ddr_impedance_se": 40, "ddr_impedance_diff": 80,
        "ddr_max_length_mm": 60, "ddr_max_skew_ps": 50,
        "usb_impedance_diff": 90,
        "emmc_max_length_mm": 50, "emmc_speed": "HS200",
        "decoupling": "100nF per VDD, 4.7uF bulk per domain",
        "reference_stackup_total_mm": 1.2,
    },
    "STM32MP1": {
        "name": "STM32MP1 Linux MPU",
        "recommended_layers": 8,
        "ddr_type": "DDR3L",
        "ddr_impedance_se": 40, "ddr_impedance_diff": 80,
        "ddr_max_length_mm": 60, "ddr_max_skew_ps": 30,
        "usb_impedance_diff": 90,
        "emmc_max_length_mm": 40, "emmc_speed": "HS200",
        "decoupling": "100nF + 1uF per VDD group",
        "reference_stackup_total_mm": 1.6,
    },
    "NRF5340": {
        "name": "Nordic nRF5340 BLE/Thread",
        "recommended_layers": 4,
        "ddr_type": None,
        "usb_impedance_diff": 90,
        "rf_impedance": 50,
        "antenna_keep_out_mm": 5,
        "decoupling": "100nF + 1uF on VDDH, 100nF per VDD",
        "reference_stackup_total_mm": 1.0,
    },
    "ESP32S3": {
        "name": "Espressif ESP32-S3",
        "recommended_layers": 4,
        "ddr_type": None,
        "usb_impedance_diff": 90,
        "rf_impedance": 50,
        "antenna_keep_out_mm": 10,
        "decoupling": "100nF per VDD, 10uF bulk",
        "reference_stackup_total_mm": 1.0,
    },
}


class ReferenceDesignComparator:
    """Compare design against known-good reference for detected SoC."""

    def analyze(
        self, design: Any, classified_nets: Any = None, interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        # Auto-detect SoC
        soc_key, soc_ref = self._detect_soc(design)
        if not soc_ref:
            findings.append({
                "severity": "info", "category": "reference_design",
                "description": "No matching SoC reference design found in database",
                "recommendation": "Supported SoCs: " + ", ".join(REFERENCE_DESIGNS.keys()),
                "details": {},
            })
            return findings

        findings.append({
            "severity": "info", "category": "reference_design",
            "description": f"Matched SoC: {soc_ref['name']} — comparing against reference guidelines",
            "recommendation": "", "details": {"soc": soc_key, "reference": soc_ref},
        })

        # Compare layer count
        copper = sum(1 for l in design.layers if l.layer_type in ('signal', 'plane'))
        ref_layers = soc_ref.get("recommended_layers", 0)
        if ref_layers and copper < ref_layers:
            findings.append({
                "severity": "warning", "category": "ref_layer_count",
                "description": f"Board has {copper} copper layers, reference recommends {ref_layers}",
                "recommendation": f"Consider {ref_layers}-layer stackup for proper impedance control and power integrity",
                "details": {"actual": copper, "recommended": ref_layers},
            })

        # Compare DDR
        if soc_ref.get("ddr_type") and classified_nets:
            ddr_nets = [nc for nc in classified_nets.classified_nets if nc.category == 'ddr']
            if ddr_nets:
                # Check if DDR type matches
                findings.append({
                    "severity": "info", "category": "ref_ddr",
                    "description": f"Reference DDR: {soc_ref['ddr_type']}, impedance SE={soc_ref.get('ddr_impedance_se')}Ω diff={soc_ref.get('ddr_impedance_diff')}Ω, max length {soc_ref.get('ddr_max_length_mm')}mm, max skew {soc_ref.get('ddr_max_skew_ps')}ps",
                    "recommendation": "Verify DDR routing meets these reference targets",
                    "details": soc_ref,
                })

        # Compare stackup thickness
        total_thick = sum(l.thickness_mm or 0 for l in design.layers if l.layer_type in ('signal', 'plane', 'dielectric'))
        ref_thick = soc_ref.get("reference_stackup_total_mm", 0)
        if ref_thick and total_thick > 0:
            dev = abs(total_thick - ref_thick) / ref_thick * 100
            if dev > 30:
                findings.append({
                    "severity": "info", "category": "ref_stackup",
                    "description": f"Board thickness {total_thick:.2f}mm vs reference {ref_thick:.1f}mm ({dev:.0f}% difference)",
                    "recommendation": "Large deviation from reference stackup — verify impedance targets are achievable",
                    "details": {"actual_mm": round(total_thick, 2), "reference_mm": ref_thick},
                })

        return findings

    def _detect_soc(self, design: Any) -> tuple:
        """Auto-detect SoC from component values."""
        for comp in design.components:
            val = (comp.value or "").upper()
            for key, ref in REFERENCE_DESIGNS.items():
                if key.upper() in val:
                    return (key, ref)
        return (None, None)
