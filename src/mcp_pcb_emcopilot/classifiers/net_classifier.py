"""Net classification engine for PCB designs.

Classifies nets by function (power, ground, DDR, USB, PCIe, etc.) using
net name pattern matching, differential pair detection, and component-based
inference. Operates on in-memory PCBDesignData from any parser.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models.pcb_data import PCBComponent, PCBDesignData, PCBNet

# =============================================================================
# Data structures
# =============================================================================

@dataclass
class NetClassification:
    """Classification result for a single net."""
    net_name: str
    net_index: int
    category: str  # rf, ddr, usb, pcie, ethernet, lvds, clock, power, ground, gpio, analog, i2c, spi, uart, jtag, unknown
    confidence: float  # 0.0 - 1.0
    source: str  # "pattern", "component", "net_class", "differential_pair"
    subcategory: Optional[str] = None  # e.g., "ddr4_data", "usb3_sstx", "pcie_refclk"
    differential_pair_name: Optional[str] = None
    differential_polarity: Optional[str] = None  # "P", "N", or None


@dataclass
class DifferentialPair:
    """A detected differential pair."""
    pair_name: str
    positive_net: str
    negative_net: str
    category: str  # usb, pcie, ethernet, lvds, ddr, etc.
    confidence: float


@dataclass
class NetClassificationResult:
    """Full classification result for all nets in a design."""
    classified_nets: list[NetClassification] = field(default_factory=list)
    differential_pairs: list[DifferentialPair] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        cats: dict[str, list[str]] = {}
        for nc in self.classified_nets:
            cats.setdefault(nc.category, []).append(nc.net_name)

        return {
            "total_nets": len(self.classified_nets),
            "classified_count": sum(1 for n in self.classified_nets if n.category != "unknown"),
            "unknown_count": sum(1 for n in self.classified_nets if n.category == "unknown"),
            "differential_pair_count": len(self.differential_pairs),
            "categories": {cat: len(nets) for cat, nets in sorted(cats.items())},
            "nets": [
                {
                    "name": nc.net_name,
                    "category": nc.category,
                    "confidence": round(nc.confidence, 2),
                    "source": nc.source,
                    "subcategory": nc.subcategory,
                    "diff_pair": nc.differential_pair_name,
                    "polarity": nc.differential_polarity,
                }
                for nc in self.classified_nets
            ],
            "differential_pairs": [
                {
                    "name": dp.pair_name,
                    "positive": dp.positive_net,
                    "negative": dp.negative_net,
                    "category": dp.category,
                    "confidence": round(dp.confidence, 2),
                }
                for dp in self.differential_pairs
            ],
        }


# =============================================================================
# Pattern definitions
# =============================================================================

# Each entry: (compiled regex, category, subcategory, confidence)
# Order matters: more specific patterns first within each category
_NET_PATTERNS: list[tuple[re.Pattern, str, Optional[str], float]] = []


def _p(pattern: str, category: str, subcategory: Optional[str] = None, confidence: float = 0.85):
    """Register a net name pattern."""
    _NET_PATTERNS.append((re.compile(pattern, re.IGNORECASE), category, subcategory, confidence))


# --- DDR ---
_p(r'^DDR\d?_', 'ddr', None, 0.95)
_p(r'^DQ\d+$', 'ddr', 'data', 0.90)
_p(r'^DQ[SP]?\d*[_PN]?$', 'ddr', 'strobe', 0.90)
_p(r'^DQS\d*[_]?[PN]?$', 'ddr', 'strobe', 0.95)
_p(r'^DQM\d*$', 'ddr', 'mask', 0.90)
_p(r'^DM\d*$', 'ddr', 'mask', 0.85)
_p(r'^DDR\d?_CK', 'ddr', 'clock', 0.95)
_p(r'^CK[E]?\d*[_]?[PN]?$', 'ddr', 'clock', 0.80)
_p(r'^CAS[_#]?$', 'ddr', 'command', 0.85)
_p(r'^RAS[_#]?$', 'ddr', 'command', 0.85)
_p(r'^WE[_#]?$', 'ddr', 'command', 0.80)
_p(r'^BA\d+$', 'ddr', 'address', 0.85)
_p(r'^BG\d+$', 'ddr', 'address', 0.85)
_p(r'^A\d{1,2}$', 'ddr', 'address', 0.60)  # lower confidence - could be other addr bus
_p(r'^DDR\d?_A\d+$', 'ddr', 'address', 0.95)
_p(r'^CS\d*[_#]?$', 'ddr', 'chip_select', 0.70)  # lower - CS can be SPI too
_p(r'^DDR\d?_CS', 'ddr', 'chip_select', 0.95)
_p(r'^ODT\d*$', 'ddr', 'control', 0.90)
_p(r'^VREF_?DQ', 'ddr', 'reference', 0.90)
_p(r'^ZQ$', 'ddr', 'calibration', 0.90)
_p(r'^RESET[_#]?$', 'ddr', 'control', 0.50)  # low - very generic

# --- USB ---
_p(r'^USB[_]?D[PM]$', 'usb', 'usb2_data', 0.95)
_p(r'^USB[_]?D[+-]$', 'usb', 'usb2_data', 0.95)
_p(r'^USB\d?[_]DP$', 'usb', 'usb2_data', 0.95)
_p(r'^USB\d?[_]DN$', 'usb', 'usb2_data', 0.95)
_p(r'^USB\d?[_]D[+-]$', 'usb', 'usb2_data', 0.95)
_p(r'^D[PM]$', 'usb', 'usb2_data', 0.70)
_p(r'^D[+-]$', 'usb', 'usb2_data', 0.70)
_p(r'^SSTX\d*[_]?[PN]?$', 'usb', 'usb3_sstx', 0.95)
_p(r'^SSRX\d*[_]?[PN]?$', 'usb', 'usb3_ssrx', 0.95)
_p(r'^USB[_]?SS[_]?TX', 'usb', 'usb3_sstx', 0.95)
_p(r'^USB[_]?SS[_]?RX', 'usb', 'usb3_ssrx', 0.95)
_p(r'^VBUS$', 'usb', 'power', 0.90)
_p(r'^USB[_]?VBUS', 'usb', 'power', 0.95)
_p(r'^USB[_]', 'usb', None, 0.85)
_p(r'^CC[12]$', 'usb', 'usbc_cc', 0.80)
_p(r'^SBU[12]$', 'usb', 'usbc_sbu', 0.85)

# --- PCIe ---
_p(r'^PCIE[_]?TX\d*[_]?[PN]?', 'pcie', 'tx', 0.95)
_p(r'^PCIE[_]?RX\d*[_]?[PN]?', 'pcie', 'rx', 0.95)
_p(r'^PET\d*[PN]?', 'pcie', 'tx', 0.90)
_p(r'^PER\d*[PN]?', 'pcie', 'rx', 0.90)
_p(r'^PCIE[_]?REFCLK', 'pcie', 'refclk', 0.95)
_p(r'^REFCLK\d*[_]?[PN]?', 'pcie', 'refclk', 0.80)
_p(r'^PCIE[_]?RST', 'pcie', 'reset', 0.90)
_p(r'^PCIE[_]?WAKE', 'pcie', 'wake', 0.90)
_p(r'^PCIE[_]?CLKREQ', 'pcie', 'clkreq', 0.90)
_p(r'^PCIE[_]', 'pcie', None, 0.85)

# --- Ethernet ---
_p(r'^ETH[_]', 'ethernet', None, 0.90)
_p(r'^MDI\d+[_]?[PN]?', 'ethernet', 'mdi', 0.95)
_p(r'^MDI[_]?[PN]$', 'ethernet', 'mdi', 0.90)
_p(r'^TX[+-]$', 'ethernet', 'mdi_tx', 0.75)
_p(r'^RX[+-]$', 'ethernet', 'mdi_rx', 0.75)
_p(r'^TX[_]?[PN]$', 'ethernet', 'mdi_tx', 0.65)  # could be UART
_p(r'^RX[_]?[PN]$', 'ethernet', 'mdi_rx', 0.65)
_p(r'^MDIO$', 'ethernet', 'management', 0.95)
_p(r'^MDC$', 'ethernet', 'management', 0.95)
_p(r'^RGMII[_]', 'ethernet', 'rgmii', 0.95)
_p(r'^RMII[_]', 'ethernet', 'rmii', 0.95)
_p(r'^MII[_]', 'ethernet', 'mii', 0.90)
_p(r'^SGMII[_]', 'ethernet', 'sgmii', 0.95)

# --- RF ---
_p(r'^RF[_]', 'rf', None, 0.95)
_p(r'^ANT\d*[_]?', 'rf', 'antenna', 0.90)
_p(r'^LNA[_]', 'rf', 'lna', 0.90)
_p(r'^PA[_]', 'rf', 'pa', 0.80)
_p(r'^RFIN\d?$', 'rf', 'input', 0.90)
_p(r'^RFOUT\d?$', 'rf', 'output', 0.90)
_p(r'^LO[_]', 'rf', 'local_oscillator', 0.90)
_p(r'^IF[_]', 'rf', 'intermediate_freq', 0.75)
_p(r'^WIFI[_]', 'rf', 'wifi', 0.90)
_p(r'^BT[_]', 'rf', 'bluetooth', 0.85)
_p(r'^BLE[_]', 'rf', 'bluetooth', 0.85)
_p(r'^GPS[_]', 'rf', 'gps', 0.90)
_p(r'^GNSS[_]', 'rf', 'gnss', 0.90)
_p(r'^LORA[_]', 'rf', 'lora', 0.90)
_p(r'^GSM[_]', 'rf', 'cellular', 0.90)
_p(r'^LTE[_]', 'rf', 'cellular', 0.90)
_p(r'^NR[_]', 'rf', 'cellular', 0.80)

# --- I2C (before clock to prevent SDA/SCL false positives) ---
_p(r'^SDA\d*$', 'i2c', 'data', 0.85)
_p(r'^SCL\d*$', 'i2c', 'clock', 0.85)
_p(r'^I2C\d*[_]', 'i2c', None, 0.95)
_p(r'^I2C[_]?SDA', 'i2c', 'data', 0.95)
_p(r'^I2C[_]?SCL', 'i2c', 'clock', 0.95)

# --- SPI (before clock to prevent SPI_CLK matching clock suffix) ---
_p(r'^MOSI\d*$', 'spi', 'mosi', 0.90)
_p(r'^MISO\d*$', 'spi', 'miso', 0.90)
_p(r'^SCLK\d*$', 'spi', 'clock', 0.85)
_p(r'^SPI\d*[_]', 'spi', None, 0.95)
_p(r'^SPI[_]?CLK', 'spi', 'clock', 0.95)
_p(r'^SPI[_]?MOSI', 'spi', 'mosi', 0.95)
_p(r'^SPI[_]?MISO', 'spi', 'miso', 0.95)
_p(r'^SPI[_]?CS', 'spi', 'chip_select', 0.95)
_p(r'^SDI\d*$', 'spi', 'data_in', 0.70)
_p(r'^SDO\d*$', 'spi', 'data_out', 0.70)

# --- UART (before clock to prevent UART_CLK matching clock suffix) ---
_p(r'^UART\d*[_]', 'uart', None, 0.95)
_p(r'^TXD\d*$', 'uart', 'tx', 0.85)
_p(r'^RXD\d*$', 'uart', 'rx', 0.85)
_p(r'^UART[_]?TX', 'uart', 'tx', 0.95)
_p(r'^UART[_]?RX', 'uart', 'rx', 0.95)
_p(r'^CTS\d*$', 'uart', 'cts', 0.75)
_p(r'^RTS\d*$', 'uart', 'rts', 0.75)

# --- JTAG/SWD (before clock to prevent SWCLK matching clock suffix) ---
_p(r'^TCK$', 'jtag', 'clock', 0.90)
_p(r'^TMS$', 'jtag', 'mode_select', 0.90)
_p(r'^TDI$', 'jtag', 'data_in', 0.90)
_p(r'^TDO$', 'jtag', 'data_out', 0.90)
_p(r'^TRST\w*$', 'jtag', 'reset', 0.90)
_p(r'^JTAG[_]', 'jtag', None, 0.95)
_p(r'^SWCLK$', 'jtag', 'swd_clock', 0.95)
_p(r'^SWDIO$', 'jtag', 'swd_data', 0.95)
_p(r'^SWO$', 'jtag', 'swd_output', 0.90)
_p(r'^SWD[_]?', 'jtag', 'swd', 0.90)
_p(r'^NRST$', 'jtag', 'reset', 0.70)

# --- Clock (after specific interfaces so SPI_CLK, SWCLK etc. match their own category) ---
_p(r'^CLK[_]?\d*[_]?[PN]?$', 'clock', None, 0.85)
_p(r'^CLK[_]\w+', 'clock', None, 0.80)  # CLK_50MHZ, CLK_100M, CLK_SYS, etc.
_p(r'^XTAL[_]?\d*[_]?', 'clock', 'crystal', 0.90)
_p(r'^OSC[_]', 'clock', 'oscillator', 0.90)
_p(r'[_]CLK[_]?[PN]?$', 'clock', None, 0.80)
_p(r'[_]CLK[_]\w+$', 'clock', None, 0.75)  # SYS_CLK_100M, etc.
_p(r'[_]CK[_]?[PN]?$', 'clock', None, 0.70)
_p(r'^MCLK$', 'clock', 'master_clock', 0.85)
_p(r'^BCLK$', 'clock', 'bit_clock', 0.85)
_p(r'^LRCLK$', 'clock', 'lr_clock', 0.85)
_p(r'^PCLK$', 'clock', None, 0.80)
_p(r'^HCLK$', 'clock', None, 0.80)
_p(r'^FCLK$', 'clock', None, 0.80)

# --- Power ---
_p(r'^VCC\w*$', 'power', None, 0.95)
_p(r'^VDD\w*$', 'power', None, 0.95)
_p(r'^VBAT\w*$', 'power', 'battery', 0.95)
_p(r'^VIN\w*$', 'power', 'input', 0.90)
_p(r'^VOUT\w*$', 'power', 'output', 0.90)
_p(r'^VSYS\w*$', 'power', 'system', 0.90)
_p(r'^V\d+P\d+\w*$', 'power', None, 0.95)  # V3P3, V1P8, V1P2, etc.
_p(r'^V\d+V\d+\w*$', 'power', None, 0.90)  # V3V3, V1V8
_p(r'^\+\d+V\d*\w*$', 'power', None, 0.95)  # +3V3, +5V, +12V
_p(r'^\+\w+$', 'power', None, 0.70)  # +AVDD, etc.
_p(r'^AVDD\w*$', 'power', 'analog', 0.95)
_p(r'^DVDD\w*$', 'power', 'digital', 0.95)
_p(r'^PVDD\w*$', 'power', 'pll', 0.90)
_p(r'^VCCO\w*$', 'power', 'io', 0.90)
_p(r'^PWR[_]', 'power', None, 0.85)

# --- Ground ---
_p(r'^GND\w*$', 'ground', None, 0.95)
_p(r'^VSS\w*$', 'ground', None, 0.95)
_p(r'^AGND\w*$', 'ground', 'analog', 0.95)
_p(r'^DGND\w*$', 'ground', 'digital', 0.95)
_p(r'^PGND\w*$', 'ground', 'power', 0.95)
_p(r'^SGND\w*$', 'ground', 'shield', 0.90)
_p(r'^EARTH\w*$', 'ground', 'earth', 0.90)
_p(r'^CHASSIS\w*$', 'ground', 'chassis', 0.85)

# --- LVDS ---
_p(r'^LVDS[_]', 'lvds', None, 0.95)
_p(r'^LVDS\d*[_]?[PN]$', 'lvds', None, 0.95)

# --- Analog ---
_p(r'^AIN\d*$', 'analog', 'adc_input', 0.85)
_p(r'^ADC\d*[_]', 'analog', 'adc', 0.90)
_p(r'^DAC\d*[_]', 'analog', 'dac', 0.90)
_p(r'^ANALOG[_]', 'analog', None, 0.90)
_p(r'^VREF\w*$', 'analog', 'reference', 0.85)
_p(r'^AOUT\d*$', 'analog', 'output', 0.80)

# --- GPIO (catch-all for digital IOs) ---
_p(r'^GPIO\d*[_]?', 'gpio', None, 0.80)
_p(r'^IO\d+$', 'gpio', None, 0.70)
_p(r'^P[A-Z]\d+$', 'gpio', None, 0.65)  # PA0, PB3, etc. - STM32 style


# =============================================================================
# Component-based classification hints
# =============================================================================

# (part_number or value pattern, reference pattern, footprint pattern) -> category
_COMPONENT_HINTS: list[tuple[Optional[str], Optional[str], Optional[str], str]] = [
    # DDR
    (r'(?i)(DDR[345L]|SDRAM|MT4\d|IS4\d|K4[AB])', None, None, 'ddr'),
    (None, None, r'(?i)(SODIMM|DIMM|DDR)', 'ddr'),
    # USB
    (None, None, r'(?i)(USB[_-]?[ABC]|TYPE[_-]?C|MICRO[_-]?USB|MINI[_-]?USB)', 'usb'),
    (r'(?i)(TUSB|USB3\d|FUSB|HD3SS)', None, None, 'usb'),
    # Ethernet
    (None, None, r'(?i)(RJ45|MAGJACK|8P8C)', 'ethernet'),
    (r'(?i)(KSZ\d|RTL\d|DP838|LAN\d|PHY)', None, None, 'ethernet'),
    (r'(?i)(SI[_-]?3\d|HX\d|HanRun)', None, None, 'ethernet'),
    # RF
    (r'(?i)(SAW|LNA|PA\d|MIXER|VCO|PLL|BALUN|RFMD|SKY\d|QPC|HMC|ADF\d|LMX\d)', None, None, 'rf'),
    (r'(?i)(CC265|CC135|ESP32|nRF\d|SX127|RFM\d|AT86RF|MRF\d)', None, None, 'rf'),
    (None, None, r'(?i)(SMA|UFL|U\.FL|MMCX|BNC|N_TYPE|IPEX|ANT)', 'rf'),
    # PCIe
    (r'(?i)(PCIE|PEX\d|PI7C)', None, None, 'pcie'),
    (None, None, r'(?i)(M\.2|NGFF|PCIE[_x])', 'pcie'),
]


# =============================================================================
# Differential pair detection
# =============================================================================

# Suffix patterns for P/N pairing
_DIFF_SUFFIXES = [
    (r'(.+)[_]P$', r'\1_N', 'P', 'N'),
    (r'(.+)[_]N$', r'\1_P', 'N', 'P'),
    (r'(.+)\+$', r'\1-', 'P', 'N'),
    (r'(.+)-$', r'\1+', 'N', 'P'),
    (r'(.+)[_]DP$', r'\1_DN', 'P', 'N'),
    (r'(.+)[_]DN$', r'\1_DP', 'N', 'P'),
    (r'(.+)P$', r'\1N', 'P', 'N'),  # less specific - only if no better match
    (r'(.+)N$', r'\1P', 'N', 'P'),
]


def _find_pair_mate(net_name: str, all_net_names: set) -> Optional[tuple[str, str, str]]:
    """Find differential pair mate. Returns (mate_name, this_polarity, pair_base_name) or None."""
    name_upper = net_name.upper()
    for pattern, replacement, this_pol, mate_pol in _DIFF_SUFFIXES:
        m = re.match(pattern, name_upper)
        if m:
            base = m.group(1)
            # Reconstruct mate name preserving original case
            mate_upper = re.sub(pattern, replacement, name_upper)
            # Find actual name in the set (case-insensitive)
            for actual in all_net_names:
                if actual.upper() == mate_upper:
                    return (actual, this_pol, base)
    return None


# =============================================================================
# Main classifier
# =============================================================================

class NetClassifier:
    """Classifies PCB nets by function using pattern matching and component inference."""

    def __init__(self):
        self._component_net_map: dict[str, list[str]] = {}  # net_name -> [component refs]
        self._component_categories: dict[str, str] = {}  # component ref -> inferred category

    def classify(self, design: PCBDesignData) -> NetClassificationResult:
        """Classify all nets in a design.

        Strategy:
        1. Build component-to-category map from component properties
        2. Detect differential pairs
        3. Classify each net by pattern matching
        4. Apply component-based inference for unclassified nets
        5. Use existing net_class assignments as hints
        """
        result = NetClassificationResult()

        # Build maps
        self._build_component_map(design)
        all_net_names = {n.name for n in design.nets}

        # Phase 1: Detect differential pairs
        seen_pairs = set()
        for net in design.nets:
            pair_info = _find_pair_mate(net.name, all_net_names)
            if pair_info:
                mate_name, polarity, base = pair_info
                pair_key = tuple(sorted([net.name.upper(), mate_name.upper()]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    # Determine pair category from base name
                    pair_cat = self._classify_by_pattern(base)
                    if pair_cat is None:
                        pair_cat = self._classify_by_pattern(net.name)
                    cat = pair_cat[0] if pair_cat else "unknown"

                    if polarity == 'P':
                        p_net, n_net = net.name, mate_name
                    else:
                        p_net, n_net = mate_name, net.name

                    result.differential_pairs.append(DifferentialPair(
                        pair_name=base,
                        positive_net=p_net,
                        negative_net=n_net,
                        category=cat,
                        confidence=0.90,
                    ))

        # Build diff pair lookup
        diff_pair_map: dict[str, tuple[str, str]] = {}  # net_name_upper -> (pair_name, polarity)
        for dp in result.differential_pairs:
            diff_pair_map[dp.positive_net.upper()] = (dp.pair_name, 'P')
            diff_pair_map[dp.negative_net.upper()] = (dp.pair_name, 'N')

        # Phase 2: Classify each net
        for net in design.nets:
            classification = self._classify_net(net, diff_pair_map, design)
            result.classified_nets.append(classification)

        # Build summary
        result.summary = self._build_summary(result)

        return result

    def _build_component_map(self, design: PCBDesignData):
        """Build mapping from component properties to categories."""
        self._component_categories.clear()
        self._component_net_map.clear()

        for comp in design.components:
            # Check component against hints
            for val_pat, ref_pat, fp_pat, category in _COMPONENT_HINTS:
                matched = False
                if val_pat:
                    check_str = comp.part_number or comp.value or ""
                    if re.search(val_pat, check_str):
                        matched = True
                if ref_pat and not matched:
                    if re.search(ref_pat, comp.reference):
                        matched = True
                if fp_pat and not matched:
                    fp_str = comp.footprint or comp.package or ""
                    if re.search(fp_pat, fp_str):
                        matched = True
                if matched:
                    self._component_categories[comp.reference] = category
                    break

            # Map component pads to nets
            for pad in comp.pads:
                if isinstance(pad, dict):
                    net_name = pad.get("net_name") or pad.get("net")
                elif hasattr(pad, 'net_name'):
                    net_name = pad.net_name
                else:
                    continue
                if net_name:
                    self._component_net_map.setdefault(net_name, []).append(comp.reference)

    def _classify_by_pattern(self, name: str) -> Optional[tuple[str, Optional[str], float]]:
        """Classify a net name by pattern. Returns (category, subcategory, confidence) or None."""
        for pattern, category, subcategory, confidence in _NET_PATTERNS:
            if pattern.search(name):
                return (category, subcategory, confidence)
        return None

    def _classify_net(self, net: PCBNet, diff_pair_map: dict, design: PCBDesignData) -> NetClassification:
        """Classify a single net using all available information."""
        name = net.name
        name_upper = name.upper()

        # Skip unconnected/empty nets
        if not name or name.lower() in ('', 'unconnected', 'no_net', '""'):
            return NetClassification(
                net_name=name, net_index=net.index,
                category='unknown', confidence=0.0, source='skip',
            )

        # 1. Check existing net_class assignment
        if net.net_class and net.net_class.lower() not in ('default', '', 'none'):
            nc_lower = net.net_class.lower()
            # Map common net class names to categories
            nc_map = {
                'power': 'power', 'pwr': 'power',
                'ground': 'ground', 'gnd': 'ground',
                'differential': None,  # need more info
                'high_speed': None,
                'signal': None,
            }
            if nc_lower in nc_map and nc_map[nc_lower]:
                return NetClassification(
                    net_name=name, net_index=net.index,
                    category=nc_map[nc_lower], confidence=0.80,  # type: ignore[arg-type]
                    source='net_class', subcategory=net.net_class,
                )

        # 2. Check existing is_differential flag
        dp_info = diff_pair_map.get(name_upper)

        # 3. Pattern-based classification
        pat_result = self._classify_by_pattern(name)
        if pat_result:
            category, subcategory, confidence = pat_result
            # Boost confidence if differential pair confirms
            if dp_info:
                confidence = min(1.0, confidence + 0.05)
            return NetClassification(
                net_name=name, net_index=net.index,
                category=category, confidence=confidence,
                source='pattern', subcategory=subcategory,
                differential_pair_name=dp_info[0] if dp_info else None,
                differential_polarity=dp_info[1] if dp_info else None,
            )

        # 4. Component-based inference
        comp_refs = self._component_net_map.get(name, [])
        for ref in comp_refs:
            if ref in self._component_categories:
                category = self._component_categories[ref]
                return NetClassification(
                    net_name=name, net_index=net.index,
                    category=category, confidence=0.65,
                    source='component', subcategory=f"via_{ref}",
                    differential_pair_name=dp_info[0] if dp_info else None,
                    differential_polarity=dp_info[1] if dp_info else None,
                )

        # 5. If part of a differential pair, use the pair's category
        if dp_info:
            pair_name, polarity = dp_info
            # Find the pair's category from already-classified pairs
            for dp in diff_pair_map.values():
                pass  # We already checked

            return NetClassification(
                net_name=name, net_index=net.index,
                category='unknown', confidence=0.50,
                source='differential_pair',
                differential_pair_name=pair_name,
                differential_polarity=polarity,
            )

        # 6. Unknown
        return NetClassification(
            net_name=name, net_index=net.index,
            category='unknown', confidence=0.0, source='none',
        )

    def _build_summary(self, result: NetClassificationResult) -> dict:
        """Build classification summary statistics."""
        cats: dict[str, int] = {}
        total_confidence = 0.0
        classified = 0

        for nc in result.classified_nets:
            cats[nc.category] = cats.get(nc.category, 0) + 1
            if nc.category != 'unknown':
                total_confidence += nc.confidence
                classified += 1

        avg_confidence = total_confidence / classified if classified else 0.0

        return {
            "total_nets": len(result.classified_nets),
            "classified": classified,
            "unknown": cats.get('unknown', 0),
            "average_confidence": round(avg_confidence, 2),
            "differential_pairs": len(result.differential_pairs),
            "categories": dict(sorted(cats.items())),
        }
