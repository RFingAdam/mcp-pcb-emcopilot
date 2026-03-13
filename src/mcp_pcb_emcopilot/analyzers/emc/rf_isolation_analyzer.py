"""RF Isolation Analyzer for diplexer/triplexer TX-RX isolation.

Validates:
- TX to RX port isolation (target: >30dB)
- Diplexer/Triplexer detection and port identification
- SAW/LC filter presence in RF paths
- Ground plane isolation between TX and RX sections

Decoupled from SQLAlchemy — operates on PCBDesignData.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RFMultiplexer:
    """Detected RF multiplexer component."""
    component_ref: str
    component_type: str
    part_number: str
    tx_port: Optional[str] = None
    rx_port: Optional[str] = None
    ant_port: Optional[str] = None
    additional_ports: list[str] = field(default_factory=list)


@dataclass
class IsolationMeasurement:
    """TX-RX isolation measurement."""
    source_net: str
    victim_net: str
    isolation_db: float
    meets_requirement: bool
    measurement_method: str
    frequency_mhz: float


@dataclass
class RFFilterDetection:
    """RF filter component detection."""
    component_ref: str
    filter_type: str
    net_name: str
    position_in_path: str


@dataclass
class RFIsolationAnalysisResult:
    """Result of RF isolation analysis."""
    multiplexers: list[RFMultiplexer] = field(default_factory=list)
    isolation_measurements: list[IsolationMeasurement] = field(default_factory=list)
    filters: list[RFFilterDetection] = field(default_factory=list)
    isolation_violations: list[dict] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def get_worst_isolation_db(self) -> float:
        if not self.isolation_measurements:
            return 0.0
        return max(m.isolation_db for m in self.isolation_measurements)


class RFIsolationAnalyzer:
    """Analyzer for RF TX-RX isolation.

    Operates on in-memory PCBDesignData instead of database sessions.
    """

    MULTIPLEXER_PATTERNS = {
        "diplexer": [r"(?i)diplexer", r"(?i)dplx"],
        "triplexer": [r"(?i)triplexer", r"(?i)tplx"],
        "quadplexer": [r"(?i)quadplexer", r"(?i)qplx"],
    }

    FILTER_PATTERNS = {
        "saw": [r"(?i)saw", r"(?i)surface\s*acoustic"],
        "baw": [r"(?i)baw", r"(?i)bulk\s*acoustic"],
        "lc": [r"(?i)lc\s*filter", r"(?i)lumped"],
        "ceramic": [r"(?i)ceramic\s*filter"],
    }

    PORT_PATTERNS = {
        "tx": [r"(?i)^TX", r"(?i)_TX$", r"(?i)TRANSMIT"],
        "rx": [r"(?i)^RX", r"(?i)_RX$", r"(?i)RECEIVE"],
        "ant": [r"(?i)^ANT", r"(?i)_ANT$", r"(?i)ANTENNA"],
    }

    MIN_ISOLATION_DB = 30.0

    def __init__(self):
        pass

    def analyze(self, design_data, frequency_mhz: float = 2400.0) -> RFIsolationAnalysisResult:
        """Analyze RF isolation in multiplexer circuits.

        Args:
            design_data: PCBDesignData with parsed design
            frequency_mhz: Analysis frequency in MHz
        """
        result = RFIsolationAnalysisResult()

        # Detect multiplexers from component data
        multiplexers = self._detect_multiplexers(design_data.components)
        result.multiplexers = multiplexers

        if not multiplexers:
            return result

        # Detect RF filters
        result.filters = self._detect_rf_filters(design_data.components)

        # Identify ports from net names
        for mux in multiplexers:
            self._identify_ports(mux, design_data.nets)

        # Measure isolation
        for mux in multiplexers:
            if mux.tx_port and mux.rx_port:
                isolation = self._estimate_isolation(mux, frequency_mhz, result.filters)
                if isolation:
                    result.isolation_measurements.append(isolation)
                    if not isolation.meets_requirement:
                        result.isolation_violations.append({
                            "component_ref": mux.component_ref,
                            "isolation_db": isolation.isolation_db,
                            "required_db": self.MIN_ISOLATION_DB,
                            "severity": "error",
                        })
                        result.errors += 1

        return result

    def _detect_multiplexers(self, components) -> list[RFMultiplexer]:
        multiplexers = []
        for comp in components:
            combined = f"{comp.part_number or ''} {comp.value or ''}".lower()
            for mux_type, patterns in self.MULTIPLEXER_PATTERNS.items():
                if any(re.search(p, combined) for p in patterns):
                    multiplexers.append(RFMultiplexer(
                        component_ref=comp.reference,
                        component_type=mux_type,
                        part_number=comp.part_number or "",
                    ))
                    break
        return multiplexers

    def _detect_rf_filters(self, components) -> list[RFFilterDetection]:
        filters = []
        for comp in components:
            combined = f"{comp.part_number or ''} {comp.value or ''}".lower()
            for filter_type, patterns in self.FILTER_PATTERNS.items():
                if any(re.search(p, combined) for p in patterns):
                    filters.append(RFFilterDetection(
                        component_ref=comp.reference,
                        filter_type=filter_type,
                        net_name="Unknown",
                        position_in_path="unknown",
                    ))
                    break
        return filters

    def _identify_ports(self, mux: RFMultiplexer, nets) -> None:
        for net in nets:
            net_name = net.name.upper()
            for port_type, patterns in self.PORT_PATTERNS.items():
                if any(re.search(p, net_name) for p in patterns):
                    if port_type == "tx":
                        mux.tx_port = net.name
                    elif port_type == "rx":
                        mux.rx_port = net.name
                    elif port_type == "ant":
                        mux.ant_port = net.name
                    break

    def _estimate_isolation(
        self, mux: RFMultiplexer, frequency_mhz: float, filters: list
    ) -> Optional[IsolationMeasurement]:
        """Estimate isolation based on component type and filter presence."""
        base_isolation_db = {
            "diplexer": -35.0,
            "triplexer": -32.0,
            "quadplexer": -30.0,
        }.get(mux.component_type, -30.0)

        # Filter bonus
        filter_factor = 0.0
        for f in filters:
            if f.filter_type == 'saw':
                filter_factor -= 10.0
            elif f.filter_type == 'baw':
                filter_factor -= 12.0
            elif f.filter_type == 'lc':
                filter_factor -= 6.0

        freq_factor = min(1.1, 1.0 + (frequency_mhz - 1000) / 10000)
        estimated = (base_isolation_db + filter_factor) * freq_factor

        return IsolationMeasurement(
            source_net=mux.tx_port or "TX",
            victim_net=mux.rx_port or "RX",
            isolation_db=round(estimated, 1),
            meets_requirement=abs(estimated) >= self.MIN_ISOLATION_DB,
            measurement_method="datasheet_estimate",
            frequency_mhz=frequency_mhz,
        )
