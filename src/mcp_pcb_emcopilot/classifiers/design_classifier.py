"""Overall PCB design classification.

Classifies a design by type (RF, mixed-signal, digital, power, etc.)
and computes a complexity score based on the design characteristics.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.pcb_data import PCBDesignData
from .interface_detector import InterfaceDetectionResult, InterfaceDetector
from .net_classifier import NetClassificationResult, NetClassifier

# =============================================================================
# Data structures
# =============================================================================

@dataclass
class DesignCharacteristic:
    """A notable characteristic found in the design."""
    name: str
    category: str  # interface, power, rf, complexity, physical
    description: str
    impact: str  # "high", "medium", "low"
    score_contribution: float  # contribution to complexity score


@dataclass
class DesignClassificationResult:
    """Classification result for a PCB design."""
    design_type: str  # rf, mixed_signal, high_speed_digital, power, simple_digital
    design_type_confidence: float
    complexity_score: float  # 1-10
    complexity_label: str  # "simple", "moderate", "complex", "very_complex"
    characteristics: list[DesignCharacteristic] = field(default_factory=list)
    secondary_types: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "design_type": self.design_type,
            "design_type_confidence": round(self.design_type_confidence, 2),
            "complexity_score": round(self.complexity_score, 1),
            "complexity_label": self.complexity_label,
            "secondary_types": self.secondary_types,
            "characteristics": [
                {
                    "name": c.name,
                    "category": c.category,
                    "description": c.description,
                    "impact": c.impact,
                }
                for c in self.characteristics
            ],
            "recommendations": self.recommendations,
        }


# =============================================================================
# Design type scoring weights
# =============================================================================

# Each design type has scoring rules based on net categories and interfaces
_TYPE_SIGNALS: dict[str, dict[str, Any]] = {
    'rf': {
        'net_categories': {'rf': 3.0},
        'interfaces': {'RF': 2.0, 'WiFi': 1.5, 'Bluetooth': 1.5, 'Cellular': 2.0, 'GNSS': 1.5, 'LoRa': 1.5},
        'component_hints': ['rf', 'antenna', 'lna', 'pa', 'mixer', 'vco', 'saw', 'balun'],
    },
    'high_speed_digital': {
        'net_categories': {'ddr': 2.0, 'pcie': 2.0, 'usb': 1.5, 'ethernet': 1.5, 'lvds': 1.5},
        'interfaces': {'DDR': 3.0, 'PCIe': 2.5, 'USB 3': 2.0, 'GbE': 1.5, 'SGMII': 2.0, 'LVDS': 1.5},
        'component_hints': ['ddr', 'pcie', 'usb3', 'fpga', 'processor'],
    },
    'mixed_signal': {
        'net_categories': {'analog': 2.0, 'rf': 1.0, 'ddr': 0.5, 'usb': 0.5},
        'interfaces': {},
        'component_hints': ['adc', 'dac', 'analog', 'opamp'],
    },
    'power': {
        'net_categories': {'power': 1.0},
        'interfaces': {},
        'component_hints': ['vrm', 'buck', 'boost', 'ldo', 'mosfet', 'igbt', 'transformer'],
    },
    'simple_digital': {
        'net_categories': {'gpio': 1.0, 'i2c': 0.5, 'spi': 0.5, 'uart': 0.5},
        'interfaces': {'USB 2.0': 0.5},
        'component_hints': ['mcu', 'microcontroller', 'led', 'relay'],
    },
}


# =============================================================================
# Design classifier
# =============================================================================

class DesignClassifier:
    """Classifies overall PCB design type and computes complexity score."""

    def __init__(self):
        self._net_classifier = NetClassifier()
        self._interface_detector = InterfaceDetector()

    def classify(
        self,
        design: PCBDesignData,
        net_classification: Optional[NetClassificationResult] = None,
        interface_detection: Optional[InterfaceDetectionResult] = None,
    ) -> DesignClassificationResult:
        """Classify the overall design type and complexity.

        Args:
            design: Parsed PCB design data.
            net_classification: Pre-computed net classification (optional).
            interface_detection: Pre-computed interface detection (optional).

        Returns:
            DesignClassificationResult with type, complexity, and characteristics.
        """
        if net_classification is None:
            net_classification = self._net_classifier.classify(design)
        if interface_detection is None:
            interface_detection = self._interface_detector.detect(design, net_classification)

        # Score each design type
        type_scores = self._score_design_types(design, net_classification, interface_detection)

        # Determine primary and secondary types
        sorted_types = sorted(type_scores.items(), key=lambda x: x[1], reverse=True)
        primary_type = sorted_types[0][0] if sorted_types else 'simple_digital'
        primary_score = sorted_types[0][1] if sorted_types else 0.0

        # Promote to mixed_signal if both analog and digital are strong
        analog_score = type_scores.get('mixed_signal', 0) + type_scores.get('rf', 0)
        digital_score = type_scores.get('high_speed_digital', 0) + type_scores.get('simple_digital', 0)
        if analog_score > 2.0 and digital_score > 2.0:
            primary_type = 'mixed_signal'
            primary_score = analog_score + digital_score

        # Confidence based on score separation
        secondary_types = []
        for t, s in sorted_types:
            if t != primary_type and s > 1.0:
                secondary_types.append(t)

        total_score = sum(s for _, s in sorted_types)
        confidence = min(0.95, primary_score / max(total_score, 1.0) + 0.3) if primary_score > 0 else 0.3

        # Compute complexity score
        characteristics = self._identify_characteristics(design, net_classification, interface_detection)
        complexity = self._compute_complexity(design, net_classification, interface_detection, characteristics)

        complexity_label = (
            "simple" if complexity <= 3.0
            else "moderate" if complexity <= 5.5
            else "complex" if complexity <= 8.0
            else "very_complex"
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(
            primary_type, characteristics, design, net_classification, interface_detection
        )

        return DesignClassificationResult(
            design_type=primary_type,
            design_type_confidence=confidence,
            complexity_score=complexity,
            complexity_label=complexity_label,
            characteristics=characteristics,
            secondary_types=secondary_types,
            recommendations=recommendations,
        )

    def _score_design_types(
        self, design: PCBDesignData,
        net_cls: NetClassificationResult,
        iface_det: InterfaceDetectionResult,
    ) -> dict[str, float]:
        """Score each design type based on found signals and interfaces."""
        scores: dict[str, float] = {t: 0.0 for t in _TYPE_SIGNALS}

        # Count nets by category
        cat_counts: dict[str, int] = {}
        for nc in net_cls.classified_nets:
            cat_counts[nc.category] = cat_counts.get(nc.category, 0) + 1

        # Score based on net categories
        for dtype, config in _TYPE_SIGNALS.items():
            for cat, weight in config['net_categories'].items():
                count = cat_counts.get(cat, 0)
                if count > 0:
                    # Logarithmic scaling so 100 DDR nets don't dominate
                    import math
                    scores[dtype] += weight * math.log2(count + 1)

        # Score based on detected interfaces
        for iface in iface_det.interfaces:
            for dtype, config in _TYPE_SIGNALS.items():
                for iface_pattern, weight in config['interfaces'].items():
                    if iface_pattern.lower() in iface.interface_type.lower():
                        scores[dtype] += weight * iface.confidence

        # Score based on component hints
        comp_text = " ".join(
            f"{c.reference} {c.value or ''} {c.footprint or ''} {c.package or ''} {c.part_number or ''}"
            for c in design.components
        ).lower()

        for dtype, config in _TYPE_SIGNALS.items():
            for hint in config['component_hints']:
                if hint in comp_text:
                    scores[dtype] += 0.5

        return scores

    def _identify_characteristics(
        self, design: PCBDesignData,
        net_cls: NetClassificationResult,
        iface_det: InterfaceDetectionResult,
    ) -> list[DesignCharacteristic]:
        """Identify notable design characteristics."""
        chars = []

        # Layer count
        copper_layers = len(design.get_copper_layers()) or design.layer_count
        if copper_layers >= 8:
            chars.append(DesignCharacteristic(
                name=f"{copper_layers}-layer stackup",
                category="physical", impact="high",
                description=f"Board has {copper_layers} copper layers indicating complex routing requirements",
                score_contribution=1.5,
            ))
        elif copper_layers >= 4:
            chars.append(DesignCharacteristic(
                name=f"{copper_layers}-layer stackup",
                category="physical", impact="medium",
                description=f"Board has {copper_layers} copper layers",
                score_contribution=0.5,
            ))

        # Component count
        comp_count = design.component_count
        if comp_count > 500:
            chars.append(DesignCharacteristic(
                name=f"{comp_count} components",
                category="complexity", impact="high",
                description="High component count indicates complex design",
                score_contribution=1.5,
            ))
        elif comp_count > 200:
            chars.append(DesignCharacteristic(
                name=f"{comp_count} components",
                category="complexity", impact="medium",
                description="Moderate component count",
                score_contribution=0.8,
            ))
        elif comp_count > 50:
            chars.append(DesignCharacteristic(
                name=f"{comp_count} components",
                category="complexity", impact="low",
                description="Typical component count",
                score_contribution=0.3,
            ))

        # Net count
        net_count = design.net_count
        if net_count > 1000:
            chars.append(DesignCharacteristic(
                name=f"{net_count} nets",
                category="complexity", impact="high",
                description="Very high net count",
                score_contribution=1.0,
            ))
        elif net_count > 300:
            chars.append(DesignCharacteristic(
                name=f"{net_count} nets",
                category="complexity", impact="medium",
                description="Moderate net count",
                score_contribution=0.5,
            ))

        # Differential pairs
        diff_count = len(net_cls.differential_pairs)
        if diff_count > 20:
            chars.append(DesignCharacteristic(
                name=f"{diff_count} differential pairs",
                category="interface", impact="high",
                description="Many differential pairs indicate high-speed signaling",
                score_contribution=1.5,
            ))
        elif diff_count > 5:
            chars.append(DesignCharacteristic(
                name=f"{diff_count} differential pairs",
                category="interface", impact="medium",
                description="Multiple differential pairs present",
                score_contribution=0.8,
            ))
        elif diff_count > 0:
            chars.append(DesignCharacteristic(
                name=f"{diff_count} differential pair(s)",
                category="interface", impact="low",
                description="Some differential signaling",
                score_contribution=0.3,
            ))

        # Detected interfaces
        for iface in iface_det.interfaces:
            impact = "high" if iface.total_pins > 20 else "medium" if iface.total_pins > 5 else "low"
            score = 1.0 if impact == "high" else 0.5 if impact == "medium" else 0.2
            chars.append(DesignCharacteristic(
                name=f"{iface.interface_type} interface",
                category="interface", impact=impact,
                description=iface.description,
                score_contribution=score,
            ))

        # Power domains
        cat_counts: dict[str, int] = {}
        for nc in net_cls.classified_nets:
            cat_counts[nc.category] = cat_counts.get(nc.category, 0) + 1

        power_count = cat_counts.get('power', 0)
        if power_count > 10:
            chars.append(DesignCharacteristic(
                name=f"{power_count} power nets",
                category="power", impact="high",
                description="Many power nets indicate complex power distribution",
                score_contribution=1.0,
            ))
        elif power_count > 3:
            chars.append(DesignCharacteristic(
                name=f"{power_count} power nets",
                category="power", impact="medium",
                description="Multiple power rails present",
                score_contribution=0.4,
            ))

        # Mixed analog/digital
        analog_count = cat_counts.get('analog', 0) + cat_counts.get('rf', 0)
        digital_count = (cat_counts.get('ddr', 0) + cat_counts.get('usb', 0) +
                         cat_counts.get('pcie', 0) + cat_counts.get('spi', 0) +
                         cat_counts.get('i2c', 0) + cat_counts.get('gpio', 0))
        if analog_count > 0 and digital_count > 0:
            chars.append(DesignCharacteristic(
                name="Mixed-signal design",
                category="complexity", impact="high",
                description=f"Both analog ({analog_count} nets) and digital ({digital_count} nets) domains present",
                score_contribution=1.0,
            ))

        # Board size
        area_mm2 = design.board_width_mm * design.board_height_mm
        if area_mm2 > 0:
            if comp_count > 0 and area_mm2 > 0:
                density = comp_count / (area_mm2 / 100)  # components per cm^2
                if density > 5:
                    chars.append(DesignCharacteristic(
                        name=f"High component density ({density:.1f}/cm^2)",
                        category="physical", impact="high",
                        description="Dense component placement requires careful routing",
                        score_contribution=1.0,
                    ))
                elif density > 2:
                    chars.append(DesignCharacteristic(
                        name=f"Moderate component density ({density:.1f}/cm^2)",
                        category="physical", impact="medium",
                        description="Moderate component density",
                        score_contribution=0.4,
                    ))

        # Via count and types
        via_count = design.via_count
        if via_count > 500:
            chars.append(DesignCharacteristic(
                name=f"{via_count} vias",
                category="complexity", impact="medium",
                description="High via count",
                score_contribution=0.5,
            ))

        blind_buried = [v for v in design.vias if v.via_type in ('blind', 'buried', 'microvia')]
        if blind_buried:
            chars.append(DesignCharacteristic(
                name=f"{len(blind_buried)} blind/buried/micro vias",
                category="complexity", impact="high",
                description="Advanced via technology in use",
                score_contribution=1.0,
            ))

        return chars

    def _compute_complexity(
        self, design: PCBDesignData,
        net_cls: NetClassificationResult,
        iface_det: InterfaceDetectionResult,
        characteristics: list[DesignCharacteristic],
    ) -> float:
        """Compute complexity score (1-10)."""
        # Base score from characteristics
        raw_score = sum(c.score_contribution for c in characteristics)

        # Additional factors
        # Multiple interfaces increase complexity
        iface_count = len(iface_det.interfaces)
        raw_score += min(iface_count * 0.3, 2.0)

        # Unknown nets (poor naming) add complexity for the reviewer
        unknown_ratio = net_cls.summary.get('unknown', 0) / max(net_cls.summary.get('total_nets', 1), 1)
        if unknown_ratio > 0.5 and design.net_count > 20:
            raw_score += 0.5  # Hard to review if nets are poorly named

        # Clamp to 1-10
        return max(1.0, min(10.0, raw_score + 1.0))

    def _generate_recommendations(
        self,
        primary_type: str,
        characteristics: list[DesignCharacteristic],
        design: PCBDesignData,
        net_cls: NetClassificationResult,
        iface_det: InterfaceDetectionResult,
    ) -> list[str]:
        """Generate design review recommendations."""
        recs = []

        # Type-specific recommendations
        if primary_type == 'rf':
            recs.append("RF design: verify controlled impedance on RF traces, check isolation between RF and digital sections")
            recs.append("Ensure solid ground planes under RF traces with no splits or voids")
        elif primary_type == 'high_speed_digital':
            recs.append("High-speed digital: verify differential pair impedance matching and length matching")
            recs.append("Check reference plane continuity under high-speed signals")
        elif primary_type == 'mixed_signal':
            recs.append("Mixed-signal: verify analog/digital ground partitioning strategy")
            recs.append("Check for digital noise coupling into analog signal paths")
        elif primary_type == 'power':
            recs.append("Power design: verify copper weight and trace widths for current capacity")
            recs.append("Check thermal relief on power planes and via thermal paths")

        # Interface-specific recommendations
        for iface in iface_det.interfaces:
            itype = iface.interface_type.lower()
            if 'ddr' in itype:
                recs.append(f"{iface.interface_type}: run length matching analysis on data/strobe groups")
                recs.append(f"{iface.interface_type}: verify fly-by topology for address/command lines")
            elif 'pcie' in itype:
                recs.append(f"{iface.interface_type}: check AC coupling cap placement near transmitter")
                recs.append(f"{iface.interface_type}: verify insertion loss budget for trace length")
            elif 'usb' in itype and '3' in iface.interface_type:
                recs.append(f"{iface.interface_type}: verify 90-ohm differential impedance for SuperSpeed pairs")
            elif 'gbe' in itype or 'ethernet' in itype.lower():
                recs.append(f"{iface.interface_type}: verify MDI pair symmetry and skew")

        # Characteristic-based recommendations
        has_diff = any(c.name.endswith('differential pairs') for c in characteristics)
        if has_diff:
            recs.append("Run differential pair skew analysis to verify length matching")

        has_many_power = any('power nets' in c.name and c.impact == 'high' for c in characteristics)
        if has_many_power:
            recs.append("Complex power distribution: analyze PDN impedance for each rail")

        has_blind_buried = any('blind/buried' in c.name for c in characteristics)
        if has_blind_buried:
            recs.append("Advanced via types detected: verify DFM constraints with your PCB fabricator")

        # Generic recommendations
        if design.layer_count <= 2 and len(iface_det.interfaces) > 0:
            recs.append("2-layer board with high-speed interfaces: consider upgrading to 4+ layers for better signal integrity")

        return recs
