"""Tolerance stack-up analyzer for DFM"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import math


@dataclass
class ToleranceResult:
    """Results from tolerance analysis"""
    # Analysis identification
    analysis_id: str
    feature_name: str

    # Nominal values
    nominal_value_mm: float
    nominal_min_mm: float
    nominal_max_mm: float

    # Worst case analysis
    worst_case_min_mm: float
    worst_case_max_mm: float
    worst_case_variation_mm: float

    # RSS (Root Sum Square) analysis
    rss_min_mm: float
    rss_max_mm: float
    rss_variation_mm: float

    # Monte Carlo (if performed)
    monte_carlo_mean_mm: Optional[float] = None
    monte_carlo_std_mm: Optional[float] = None
    monte_carlo_cpk: Optional[float] = None

    # Assessment
    within_spec: bool = True
    margin_mm: float = 0
    dfm_score: float = 100

    # Contributors
    contributors: List[Dict[str, Any]] = field(default_factory=list)

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ToleranceContributor:
    """Single contributor to tolerance stack"""
    name: str
    nominal_mm: float
    tolerance_plus_mm: float
    tolerance_minus_mm: float
    distribution: str = "normal"  # normal, uniform, triangular
    sensitivity: float = 1.0  # How much this affects the result (+1 or -1 typically)


class ToleranceAnalyzer:
    """
    Tolerance stack-up analyzer for DFM.

    Analyzes:
    - PCB manufacturing tolerances
    - Component placement tolerances
    - Assembly stack-ups

    Supports:
    - Worst case analysis
    - RSS (Root Sum Square) statistical analysis
    - Monte Carlo simulation
    """

    # Standard PCB manufacturing tolerances (mm)
    PCB_TOLERANCES = {
        "board_thickness_standard": 0.1,      # ±0.1mm on 1.6mm
        "board_thickness_controlled": 0.05,   # ±0.05mm controlled
        "trace_width_standard": 0.025,        # ±25um
        "trace_width_fine": 0.015,            # ±15um
        "drill_position": 0.05,               # ±50um
        "drill_diameter": 0.025,              # ±25um
        "layer_registration": 0.075,          # ±75um
        "solder_mask_registration": 0.075,    # ±75um
        "copper_thickness": 0.007,            # ±7um (1oz)
        "prepreg_thickness": 0.015,           # ±15um
        "core_thickness": 0.025,              # ±25um
    }

    # Component placement tolerances (mm)
    PLACEMENT_TOLERANCES = {
        "pick_and_place_standard": 0.05,      # ±50um
        "pick_and_place_fine": 0.025,         # ±25um
        "manual_placement": 0.25,             # ±250um
        "component_position_chip": 0.05,      # Component internal tolerance
        "component_position_qfp": 0.1,
        "component_position_bga": 0.05,
    }

    def __init__(self):
        pass

    def analyze_stack(
        self,
        contributors: List[ToleranceContributor],
        specification_mm: Tuple[float, float],
        analysis_id: str = "T1",
        feature_name: str = "Feature",
        run_monte_carlo: bool = False,
        monte_carlo_iterations: int = 10000,
    ) -> ToleranceResult:
        """
        Analyze tolerance stack-up.

        Args:
            contributors: List of tolerance contributors
            specification_mm: (min_allowed, max_allowed)
            analysis_id: Analysis identifier
            feature_name: Name of the feature being analyzed
            run_monte_carlo: Whether to run Monte Carlo
            monte_carlo_iterations: Number of iterations

        Returns:
            ToleranceResult with complete analysis
        """
        spec_min, spec_max = specification_mm

        # Calculate nominal
        nominal = sum(c.nominal_mm * c.sensitivity for c in contributors)

        # Worst case analysis
        wc_plus = sum(
            c.tolerance_plus_mm * abs(c.sensitivity) if c.sensitivity > 0
            else c.tolerance_minus_mm * abs(c.sensitivity)
            for c in contributors
        )
        wc_minus = sum(
            c.tolerance_minus_mm * abs(c.sensitivity) if c.sensitivity > 0
            else c.tolerance_plus_mm * abs(c.sensitivity)
            for c in contributors
        )
        wc_max = nominal + wc_plus
        wc_min = nominal - wc_minus

        # RSS analysis
        rss_plus = math.sqrt(sum(
            (c.tolerance_plus_mm * abs(c.sensitivity))**2
            for c in contributors
        ))
        rss_minus = math.sqrt(sum(
            (c.tolerance_minus_mm * abs(c.sensitivity))**2
            for c in contributors
        ))
        rss_max = nominal + rss_plus
        rss_min = nominal - rss_minus

        # Contributor analysis
        contributor_details = []
        for c in contributors:
            contribution_wc = max(c.tolerance_plus_mm, c.tolerance_minus_mm) * abs(c.sensitivity)
            total_wc = (wc_plus + wc_minus) / 2
            percent_contribution = (contribution_wc / total_wc * 100) if total_wc > 0 else 0

            contributor_details.append({
                "name": c.name,
                "nominal_mm": c.nominal_mm,
                "tolerance_plus_mm": c.tolerance_plus_mm,
                "tolerance_minus_mm": c.tolerance_minus_mm,
                "sensitivity": c.sensitivity,
                "contribution_mm": round(contribution_wc, 4),
                "contribution_percent": round(percent_contribution, 1),
            })

        # Sort by contribution
        contributor_details.sort(key=lambda x: x["contribution_percent"], reverse=True)

        # Monte Carlo if requested
        mc_mean = None
        mc_std = None
        mc_cpk = None

        if run_monte_carlo:
            mc_results = self._monte_carlo(contributors, monte_carlo_iterations)
            mc_mean = mc_results["mean"]
            mc_std = mc_results["std"]

            # Calculate Cpk
            if mc_std > 0:
                cpu = (spec_max - mc_mean) / (3 * mc_std)
                cpl = (mc_mean - spec_min) / (3 * mc_std)
                mc_cpk = min(cpu, cpl)

        # Check against specification
        within_spec = wc_min >= spec_min and wc_max <= spec_max
        margin = min(wc_min - spec_min, spec_max - wc_max)

        # DFM score
        if within_spec:
            if margin > 0.1:
                score = 95
            elif margin > 0.05:
                score = 85
            elif margin > 0:
                score = 75
            else:
                score = 65
        else:
            # Out of spec
            overshoot = max(spec_min - wc_min, wc_max - spec_max)
            score = max(0, 50 - overshoot * 100)

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if not within_spec:
            issues.append(f"Stack-up exceeds specification by {abs(margin):.3f}mm")

            # Find largest contributors
            top_contributors = contributor_details[:3]
            for tc in top_contributors:
                if tc["contribution_percent"] > 20:
                    recommendations.append(
                        f"Reduce tolerance on {tc['name']} ({tc['contribution_percent']:.0f}% contribution)"
                    )

        if mc_cpk is not None and mc_cpk < 1.33:
            issues.append(f"Process capability Cpk={mc_cpk:.2f} below 1.33")
            recommendations.append("Tighten tolerances or improve process capability")

        if margin < 0.05 and within_spec:
            issues.append(f"Marginal stack-up with only {margin:.3f}mm margin")
            recommendations.append("Consider tightening key tolerances")

        return ToleranceResult(
            analysis_id=analysis_id,
            feature_name=feature_name,
            nominal_value_mm=round(nominal, 4),
            nominal_min_mm=round(nominal - spec_min, 4),
            nominal_max_mm=round(spec_max - nominal, 4),
            worst_case_min_mm=round(wc_min, 4),
            worst_case_max_mm=round(wc_max, 4),
            worst_case_variation_mm=round(wc_max - wc_min, 4),
            rss_min_mm=round(rss_min, 4),
            rss_max_mm=round(rss_max, 4),
            rss_variation_mm=round(rss_max - rss_min, 4),
            monte_carlo_mean_mm=round(mc_mean, 4) if mc_mean else None,
            monte_carlo_std_mm=round(mc_std, 4) if mc_std else None,
            monte_carlo_cpk=round(mc_cpk, 2) if mc_cpk else None,
            within_spec=within_spec,
            margin_mm=round(margin, 4),
            dfm_score=round(score, 1),
            contributors=contributor_details,
            issues=issues,
            recommendations=recommendations,
        )

    def _monte_carlo(
        self,
        contributors: List[ToleranceContributor],
        iterations: int,
    ) -> Dict[str, float]:
        """Run Monte Carlo simulation."""
        import random

        results = []

        for _ in range(iterations):
            total = 0
            for c in contributors:
                # Generate random value based on distribution
                if c.distribution == "normal":
                    # Use tolerance as 3-sigma
                    sigma = (c.tolerance_plus_mm + c.tolerance_minus_mm) / 6
                    value = random.gauss(c.nominal_mm, sigma)
                elif c.distribution == "uniform":
                    value = random.uniform(
                        c.nominal_mm - c.tolerance_minus_mm,
                        c.nominal_mm + c.tolerance_plus_mm,
                    )
                else:  # triangular
                    value = random.triangular(
                        c.nominal_mm - c.tolerance_minus_mm,
                        c.nominal_mm + c.tolerance_plus_mm,
                        c.nominal_mm,
                    )

                total += value * c.sensitivity

            results.append(total)

        mean = sum(results) / len(results)
        variance = sum((x - mean)**2 for x in results) / len(results)
        std = math.sqrt(variance)

        return {
            "mean": mean,
            "std": std,
            "min": min(results),
            "max": max(results),
        }

    def analyze_pcb_stackup(
        self,
        layer_count: int,
        target_thickness_mm: float = 1.6,
        controlled_impedance: bool = False,
    ) -> ToleranceResult:
        """
        Analyze PCB stackup tolerance.

        Args:
            layer_count: Number of copper layers
            target_thickness_mm: Target board thickness
            controlled_impedance: Whether controlled impedance is required

        Returns:
            ToleranceResult for stackup
        """
        contributors = []

        # Calculate typical stackup
        if layer_count == 2:
            # 2-layer: core only
            contributors.append(ToleranceContributor(
                name="Core",
                nominal_mm=target_thickness_mm - 0.07,  # Account for copper
                tolerance_plus_mm=self.PCB_TOLERANCES["core_thickness"],
                tolerance_minus_mm=self.PCB_TOLERANCES["core_thickness"],
                sensitivity=1.0,
            ))
            contributors.append(ToleranceContributor(
                name="Top copper",
                nominal_mm=0.035,
                tolerance_plus_mm=self.PCB_TOLERANCES["copper_thickness"],
                tolerance_minus_mm=self.PCB_TOLERANCES["copper_thickness"],
                sensitivity=1.0,
            ))
            contributors.append(ToleranceContributor(
                name="Bottom copper",
                nominal_mm=0.035,
                tolerance_plus_mm=self.PCB_TOLERANCES["copper_thickness"],
                tolerance_minus_mm=self.PCB_TOLERANCES["copper_thickness"],
                sensitivity=1.0,
            ))
        else:
            # Multi-layer: cores and prepregs
            num_cores = layer_count // 2
            num_prepregs = (layer_count - 2) // 2 + 1

            core_thickness = (target_thickness_mm * 0.6) / num_cores
            prepreg_thickness = (target_thickness_mm * 0.4 - 0.035 * layer_count) / num_prepregs

            for i in range(num_cores):
                contributors.append(ToleranceContributor(
                    name=f"Core {i+1}",
                    nominal_mm=core_thickness,
                    tolerance_plus_mm=self.PCB_TOLERANCES["core_thickness"],
                    tolerance_minus_mm=self.PCB_TOLERANCES["core_thickness"],
                    sensitivity=1.0,
                ))

            for i in range(num_prepregs):
                contributors.append(ToleranceContributor(
                    name=f"Prepreg {i+1}",
                    nominal_mm=prepreg_thickness,
                    tolerance_plus_mm=self.PCB_TOLERANCES["prepreg_thickness"],
                    tolerance_minus_mm=self.PCB_TOLERANCES["prepreg_thickness"],
                    sensitivity=1.0,
                ))

            for i in range(layer_count):
                contributors.append(ToleranceContributor(
                    name=f"Copper L{i+1}",
                    nominal_mm=0.035,
                    tolerance_plus_mm=self.PCB_TOLERANCES["copper_thickness"],
                    tolerance_minus_mm=self.PCB_TOLERANCES["copper_thickness"],
                    sensitivity=1.0,
                ))

        # Specification
        if controlled_impedance:
            spec_tolerance = self.PCB_TOLERANCES["board_thickness_controlled"]
        else:
            spec_tolerance = self.PCB_TOLERANCES["board_thickness_standard"]

        return self.analyze_stack(
            contributors,
            (target_thickness_mm - spec_tolerance, target_thickness_mm + spec_tolerance),
            analysis_id="STACKUP",
            feature_name=f"{layer_count}L PCB Stackup",
            run_monte_carlo=True,
        )

    def analyze_component_fitment(
        self,
        pad_width_mm: float,
        component_lead_width_mm: float,
        placement_process: str = "pick_and_place_standard",
    ) -> ToleranceResult:
        """
        Analyze component to pad alignment tolerance.

        Args:
            pad_width_mm: PCB pad width
            component_lead_width_mm: Component lead/ball width
            placement_process: Placement method

        Returns:
            ToleranceResult for alignment
        """
        placement_tol = self.PLACEMENT_TOLERANCES.get(placement_process, 0.05)

        contributors = [
            ToleranceContributor(
                name="Pad position",
                nominal_mm=0,
                tolerance_plus_mm=self.PCB_TOLERANCES["layer_registration"],
                tolerance_minus_mm=self.PCB_TOLERANCES["layer_registration"],
                sensitivity=1.0,
            ),
            ToleranceContributor(
                name="Pad width",
                nominal_mm=pad_width_mm,
                tolerance_plus_mm=self.PCB_TOLERANCES["trace_width_standard"],
                tolerance_minus_mm=self.PCB_TOLERANCES["trace_width_standard"],
                sensitivity=1.0,
            ),
            ToleranceContributor(
                name="Component placement",
                nominal_mm=0,
                tolerance_plus_mm=placement_tol,
                tolerance_minus_mm=placement_tol,
                sensitivity=1.0,
            ),
            ToleranceContributor(
                name="Component lead position",
                nominal_mm=0,
                tolerance_plus_mm=self.PLACEMENT_TOLERANCES["component_position_chip"],
                tolerance_minus_mm=self.PLACEMENT_TOLERANCES["component_position_chip"],
                sensitivity=-1.0,
            ),
        ]

        # Minimum overlap needed
        min_overlap = 0.1  # At least 0.1mm overlap on each side

        # Calculate specification
        total_overlap = (pad_width_mm - component_lead_width_mm) / 2
        spec_min = min_overlap
        spec_max = total_overlap + min_overlap

        return self.analyze_stack(
            contributors,
            (spec_min, spec_max),
            analysis_id="FITMENT",
            feature_name="Component Alignment",
            run_monte_carlo=True,
        )

    def get_manufacturing_tolerances(
        self,
        pcb_class: str = "standard",
    ) -> Dict[str, float]:
        """
        Get manufacturing tolerances for a PCB class.

        Args:
            pcb_class: PCB class (standard, fine, advanced)

        Returns:
            Dictionary of tolerances
        """
        multipliers = {
            "standard": 1.0,
            "fine": 0.7,
            "advanced": 0.5,
        }

        mult = multipliers.get(pcb_class, 1.0)

        return {
            key: value * mult
            for key, value in self.PCB_TOLERANCES.items()
        }
