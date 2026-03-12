"""High-speed interface detection for PCB designs.

Identifies complete interfaces (DDR, PCIe, USB, Ethernet, LVDS, etc.)
by aggregating classified nets into logical interface groups with
pin counts and signal breakdowns.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models.pcb_data import PCBDesignData
from .net_classifier import NetClassifier, NetClassificationResult, NetClassification


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class InterfaceSignalGroup:
    """A group of signals within an interface (e.g., DDR data byte lane 0)."""
    group_name: str
    signal_type: str  # data, strobe, clock, address, command, control, power, management
    net_names: list[str] = field(default_factory=list)
    pin_count: int = 0
    differential_pairs: int = 0


@dataclass
class DetectedInterface:
    """A detected high-speed interface."""
    interface_type: str  # DDR4, USB3.0, PCIe_x4, GbE, LVDS, etc.
    description: str  # Human-readable description
    confidence: float
    signal_groups: list[InterfaceSignalGroup] = field(default_factory=list)
    total_pins: int = 0
    differential_pairs: int = 0
    associated_nets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.interface_type,
            "description": self.description,
            "confidence": round(self.confidence, 2),
            "total_pins": self.total_pins,
            "differential_pairs": self.differential_pairs,
            "signal_groups": [
                {
                    "name": sg.group_name,
                    "type": sg.signal_type,
                    "nets": sg.net_names,
                    "pins": sg.pin_count,
                    "diff_pairs": sg.differential_pairs,
                }
                for sg in self.signal_groups
            ],
            "associated_nets": self.associated_nets,
            "notes": self.notes,
        }


@dataclass
class InterfaceDetectionResult:
    """Full interface detection result."""
    interfaces: list[DetectedInterface] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "interface_count": len(self.interfaces),
            "interfaces": [iface.to_dict() for iface in self.interfaces],
            "summary": self.summary,
        }


# =============================================================================
# Interface detector
# =============================================================================

class InterfaceDetector:
    """Detects high-speed interfaces from classified net data."""

    def __init__(self):
        self._classifier = NetClassifier()

    def detect(self, design: PCBDesignData, classification: Optional[NetClassificationResult] = None) -> InterfaceDetectionResult:
        """Detect all high-speed interfaces in a design.

        Args:
            design: Parsed PCB design data.
            classification: Pre-computed net classification (optional, will compute if not provided).

        Returns:
            InterfaceDetectionResult with all detected interfaces.
        """
        if classification is None:
            classification = self._classifier.classify(design)

        result = InterfaceDetectionResult()

        # Group nets by category
        category_nets: dict[str, list[NetClassification]] = {}
        for nc in classification.classified_nets:
            category_nets.setdefault(nc.category, []).append(nc)

        # Detect each interface type
        detectors = [
            self._detect_ddr,
            self._detect_usb,
            self._detect_pcie,
            self._detect_ethernet,
            self._detect_lvds,
            self._detect_rf,
        ]

        for detector in detectors:
            interfaces = detector(category_nets, classification)
            result.interfaces.extend(interfaces)

        # Build summary
        result.summary = {
            "total_interfaces": len(result.interfaces),
            "types": [i.interface_type for i in result.interfaces],
            "total_high_speed_nets": sum(i.total_pins for i in result.interfaces),
            "total_differential_pairs": sum(i.differential_pairs for i in result.interfaces),
        }

        return result

    # -------------------------------------------------------------------------
    # DDR Detection
    # -------------------------------------------------------------------------

    def _detect_ddr(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect DDR memory interfaces."""
        ddr_nets = category_nets.get('ddr', [])
        if not ddr_nets:
            return []

        # Subgroup by subcategory
        data_nets = [n for n in ddr_nets if n.subcategory == 'data']
        strobe_nets = [n for n in ddr_nets if n.subcategory == 'strobe']
        address_nets = [n for n in ddr_nets if n.subcategory == 'address']
        command_nets = [n for n in ddr_nets if n.subcategory == 'command']
        clock_nets = [n for n in ddr_nets if n.subcategory == 'clock']
        control_nets = [n for n in ddr_nets if n.subcategory in ('control', 'chip_select', 'calibration')]
        mask_nets = [n for n in ddr_nets if n.subcategory == 'mask']
        ref_nets = [n for n in ddr_nets if n.subcategory == 'reference']
        other_nets = [n for n in ddr_nets if n.subcategory not in ('data', 'strobe', 'address', 'command', 'clock', 'control', 'chip_select', 'calibration', 'mask', 'reference')]

        # Infer DDR generation
        ddr_gen = self._infer_ddr_generation(ddr_nets, classification)

        # Count data width
        data_width = len(data_nets)
        # DQS pairs indicate byte lanes
        dqs_count = len(strobe_nets)
        byte_lanes = max(dqs_count // 2, data_width // 8) if data_width > 0 else 0

        # Build signal groups
        groups = []
        if data_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Data", signal_type="data",
                net_names=[n.net_name for n in data_nets],
                pin_count=len(data_nets),
            ))
        if strobe_nets:
            dp_count = sum(1 for n in strobe_nets if n.differential_polarity == 'P')
            groups.append(InterfaceSignalGroup(
                group_name="Strobe (DQS)", signal_type="strobe",
                net_names=[n.net_name for n in strobe_nets],
                pin_count=len(strobe_nets),
                differential_pairs=dp_count,
            ))
        if address_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Address", signal_type="address",
                net_names=[n.net_name for n in address_nets],
                pin_count=len(address_nets),
            ))
        if command_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Command", signal_type="command",
                net_names=[n.net_name for n in command_nets],
                pin_count=len(command_nets),
            ))
        if clock_nets:
            dp_count = sum(1 for n in clock_nets if n.differential_polarity == 'P')
            groups.append(InterfaceSignalGroup(
                group_name="Clock", signal_type="clock",
                net_names=[n.net_name for n in clock_nets],
                pin_count=len(clock_nets),
                differential_pairs=dp_count,
            ))
        if control_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Control", signal_type="control",
                net_names=[n.net_name for n in control_nets],
                pin_count=len(control_nets),
            ))

        total_pins = sum(g.pin_count for g in groups)
        total_diff = sum(g.differential_pairs for g in groups)
        all_nets = [n.net_name for n in ddr_nets]

        # Build description
        width_str = f"x{data_width}" if data_width > 0 else ""
        parts = []
        if data_nets:
            parts.append(f"{len(data_nets)} data")
        if strobe_nets:
            parts.append(f"{len(strobe_nets)//2} DQS")
        if address_nets:
            parts.append(f"addr/cmd")
        desc = f"{ddr_gen} {width_str} ({' + '.join(parts)})" if parts else f"{ddr_gen}"

        notes = []
        if byte_lanes > 0:
            notes.append(f"{byte_lanes} byte lane(s) detected")

        return [DetectedInterface(
            interface_type=ddr_gen,
            description=desc,
            confidence=min(0.95, 0.6 + 0.05 * len(groups)),
            signal_groups=groups,
            total_pins=total_pins,
            differential_pairs=total_diff,
            associated_nets=all_nets,
            notes=notes,
        )]

    def _infer_ddr_generation(self, ddr_nets: list, classification: NetClassificationResult) -> str:
        """Infer DDR generation from net names."""
        all_names = " ".join(n.net_name for n in ddr_nets)
        if re.search(r'DDR5|LPDDR5', all_names, re.IGNORECASE):
            return "DDR5"
        if re.search(r'DDR4|LPDDR4', all_names, re.IGNORECASE):
            return "DDR4"
        if re.search(r'DDR3|LPDDR3', all_names, re.IGNORECASE):
            return "DDR3"
        if re.search(r'DDR2', all_names, re.IGNORECASE):
            return "DDR2"
        # Check for DDR4-specific signals
        bg_nets = [n for n in ddr_nets if re.match(r'^BG\d', n.net_name, re.IGNORECASE)]
        if bg_nets:
            return "DDR4"  # BG (bank group) is DDR4+
        return "DDR"

    # -------------------------------------------------------------------------
    # USB Detection
    # -------------------------------------------------------------------------

    def _detect_usb(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect USB interfaces."""
        usb_nets = category_nets.get('usb', [])
        if not usb_nets:
            return []

        interfaces = []

        # Check for USB 3.x (has SSTX/SSRX)
        ss_tx = [n for n in usb_nets if n.subcategory and 'sstx' in n.subcategory]
        ss_rx = [n for n in usb_nets if n.subcategory and 'ssrx' in n.subcategory]
        usb2_data = [n for n in usb_nets if n.subcategory and 'usb2' in n.subcategory]
        power_nets = [n for n in usb_nets if n.subcategory == 'power']
        cc_nets = [n for n in usb_nets if n.subcategory and 'cc' in n.subcategory]
        sbu_nets = [n for n in usb_nets if n.subcategory and 'sbu' in n.subcategory]
        other_nets = [n for n in usb_nets if n not in ss_tx + ss_rx + usb2_data + power_nets + cc_nets + sbu_nets]

        has_ss = len(ss_tx) > 0 or len(ss_rx) > 0
        has_usbc = len(cc_nets) > 0

        if has_ss:
            # USB 3.x
            usb_version = "USB 3.0"
            ss_pairs = max(len(ss_tx), len(ss_rx))
            if ss_pairs >= 4:
                usb_version = "USB 3.2 Gen2x2"
            elif ss_pairs >= 2:
                usb_version = "USB 3.1"

            groups = []
            if usb2_data:
                groups.append(InterfaceSignalGroup(
                    group_name="USB 2.0 (D+/D-)", signal_type="data",
                    net_names=[n.net_name for n in usb2_data],
                    pin_count=len(usb2_data), differential_pairs=len(usb2_data) // 2,
                ))
            if ss_tx:
                groups.append(InterfaceSignalGroup(
                    group_name="SuperSpeed TX", signal_type="data",
                    net_names=[n.net_name for n in ss_tx],
                    pin_count=len(ss_tx), differential_pairs=len(ss_tx) // 2,
                ))
            if ss_rx:
                groups.append(InterfaceSignalGroup(
                    group_name="SuperSpeed RX", signal_type="data",
                    net_names=[n.net_name for n in ss_rx],
                    pin_count=len(ss_rx), differential_pairs=len(ss_rx) // 2,
                ))
            if cc_nets:
                groups.append(InterfaceSignalGroup(
                    group_name="Type-C CC", signal_type="control",
                    net_names=[n.net_name for n in cc_nets],
                    pin_count=len(cc_nets),
                ))
            if power_nets:
                groups.append(InterfaceSignalGroup(
                    group_name="VBUS", signal_type="power",
                    net_names=[n.net_name for n in power_nets],
                    pin_count=len(power_nets),
                ))

            total_pins = sum(g.pin_count for g in groups)
            total_diff = sum(g.differential_pairs for g in groups)
            desc_parts = []
            if usb2_data:
                desc_parts.append("D+/D-")
            if ss_tx:
                desc_parts.append("SSTX")
            if ss_rx:
                desc_parts.append("SSRX")
            desc = f"{usb_version} ({', '.join(desc_parts)})"

            interfaces.append(DetectedInterface(
                interface_type=usb_version,
                description=desc,
                confidence=0.90,
                signal_groups=groups,
                total_pins=total_pins,
                differential_pairs=total_diff,
                associated_nets=[n.net_name for n in usb_nets],
                notes=["Type-C connector detected"] if has_usbc else [],
            ))
        elif usb2_data or other_nets:
            # USB 2.0 only
            groups = []
            data_all = usb2_data + other_nets
            groups.append(InterfaceSignalGroup(
                group_name="USB 2.0 Data", signal_type="data",
                net_names=[n.net_name for n in data_all],
                pin_count=len(data_all), differential_pairs=len(data_all) // 2,
            ))
            if power_nets:
                groups.append(InterfaceSignalGroup(
                    group_name="VBUS", signal_type="power",
                    net_names=[n.net_name for n in power_nets],
                    pin_count=len(power_nets),
                ))

            total_pins = sum(g.pin_count for g in groups)
            total_diff = sum(g.differential_pairs for g in groups)

            interfaces.append(DetectedInterface(
                interface_type="USB 2.0",
                description=f"USB 2.0 (D+/D-)",
                confidence=0.85,
                signal_groups=groups,
                total_pins=total_pins,
                differential_pairs=total_diff,
                associated_nets=[n.net_name for n in usb_nets],
            ))

        return interfaces

    # -------------------------------------------------------------------------
    # PCIe Detection
    # -------------------------------------------------------------------------

    def _detect_pcie(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect PCIe interfaces."""
        pcie_nets = category_nets.get('pcie', [])
        if not pcie_nets:
            return []

        tx_nets = [n for n in pcie_nets if n.subcategory == 'tx']
        rx_nets = [n for n in pcie_nets if n.subcategory == 'rx']
        refclk_nets = [n for n in pcie_nets if n.subcategory == 'refclk']
        ctrl_nets = [n for n in pcie_nets if n.subcategory in ('reset', 'wake', 'clkreq')]
        other_nets = [n for n in pcie_nets if n not in tx_nets + rx_nets + refclk_nets + ctrl_nets]

        # Each lane has TX P/N and RX P/N = 4 pins per lane
        tx_pairs = len(tx_nets) // 2 if len(tx_nets) >= 2 else len(tx_nets)
        rx_pairs = len(rx_nets) // 2 if len(rx_nets) >= 2 else len(rx_nets)
        lane_count = max(tx_pairs, rx_pairs)
        if lane_count == 0:
            lane_count = max(len(tx_nets), len(rx_nets))

        width_label = f"x{lane_count}" if lane_count > 0 else ""

        groups = []
        if tx_nets:
            groups.append(InterfaceSignalGroup(
                group_name="TX Lanes", signal_type="data",
                net_names=[n.net_name for n in tx_nets],
                pin_count=len(tx_nets), differential_pairs=tx_pairs,
            ))
        if rx_nets:
            groups.append(InterfaceSignalGroup(
                group_name="RX Lanes", signal_type="data",
                net_names=[n.net_name for n in rx_nets],
                pin_count=len(rx_nets), differential_pairs=rx_pairs,
            ))
        if refclk_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Reference Clock", signal_type="clock",
                net_names=[n.net_name for n in refclk_nets],
                pin_count=len(refclk_nets), differential_pairs=len(refclk_nets) // 2,
            ))
        if ctrl_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Sideband", signal_type="control",
                net_names=[n.net_name for n in ctrl_nets],
                pin_count=len(ctrl_nets),
            ))

        total_pins = sum(g.pin_count for g in groups)
        total_diff = sum(g.differential_pairs for g in groups)

        parts = []
        if lane_count > 0:
            parts.append(f"{lane_count} lane(s)")
        if refclk_nets:
            parts.append("REFCLK")
        if ctrl_nets:
            parts.append("sideband")
        desc = f"PCIe {width_label} ({', '.join(parts)})" if parts else f"PCIe {width_label}"

        return [DetectedInterface(
            interface_type=f"PCIe {width_label}".strip(),
            description=desc,
            confidence=0.90 if lane_count > 0 else 0.70,
            signal_groups=groups,
            total_pins=total_pins,
            differential_pairs=total_diff,
            associated_nets=[n.net_name for n in pcie_nets],
        )]

    # -------------------------------------------------------------------------
    # Ethernet Detection
    # -------------------------------------------------------------------------

    def _detect_ethernet(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect Ethernet interfaces."""
        eth_nets = category_nets.get('ethernet', [])
        if not eth_nets:
            return []

        mdi_nets = [n for n in eth_nets if n.subcategory and 'mdi' in n.subcategory]
        mgmt_nets = [n for n in eth_nets if n.subcategory == 'management']
        rgmii_nets = [n for n in eth_nets if n.subcategory == 'rgmii']
        rmii_nets = [n for n in eth_nets if n.subcategory == 'rmii']
        mii_nets = [n for n in eth_nets if n.subcategory == 'mii']
        sgmii_nets = [n for n in eth_nets if n.subcategory == 'sgmii']
        other_nets = [n for n in eth_nets if n not in mdi_nets + mgmt_nets + rgmii_nets + rmii_nets + mii_nets + sgmii_nets]

        # Count MDI pairs (4 pairs for GbE)
        mdi_pair_count = len(mdi_nets) // 2 if len(mdi_nets) >= 2 else len(mdi_nets)

        # Infer speed
        speed = "Ethernet"
        if mdi_pair_count >= 4:
            speed = "GbE"
        elif mdi_pair_count >= 2:
            speed = "100BASE-TX"
        elif sgmii_nets:
            speed = "SGMII"

        # Detect PHY interface type
        phy_type = None
        if rgmii_nets:
            phy_type = "RGMII"
        elif rmii_nets:
            phy_type = "RMII"
        elif mii_nets:
            phy_type = "MII"
        elif sgmii_nets:
            phy_type = "SGMII"

        groups = []
        if mdi_nets:
            groups.append(InterfaceSignalGroup(
                group_name="MDI Pairs", signal_type="data",
                net_names=[n.net_name for n in mdi_nets],
                pin_count=len(mdi_nets), differential_pairs=mdi_pair_count,
            ))
        if rgmii_nets:
            groups.append(InterfaceSignalGroup(
                group_name="RGMII", signal_type="data",
                net_names=[n.net_name for n in rgmii_nets],
                pin_count=len(rgmii_nets),
            ))
        if rmii_nets:
            groups.append(InterfaceSignalGroup(
                group_name="RMII", signal_type="data",
                net_names=[n.net_name for n in rmii_nets],
                pin_count=len(rmii_nets),
            ))
        if sgmii_nets:
            groups.append(InterfaceSignalGroup(
                group_name="SGMII", signal_type="data",
                net_names=[n.net_name for n in sgmii_nets],
                pin_count=len(sgmii_nets), differential_pairs=len(sgmii_nets) // 2,
            ))
        if mgmt_nets:
            groups.append(InterfaceSignalGroup(
                group_name="Management (MDIO/MDC)", signal_type="management",
                net_names=[n.net_name for n in mgmt_nets],
                pin_count=len(mgmt_nets),
            ))

        total_pins = sum(g.pin_count for g in groups)
        total_diff = sum(g.differential_pairs for g in groups)

        parts = []
        if mdi_pair_count > 0:
            parts.append(f"{mdi_pair_count} MDI pair(s)")
        if phy_type:
            parts.append(phy_type)
        if mgmt_nets:
            parts.append("MDIO")
        desc = f"{speed} ({', '.join(parts)})" if parts else speed

        return [DetectedInterface(
            interface_type=speed,
            description=desc,
            confidence=0.85 if mdi_pair_count > 0 else 0.70,
            signal_groups=groups,
            total_pins=total_pins,
            differential_pairs=total_diff,
            associated_nets=[n.net_name for n in eth_nets],
            notes=[f"PHY interface: {phy_type}"] if phy_type else [],
        )]

    # -------------------------------------------------------------------------
    # LVDS Detection
    # -------------------------------------------------------------------------

    def _detect_lvds(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect LVDS interfaces."""
        lvds_nets = category_nets.get('lvds', [])
        if not lvds_nets:
            return []

        pair_count = sum(1 for n in lvds_nets if n.differential_polarity == 'P')
        if pair_count == 0:
            pair_count = len(lvds_nets) // 2

        groups = [InterfaceSignalGroup(
            group_name="LVDS Pairs", signal_type="data",
            net_names=[n.net_name for n in lvds_nets],
            pin_count=len(lvds_nets), differential_pairs=pair_count,
        )]

        desc = f"LVDS ({pair_count} pair(s))"

        return [DetectedInterface(
            interface_type="LVDS",
            description=desc,
            confidence=0.85,
            signal_groups=groups,
            total_pins=len(lvds_nets),
            differential_pairs=pair_count,
            associated_nets=[n.net_name for n in lvds_nets],
        )]

    # -------------------------------------------------------------------------
    # RF Detection
    # -------------------------------------------------------------------------

    def _detect_rf(self, category_nets: dict, classification: NetClassificationResult) -> list[DetectedInterface]:
        """Detect RF interfaces."""
        rf_nets = category_nets.get('rf', [])
        if not rf_nets:
            return []

        # Group by subcategory
        subcats: dict[str, list[NetClassification]] = {}
        for n in rf_nets:
            key = n.subcategory or 'general'
            subcats.setdefault(key, []).append(n)

        interfaces = []

        # Detect specific RF subsystems
        rf_types_found = set(subcats.keys())

        # WiFi
        wifi_nets = subcats.get('wifi', [])
        if wifi_nets:
            groups = [InterfaceSignalGroup(
                group_name="WiFi", signal_type="data",
                net_names=[n.net_name for n in wifi_nets],
                pin_count=len(wifi_nets),
            )]
            interfaces.append(DetectedInterface(
                interface_type="WiFi",
                description=f"WiFi ({len(wifi_nets)} signal(s))",
                confidence=0.85,
                signal_groups=groups,
                total_pins=len(wifi_nets),
                associated_nets=[n.net_name for n in wifi_nets],
            ))

        # Bluetooth
        bt_nets = subcats.get('bluetooth', [])
        if bt_nets:
            groups = [InterfaceSignalGroup(
                group_name="Bluetooth", signal_type="data",
                net_names=[n.net_name for n in bt_nets],
                pin_count=len(bt_nets),
            )]
            interfaces.append(DetectedInterface(
                interface_type="Bluetooth",
                description=f"Bluetooth ({len(bt_nets)} signal(s))",
                confidence=0.85,
                signal_groups=groups,
                total_pins=len(bt_nets),
                associated_nets=[n.net_name for n in bt_nets],
            ))

        # Cellular
        cell_nets = subcats.get('cellular', [])
        if cell_nets:
            groups = [InterfaceSignalGroup(
                group_name="Cellular", signal_type="data",
                net_names=[n.net_name for n in cell_nets],
                pin_count=len(cell_nets),
            )]
            interfaces.append(DetectedInterface(
                interface_type="Cellular",
                description=f"Cellular RF ({len(cell_nets)} signal(s))",
                confidence=0.85,
                signal_groups=groups,
                total_pins=len(cell_nets),
                associated_nets=[n.net_name for n in cell_nets],
            ))

        # General RF (antenna, LNA, PA, etc.)
        general_rf = []
        for subcat, nets in subcats.items():
            if subcat not in ('wifi', 'bluetooth', 'cellular', 'gps', 'gnss', 'lora'):
                general_rf.extend(nets)

        if general_rf:
            groups = []
            ant_nets = [n for n in general_rf if n.subcategory == 'antenna']
            sig_nets = [n for n in general_rf if n.subcategory != 'antenna']
            if ant_nets:
                groups.append(InterfaceSignalGroup(
                    group_name="Antenna", signal_type="data",
                    net_names=[n.net_name for n in ant_nets],
                    pin_count=len(ant_nets),
                ))
            if sig_nets:
                groups.append(InterfaceSignalGroup(
                    group_name="RF Signals", signal_type="data",
                    net_names=[n.net_name for n in sig_nets],
                    pin_count=len(sig_nets),
                ))

            total = len(general_rf)
            interfaces.append(DetectedInterface(
                interface_type="RF",
                description=f"RF ({total} signal(s))",
                confidence=0.80,
                signal_groups=groups,
                total_pins=total,
                associated_nets=[n.net_name for n in general_rf],
            ))

        # GPS/GNSS
        gps_nets = subcats.get('gps', []) + subcats.get('gnss', [])
        if gps_nets:
            groups = [InterfaceSignalGroup(
                group_name="GNSS", signal_type="data",
                net_names=[n.net_name for n in gps_nets],
                pin_count=len(gps_nets),
            )]
            interfaces.append(DetectedInterface(
                interface_type="GNSS",
                description=f"GNSS ({len(gps_nets)} signal(s))",
                confidence=0.85,
                signal_groups=groups,
                total_pins=len(gps_nets),
                associated_nets=[n.net_name for n in gps_nets],
            ))

        # LoRa
        lora_nets = subcats.get('lora', [])
        if lora_nets:
            groups = [InterfaceSignalGroup(
                group_name="LoRa", signal_type="data",
                net_names=[n.net_name for n in lora_nets],
                pin_count=len(lora_nets),
            )]
            interfaces.append(DetectedInterface(
                interface_type="LoRa",
                description=f"LoRa ({len(lora_nets)} signal(s))",
                confidence=0.85,
                signal_groups=groups,
                total_pins=len(lora_nets),
                associated_nets=[n.net_name for n in lora_nets],
            ))

        return interfaces
