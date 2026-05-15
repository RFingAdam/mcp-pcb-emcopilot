"""Review context — identifies missing information and stores user answers.

When the MCP tool runs a design review and encounters ambiguity or missing
information, this module determines what questions need answering and provides
typed access to the user-supplied answers.

Phase 4 extension: multi-market intake. The 10-question CORE pack below stays
the canonical legacy list, but ``get_review_questions`` now also merges the
per-market packs from :mod:`market_packs` based on either the explicit
``markets`` answer or the playbook's ``declared_market``. Typed getters for
the new market-specific answers (vehicle_class, iso7637_pulses, fcc_part,
iec60601_edition, device_class) are exposed alongside the legacy ones.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import market_packs
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

def get_active_markets(
    design: PCBDesignData,
    classification: Optional[DesignClassificationResult] = None,
    net_cls: Optional[NetClassificationResult] = None,
) -> list[str]:
    """Return the list of markets that apply to this session.

    Sources, in order of authority:
    1. Explicit ``markets`` list on ``review_context`` (Phase 4 — set via
       ``pcb_set_market``).
    2. The playbook's ``declared_market`` (from Phase 2 ``pcb_start_professional_review``).
    3. Heuristic auto-inference: RF nets → ``wireless``, automotive bus tags →
       ``automotive`` (deferred to net_cls when available).
    """
    ctx = design.review_context or {}
    explicit: list[str] = []
    if isinstance(ctx.get("markets"), list):
        for m in ctx["markets"]:
            m_l = str(m).strip().lower()
            if m_l and m_l in market_packs.KNOWN_MARKETS and m_l not in explicit:
                explicit.append(m_l)
    if explicit:
        return explicit

    pb = ctx.get("playbook") or {}
    declared = str(pb.get("declared_market") or "").strip().lower()
    if declared and declared != "unknown" and declared in market_packs.KNOWN_MARKETS:
        return [declared]

    # Auto-inference fallback.
    inferred: list[str] = []
    if net_cls is not None:
        has_rf = any(nc.category == "rf" for nc in net_cls.classified_nets)
        if has_rf:
            inferred.append("wireless")
    return inferred


def get_review_questions(
    design: PCBDesignData,
    classification: DesignClassificationResult,
    net_cls: NetClassificationResult,
) -> list[dict[str, Any]]:
    """Return the list of applicable review questions for this design.

    Merges:
    1. The CORE legacy pack (``REVIEW_QUESTIONS``) — filtered by per-question
       conditional predicates against the parsed design.
    2. Per-market packs from :mod:`market_packs` for every market in
       :func:`get_active_markets`.

    Deduplicates by question id (CORE wins on collision). Strips callables
    and other server-side metadata so the result is JSON-safe.
    """
    applicable: list[dict[str, Any]] = []
    seen: set[str] = set()

    # CORE pack (legacy) — gated by per-question conditional predicates.
    for q in REVIEW_QUESTIONS:
        cond = _CONDITIONS.get(q["id"], _always)
        try:
            if cond(design, classification, net_cls):
                applicable.append({
                    "id": q["id"],
                    "category": q["category"],
                    "text": q["text"],
                    "type": q["type"],
                    "choices": q.get("choices"),
                    "default": q.get("default"),
                    "why": q["why"],
                })
                seen.add(q["id"])
        except Exception:
            logger.debug("Condition check failed for question %s", q["id"], exc_info=True)

    # Per-market packs.
    for market in get_active_markets(design, classification, net_cls):
        for q in market_packs.get_pack(market):
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            applicable.append({
                "id": q["id"],
                "category": q.get("category", market),
                "text": q["text"],
                "type": q["type"],
                "choices": q.get("choices"),
                "default": q.get("default"),
                "why": q.get("why", ""),
            })

    return applicable


def get_target_standards_for(
    design: PCBDesignData,
    classification: Optional[DesignClassificationResult] = None,
    net_cls: Optional[NetClassificationResult] = None,
) -> list[str]:
    """Return the union of standards activated by all active markets."""
    return market_packs.merge_standards(get_active_markets(design, classification, net_cls))


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
        try:
            return float(val)  # type: ignore[arg-type]
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

    # -- Phase 4 market-specific typed getters -------------------------------

    def get_vehicle_class(self) -> Optional[str]:
        """Automotive ``vehicle_class`` answer (passenger / commercial / ...)."""
        val = self._answers.get("vehicle_class")
        return val if isinstance(val, str) and val else None

    def get_bus_voltage(self) -> Optional[str]:
        """Automotive bus voltage answer (12V / 24V / 48V / HV-traction)."""
        val = self._answers.get("bus_voltage")
        return val if isinstance(val, str) and val else None

    def get_iso26262_asil(self) -> Optional[str]:
        """Automotive ASIL level (QM / A / B / C / D) or None."""
        val = self._answers.get("iso26262_asil")
        return val if isinstance(val, str) and val else None

    def get_cispr25_class(self) -> Optional[int]:
        """Automotive CISPR-25 target class as int (1-5) or None."""
        val = self._answers.get("cispr25_class")
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_iso7637_pulses(self) -> list[str]:
        """Automotive ISO 7637-2 pulse set the design must survive."""
        val = self._answers.get("iso7637_pulses")
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str) and val:
            import re
            return [tok for tok in re.split(r"[,;\s]+", val.strip()) if tok]
        return []

    def get_oem_spec(self) -> str:
        """Automotive OEM-specific spec or 'none'."""
        val = self._answers.get("oem_spec")
        return val if isinstance(val, str) and val else "none"

    def get_device_class(self) -> Optional[str]:
        """Medical device class (I / IIa / IIb / III)."""
        val = self._answers.get("device_class")
        return val if isinstance(val, str) and val else None

    def get_iec60601_edition(self) -> str:
        """Medical IEC 60601-1-2 edition target (defaults to 4.1)."""
        val = self._answers.get("iec60601_edition")
        if isinstance(val, str) and val:
            return val
        return "4.1"

    def get_patient_contact(self) -> Optional[str]:
        """Medical patient-contact type or None."""
        val = self._answers.get("patient_contact")
        return val if isinstance(val, str) and val else None

    def get_fcc_part(self) -> Optional[str]:
        """Wireless FCC Part (15B / 15C / 95 / etc.) or None."""
        val = self._answers.get("fcc_part")
        return val if isinstance(val, str) and val else None

    def get_tx_power_dbm(self) -> Optional[float]:
        """Wireless conducted TX power in dBm or None."""
        val = self._answers.get("tx_power_dbm")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_antenna_gain_dbi(self) -> Optional[float]:
        """Wireless antenna gain in dBi or None."""
        val = self._answers.get("antenna_gain_dbi")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_intentional_radiator(self) -> bool:
        """Wireless intentional-radiator flag (defaults to False)."""
        val = self._answers.get("intentional_radiator")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "yes", "1")
        return False

    def get_target_regions(self) -> list[str]:
        """Commercial target regions (multi-select)."""
        val = self._answers.get("target_regions")
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str) and val:
            import re
            return [tok for tok in re.split(r"[,;\s]+", val.strip()) if tok]
        return []

    def get_cispr32_class(self) -> Optional[str]:
        """Commercial CISPR 32 class (A / B) or None."""
        val = self._answers.get("cispr32_class")
        return val if isinstance(val, str) and val else None

    def get_iec61000_4_immunity_level(self) -> Optional[int]:
        """Commercial / industrial IEC 61000-4 immunity level (1-4) or None."""
        val = self._answers.get("iec61000_4_immunity_level")
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_hazloc_class(self) -> Optional[str]:
        """Industrial hazardous-location class or None."""
        val = self._answers.get("hazloc_class")
        if isinstance(val, str) and val and val.lower() != "none":
            return val
        return None

    def get_surge_target_kV(self) -> Optional[float]:  # noqa: N802 — match kV spelling
        """Industrial IEC 61000-4-5 surge target in kV or None."""
        val = self._answers.get("surge_target_kV") or self._answers.get("surge_target_kv")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None
