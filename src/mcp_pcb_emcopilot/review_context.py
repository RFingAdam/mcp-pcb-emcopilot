"""Review context — identifies missing information and stores user answers.

When the MCP tool runs a design review and encounters ambiguity or missing
information, this module determines what questions need answering and provides
typed access to the user-supplied answers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .classifiers.design_classifier import DesignClassificationResult
from .classifiers.net_classifier import NetClassificationResult
from .models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# =============================================================================
# Question definitions
# =============================================================================

REVIEW_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "ddr_standard",
        "category": "interfaces",
        "text": "What DDR standard is used in this design?",
        "type": "choice",
        "choices": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"],
        "default": None,
        "why": "DDR standard determines timing margins, impedance targets, and length-matching rules.",
    },
    {
        "id": "emmc_speed_mode",
        "category": "interfaces",
        "text": "What eMMC speed mode is the design targeting?",
        "type": "choice",
        "choices": ["HS200", "HS400", "legacy"],
        "default": "HS200",
        "why": "eMMC speed mode sets data-strobe requirements and trace length constraints.",
    },
    {
        "id": "usb_version",
        "category": "interfaces",
        "text": "What USB version is used?",
        "type": "choice",
        "choices": ["USB2.0", "USB3.0", "USB3.1", "USB4"],
        "default": None,
        "why": "USB version determines impedance targets (90 ohm diff for USB3+) and routing rules.",
    },
    {
        "id": "target_impedance_se",
        "category": "stackup",
        "text": "Single-ended impedance target (ohms)?",
        "type": "number",
        "default": 50,
        "why": "Single-ended impedance target is needed to validate stackup and trace geometry.",
    },
    {
        "id": "target_impedance_diff",
        "category": "stackup",
        "text": "Differential impedance target (ohms)?",
        "type": "number",
        "default": 100,
        "why": "Differential impedance target is needed for USB, PCIe, DDR strobe, and Ethernet pair validation.",
    },
    {
        "id": "max_current_estimates",
        "category": "power",
        "text": (
            "Review/override current estimates for power rails "
            "(JSON or free text, e.g. 'VCC_3V3: 2A, VDD_CORE: 1.5A')."
        ),
        "type": "text",
        "default": "",
        "why": "Accurate current estimates are needed for trace width validation and thermal analysis.",
    },
    {
        "id": "rf_operating_freq",
        "category": "rf",
        "text": "RF operating frequencies in MHz (comma-separated, e.g. '2400, 5800')?",
        "type": "text",
        "default": "",
        "why": "RF frequencies determine wavelength-based keep-out zones, via spacing, and filter requirements.",
    },
    {
        "id": "battery_capacity_mah",
        "category": "power",
        "text": "Battery capacity in mAh (if battery-powered)?",
        "type": "number",
        "default": None,
        "why": "Battery capacity is needed for power budget and battery-life estimation.",
    },
    {
        "id": "operating_environment",
        "category": "interfaces",
        "text": "What is the target operating environment?",
        "type": "choice",
        "choices": ["consumer", "industrial", "automotive", "medical", "military"],
        "default": "consumer",
        "why": "Operating environment determines temperature range, EMC standard selection, and derating rules.",
    },
    {
        "id": "fab_stackup_spec",
        "category": "stackup",
        "text": "Do you have the fab stackup specification?",
        "type": "choice",
        "choices": ["yes_upload", "no_use_extracted"],
        "default": "no_use_extracted",
        "why": "A fab stackup spec provides accurate dielectric thicknesses for impedance calculations.",
    },
]

# Quick lookup by ID
_QUESTIONS_BY_ID: dict[str, dict[str, Any]] = {q["id"]: q for q in REVIEW_QUESTIONS}


# =============================================================================
# Condition functions — determine when each question is applicable
# =============================================================================

def _has_ddr(design: PCBDesignData, classification: DesignClassificationResult,
             net_cls: NetClassificationResult) -> bool:
    """True when DDR nets are detected."""
    return any(nc.category == "ddr" for nc in net_cls.classified_nets)


def _has_emmc(design: PCBDesignData, classification: DesignClassificationResult,
              net_cls: NetClassificationResult) -> bool:
    """True when eMMC nets are detected."""
    return any(nc.category == "emmc" for nc in net_cls.classified_nets)


def _has_usb(design: PCBDesignData, classification: DesignClassificationResult,
             net_cls: NetClassificationResult) -> bool:
    """True when USB nets are detected."""
    return any(nc.category == "usb" for nc in net_cls.classified_nets)


def _has_diff_pairs(design: PCBDesignData, classification: DesignClassificationResult,
                    net_cls: NetClassificationResult) -> bool:
    """True when differential pairs are detected."""
    return len(net_cls.differential_pairs) > 0


def _has_power(design: PCBDesignData, classification: DesignClassificationResult,
               net_cls: NetClassificationResult) -> bool:
    """True when power nets are detected."""
    return any(nc.category == "power" for nc in net_cls.classified_nets)


def _has_rf(design: PCBDesignData, classification: DesignClassificationResult,
            net_cls: NetClassificationResult) -> bool:
    """True when RF nets are detected."""
    return any(nc.category == "rf" for nc in net_cls.classified_nets)


def _always(design: PCBDesignData, classification: DesignClassificationResult,
            net_cls: NetClassificationResult) -> bool:
    """Always applicable."""
    return True


# Map question IDs to their condition functions
_CONDITIONS: dict[str, Any] = {
    "ddr_standard": _has_ddr,
    "emmc_speed_mode": _has_emmc,
    "usb_version": _has_usb,
    "target_impedance_se": _always,
    "target_impedance_diff": _has_diff_pairs,
    "max_current_estimates": _has_power,
    "rf_operating_freq": _has_rf,
    "battery_capacity_mah": _has_power,
    "operating_environment": _always,
    "fab_stackup_spec": _always,
}


# =============================================================================
# Public API
# =============================================================================

def get_review_questions(
    design: PCBDesignData,
    classification: DesignClassificationResult,
    net_cls: NetClassificationResult,
) -> list[dict[str, Any]]:
    """Return the list of applicable review questions for this design.

    Only questions whose condition is met are returned.  Each question dict
    is a copy of the definition (safe to serialise to JSON).
    """
    applicable: list[dict[str, Any]] = []
    for q in REVIEW_QUESTIONS:
        cond = _CONDITIONS.get(q["id"], _always)
        try:
            if cond(design, classification, net_cls):
                # Return a serialisable copy (no callables)
                applicable.append({
                    "id": q["id"],
                    "category": q["category"],
                    "text": q["text"],
                    "type": q["type"],
                    "choices": q.get("choices"),
                    "default": q.get("default"),
                    "why": q["why"],
                })
        except Exception:
            logger.debug("Condition check failed for question %s", q["id"], exc_info=True)
    return applicable


class ReviewContext:
    """Stores user-provided answers and provides typed getters.

    Parameters
    ----------
    answers : dict
        A ``{question_id: value}`` mapping, typically from the user via the
        ``pcb_answer_review_questions`` MCP tool.
    """

    def __init__(self, answers: Optional[dict[str, Any]] = None) -> None:
        self._answers: dict[str, Any] = dict(answers) if answers else {}

    # -- raw access -----------------------------------------------------------

    def has(self, question_id: str) -> bool:
        """Return True if the user provided an answer for *question_id*."""
        return question_id in self._answers

    def get_raw(self, question_id: str, default: Any = None) -> Any:
        """Return the raw answer value, or *default*."""
        return self._answers.get(question_id, default)

    @property
    def answers(self) -> dict[str, Any]:
        """Return the full answers dict (read-only copy)."""
        return dict(self._answers)

    # -- typed getters --------------------------------------------------------

    def get_ddr_standard(self) -> Optional[str]:
        """Return DDR standard (e.g. 'DDR4') or None if not specified."""
        val = self._answers.get("ddr_standard")
        if val and isinstance(val, str):
            return val
        return None

    def get_emmc_mode(self) -> str:
        """Return eMMC speed mode, defaulting to 'HS200'."""
        val = self._answers.get("emmc_speed_mode")
        if val and isinstance(val, str):
            return val
        return "HS200"

    def get_usb_version(self) -> Optional[str]:
        """Return USB version (e.g. 'USB3.1') or None if not specified."""
        val = self._answers.get("usb_version")
        if val and isinstance(val, str):
            return val
        return None

    def get_impedance_target(self, kind: str = "single_ended") -> float:
        """Return impedance target in ohms.

        Parameters
        ----------
        kind : str
            ``'single_ended'`` (default) or ``'differential'``.
        """
        if kind == "differential":
            val = self._answers.get("target_impedance_diff")
            default = 100.0
        else:
            val = self._answers.get("target_impedance_se")
            default = 50.0
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def get_current_estimate(self, rail_name: str) -> Optional[float]:
        """Parse current estimate for a specific power rail.

        The ``max_current_estimates`` answer can be free text like
        ``'VCC_3V3: 2A, VDD_CORE: 1.5A'``.  This attempts a best-effort
        parse; returns ``None`` if the rail is not found.
        """
        raw = self._answers.get("max_current_estimates", "")
        if not raw or not isinstance(raw, str):
            return None
        import re
        # Try "RAIL_NAME: <number>A" or "RAIL_NAME: <number>"
        pattern = re.compile(
            re.escape(rail_name) + r'\s*[:=]\s*([\d.]+)\s*[Aa]?',
            re.IGNORECASE,
        )
        m = pattern.search(raw)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None

    def get_rf_frequencies_mhz(self) -> list[float]:
        """Return RF operating frequencies as a list of floats (MHz)."""
        raw = self._answers.get("rf_operating_freq", "")
        if not raw or not isinstance(raw, str):
            return []
        import re
        parts = re.split(r'[,;\s]+', raw.strip())
        freqs: list[float] = []
        for p in parts:
            try:
                freqs.append(float(p))
            except ValueError:
                continue
        return freqs

    def get_battery_capacity_mah(self) -> Optional[float]:
        """Return battery capacity in mAh, or None."""
        val = self._answers.get("battery_capacity_mah")
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def get_operating_environment(self) -> str:
        """Return operating environment, defaulting to 'consumer'."""
        val = self._answers.get("operating_environment")
        if val and isinstance(val, str):
            return val
        return "consumer"

    def get_fab_stackup_choice(self) -> str:
        """Return fab stackup choice: 'yes_upload' or 'no_use_extracted'."""
        val = self._answers.get("fab_stackup_spec")
        if val and isinstance(val, str):
            return val
        return "no_use_extracted"
