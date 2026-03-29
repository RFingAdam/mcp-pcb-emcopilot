"""Bridge to mcp-openems for full-wave validation of analytical results."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..analyzers.rf_si.rf_simulation_extractor import SimulationCandidate


@dataclass
class OpenEMSModel:
    """Model definition for OpenEMS simulation."""
    model_type: str  # "microstrip", "stripline", "via", "trace_antenna"
    description: str
    geometry: dict
    frequency_range_hz: tuple[float, float]
    mesh_resolution: int = 20  # cells per wavelength
    excitation: str = "gaussian"
    boundary_conditions: list[str] = field(default_factory=lambda: ["PML"] * 6)
    script: str = ""


@dataclass
class ValidationResult:
    """Comparison between analytical and simulated results."""
    parameter: str
    analytical_value: float
    analytical_unit: str
    simulated_value: Optional[float] = None
    simulated_unit: Optional[str] = None
    difference_percent: Optional[float] = None
    status: str = "pending"  # "pending", "pass", "warning", "fail"
    notes: str = ""


class OpenEMSBridge:
    """Bridge between PCB EMCopilot analysis and OpenEMS simulation."""

    def generate_microstrip_model(
        self,
        trace_width_mm: float,
        dielectric_height_mm: float,
        trace_thickness_mm: float = 0.035,
        er: float = 4.3,
        frequency_ghz: float = 1.0,
        trace_length_mm: float = 50.0,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for microstrip impedance validation."""
        freq_hz = frequency_ghz * 1e9
        # Wavelength in dielectric
        c0 = 299792458.0
        wavelength_mm = (c0 / freq_hz / math.sqrt(er)) * 1000

        # Simulation domain - extend beyond trace
        margin_mm = max(5.0, dielectric_height_mm * 10)

        geometry = {
            "trace_width_mm": trace_width_mm,
            "trace_length_mm": trace_length_mm,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "dielectric_er": er,
            "substrate_width_mm": trace_length_mm + 2 * margin_mm,
            "substrate_depth_mm": trace_width_mm * 20,
            "air_height_mm": dielectric_height_mm * 10,
            "wavelength_mm": wavelength_mm,
        }

        model = OpenEMSModel(
            model_type="microstrip",
            description=f"Microstrip: w={trace_width_mm}mm, h={dielectric_height_mm}mm, er={er}, f={frequency_ghz}GHz",
            geometry=geometry,
            frequency_range_hz=(0, freq_hz * 2),
            mesh_resolution=20,
        )
        model.script = self._generate_microstrip_script(geometry, freq_hz)
        return model

    def generate_stripline_model(
        self,
        trace_width_mm: float,
        dielectric_height_mm: float,
        trace_thickness_mm: float = 0.035,
        er: float = 4.3,
        frequency_ghz: float = 1.0,
        trace_length_mm: float = 50.0,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for stripline impedance validation."""
        freq_hz = frequency_ghz * 1e9
        c0 = 299792458.0
        wavelength_mm = (c0 / freq_hz / math.sqrt(er)) * 1000

        geometry = {
            "trace_width_mm": trace_width_mm,
            "trace_length_mm": trace_length_mm,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "total_height_mm": dielectric_height_mm * 2 + trace_thickness_mm,
            "dielectric_er": er,
            "substrate_width_mm": trace_length_mm + 20,
            "substrate_depth_mm": trace_width_mm * 20,
            "wavelength_mm": wavelength_mm,
        }

        model = OpenEMSModel(
            model_type="stripline",
            description=f"Stripline: w={trace_width_mm}mm, h={dielectric_height_mm}mm, er={er}",
            geometry=geometry,
            frequency_range_hz=(0, freq_hz * 2),
        )
        model.script = self._generate_stripline_script(geometry, freq_hz)
        return model

    def generate_via_model(
        self,
        drill_diameter_mm: float,
        pad_diameter_mm: float,
        board_thickness_mm: float,
        antipad_diameter_mm: float = 0.0,
        er: float = 4.3,
        frequency_ghz: float = 5.0,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for via impedance discontinuity."""
        if antipad_diameter_mm <= 0:
            antipad_diameter_mm = pad_diameter_mm * 2

        freq_hz = frequency_ghz * 1e9

        geometry = {
            "drill_diameter_mm": drill_diameter_mm,
            "pad_diameter_mm": pad_diameter_mm,
            "antipad_diameter_mm": antipad_diameter_mm,
            "board_thickness_mm": board_thickness_mm,
            "dielectric_er": er,
        }

        model = OpenEMSModel(
            model_type="via",
            description=f"Via: drill={drill_diameter_mm}mm, pad={pad_diameter_mm}mm, h={board_thickness_mm}mm",
            geometry=geometry,
            frequency_range_hz=(0, freq_hz * 2),
            mesh_resolution=30,
        )
        model.script = self._generate_via_script(geometry, freq_hz)
        return model

    def generate_trace_antenna_model(
        self,
        trace_length_mm: float,
        trace_width_mm: float,
        height_above_ground_mm: float,
        er: float = 4.3,
        frequency_ghz: float = 1.0,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for unintentional trace radiation."""
        freq_hz = frequency_ghz * 1e9

        geometry = {
            "trace_length_mm": trace_length_mm,
            "trace_width_mm": trace_width_mm,
            "height_above_ground_mm": height_above_ground_mm,
            "dielectric_er": er,
        }

        model = OpenEMSModel(
            model_type="trace_antenna",
            description=f"Trace antenna: L={trace_length_mm}mm, w={trace_width_mm}mm, h={height_above_ground_mm}mm",
            geometry=geometry,
            frequency_range_hz=(freq_hz * 0.1, freq_hz * 3),
        )
        model.script = self._generate_trace_antenna_script(geometry, freq_hz)
        return model

    def compare_results(
        self,
        parameter: str,
        analytical_value: float,
        simulated_value: float,
        unit: str = "ohms",
        tolerance_percent: float = 5.0,
    ) -> ValidationResult:
        """Compare analytical vs simulated result."""
        if analytical_value == 0:
            diff = float('inf') if simulated_value != 0 else 0.0
        else:
            diff = abs(simulated_value - analytical_value) / abs(analytical_value) * 100

        if diff <= tolerance_percent:
            status = "pass"
        elif diff <= tolerance_percent * 2:
            status = "warning"
        else:
            status = "fail"

        return ValidationResult(
            parameter=parameter,
            analytical_value=analytical_value,
            analytical_unit=unit,
            simulated_value=simulated_value,
            simulated_unit=unit,
            difference_percent=round(diff, 2),
            status=status,
            notes=f"{'Within' if status == 'pass' else 'Exceeds'} {tolerance_percent}% tolerance",
        )

    def format_validation_report(self, results: list[ValidationResult]) -> dict:
        """Format validation results as structured report."""
        passed = sum(1 for r in results if r.status == "pass")
        warnings = sum(1 for r in results if r.status == "warning")
        failed = sum(1 for r in results if r.status == "fail")
        pending = sum(1 for r in results if r.status == "pending")

        return {
            "summary": {
                "total": len(results),
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
                "pending": pending,
                "overall_status": "fail" if failed > 0 else ("warning" if warnings > 0 else "pass"),
            },
            "results": [
                {
                    "parameter": r.parameter,
                    "analytical": f"{r.analytical_value} {r.analytical_unit}",
                    "simulated": f"{r.simulated_value} {r.simulated_unit}" if r.simulated_value is not None else "pending",
                    "difference_percent": r.difference_percent,
                    "status": r.status,
                    "notes": r.notes,
                }
                for r in results
            ],
        }

    def _generate_microstrip_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS Python script for microstrip simulation."""
        return f'''#!/usr/bin/env python3
"""OpenEMS microstrip impedance simulation.

Auto-generated by MCP PCB EMCopilot.
Trace: w={geom["trace_width_mm"]}mm, h={geom["dielectric_height_mm"]}mm, er={geom["dielectric_er"]}
"""
import os
import numpy as np

# Try importing openEMS — graceful fallback if not installed
try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0, EPS0, MUE0
except ImportError:
    raise ImportError(
        "openEMS not installed. Install via: "
        "conda install -c conda-forge openems"
    )

# --- Simulation Parameters ---
f_max = {freq_hz * 2:.1f}  # Hz
trace_w = {geom["trace_width_mm"]:.4f}  # mm
trace_l = {geom["trace_length_mm"]:.4f}  # mm
trace_t = {geom["trace_thickness_mm"]:.4f}  # mm
sub_h = {geom["dielectric_height_mm"]:.4f}  # mm
sub_er = {geom["dielectric_er"]:.2f}
sub_w = {geom["substrate_width_mm"]:.4f}  # mm
sub_d = {geom["substrate_depth_mm"]:.4f}  # mm
air_h = {geom["air_height_mm"]:.4f}  # mm

unit = 1e-3  # mm

# --- Setup FDTD ---
FDTD = openEMS(NrTS=50000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

# --- Materials ---
substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# --- Geometry ---
# Ground plane
copper.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, 0], priority=10)

# Substrate
margin_x = (sub_w - trace_l) / 2
substrate.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, sub_h], priority=1)

# Microstrip trace
trace_start_x = margin_x
trace_end_x = margin_x + trace_l
copper.AddBox(
    [trace_start_x, -trace_w/2, sub_h],
    [trace_end_x, trace_w/2, sub_h + trace_t],
    priority=10
)

# --- Ports ---
port1 = FDTD.AddLumpedPort(1, 50, [trace_start_x, -trace_w/2, 0],
                            [trace_start_x, trace_w/2, sub_h], "z", excite=1)
port2 = FDTD.AddLumpedPort(2, 50, [trace_end_x, -trace_w/2, 0],
                            [trace_end_x, trace_w/2, sub_h], "z")

# --- Mesh ---
mesh.AddLine("x", np.concatenate([
    np.array([0, sub_w]),
    np.linspace(trace_start_x, trace_end_x, 40),
]))
mesh.AddLine("y", np.concatenate([
    np.array([-sub_d/2, sub_d/2]),
    np.linspace(-trace_w, trace_w, 10),
]))
mesh.AddLine("z", np.concatenate([
    np.array([-air_h, sub_h + air_h]),
    np.linspace(0, sub_h + trace_t, 10),
]))
mesh.SmoothMeshLines("all", C0 / f_max / unit / 20)

# --- Run ---
sim_path = os.path.join(os.path.dirname(__file__), "microstrip_sim")
FDTD.Run(sim_path, cleanup=True)

# --- Post-process ---
freq = np.linspace(1e6, f_max, 1000)
port1.CalcPort(sim_path, freq)
port2.CalcPort(sim_path, freq)

s11 = port1.uf_ref / port1.uf_inc
s21 = port2.uf_ref / port1.uf_inc
Z0 = port1.uf_tot / port1.if_tot

print(f"Characteristic impedance at {{f_max/2/1e9:.2f}} GHz: {{np.real(Z0[len(Z0)//2]):.1f}} ohms")
print(f"S11 at {{f_max/2/1e9:.2f}} GHz: {{20*np.log10(np.abs(s11[len(s11)//2])):.1f}} dB")
print(f"S21 at {{f_max/2/1e9:.2f}} GHz: {{20*np.log10(np.abs(s21[len(s21)//2])):.1f}} dB")
'''

    def _generate_stripline_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS Python script for stripline simulation."""
        return f'''#!/usr/bin/env python3
"""OpenEMS stripline impedance simulation.

Auto-generated by MCP PCB EMCopilot.
Trace: w={geom["trace_width_mm"]}mm, h={geom["dielectric_height_mm"]}mm, er={geom["dielectric_er"]}
"""
import os
import numpy as np

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0
except ImportError:
    raise ImportError("openEMS not installed.")

f_max = {freq_hz * 2:.1f}
trace_w = {geom["trace_width_mm"]:.4f}
trace_l = {geom["trace_length_mm"]:.4f}
trace_t = {geom["trace_thickness_mm"]:.4f}
sub_h = {geom["dielectric_height_mm"]:.4f}
total_h = {geom["total_height_mm"]:.4f}
sub_er = {geom["dielectric_er"]:.2f}
sub_w = {geom["substrate_width_mm"]:.4f}
sub_d = {geom["substrate_depth_mm"]:.4f}

unit = 1e-3

FDTD = openEMS(NrTS=50000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# Bottom ground
copper.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, 0], priority=10)
# Top ground
copper.AddBox([0, -sub_d/2, total_h], [sub_w, sub_d/2, total_h], priority=10)
# Dielectric fill
substrate.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, total_h], priority=1)

# Stripline trace centered vertically
trace_z = sub_h
margin_x = (sub_w - trace_l) / 2
copper.AddBox(
    [margin_x, -trace_w/2, trace_z],
    [margin_x + trace_l, trace_w/2, trace_z + trace_t],
    priority=10
)

port1 = FDTD.AddLumpedPort(1, 50, [margin_x, -trace_w/2, 0],
                            [margin_x, trace_w/2, trace_z], "z", excite=1)
port2 = FDTD.AddLumpedPort(2, 50, [margin_x + trace_l, -trace_w/2, 0],
                            [margin_x + trace_l, trace_w/2, trace_z], "z")

mesh.SmoothMeshLines("all", C0 / f_max / unit / 20)

sim_path = os.path.join(os.path.dirname(__file__), "stripline_sim")
FDTD.Run(sim_path, cleanup=True)

freq = np.linspace(1e6, f_max, 1000)
port1.CalcPort(sim_path, freq)
port2.CalcPort(sim_path, freq)
Z0 = port1.uf_tot / port1.if_tot
print(f"Characteristic impedance: {{np.real(Z0[len(Z0)//2]):.1f}} ohms")
'''

    def _generate_via_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS Python script for via model."""
        return f'''#!/usr/bin/env python3
"""OpenEMS via impedance simulation.

Auto-generated by MCP PCB EMCopilot.
Via: drill={geom["drill_diameter_mm"]}mm, pad={geom["pad_diameter_mm"]}mm
"""
import os
import numpy as np

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0
except ImportError:
    raise ImportError("openEMS not installed.")

f_max = {freq_hz * 2:.1f}
drill_d = {geom["drill_diameter_mm"]:.4f}
pad_d = {geom["pad_diameter_mm"]:.4f}
antipad_d = {geom["antipad_diameter_mm"]:.4f}
board_h = {geom["board_thickness_mm"]:.4f}
sub_er = {geom["dielectric_er"]:.2f}

unit = 1e-3
sim_box = max(antipad_d * 4, 5.0)

FDTD = openEMS(NrTS=30000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# Ground planes with antipad clearance
copper.AddBox([-sim_box, -sim_box, 0], [sim_box, sim_box, 0], priority=10)
copper.AddBox([-sim_box, -sim_box, board_h], [sim_box, sim_box, board_h], priority=10)

# Substrate
substrate.AddBox([-sim_box, -sim_box, 0], [sim_box, sim_box, board_h], priority=1)

# Via barrel (cylinder approximated)
via = CSX.AddMetal("via_barrel")
via.AddCylinder([0, 0, 0], [0, 0, board_h], drill_d/2, priority=20)

# Pads
copper.AddCylinder([0, 0, 0], [0, 0, 0], pad_d/2, priority=15)
copper.AddCylinder([0, 0, board_h], [0, 0, board_h], pad_d/2, priority=15)

mesh.SmoothMeshLines("all", C0 / f_max / unit / 30)

sim_path = os.path.join(os.path.dirname(__file__), "via_sim")
FDTD.Run(sim_path, cleanup=True)
print("Via simulation complete.")
'''

    def _generate_trace_antenna_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS Python script for trace radiation analysis."""
        return f'''#!/usr/bin/env python3
"""OpenEMS trace radiation simulation.

Auto-generated by MCP PCB EMCopilot.
Trace: L={geom["trace_length_mm"]}mm, w={geom["trace_width_mm"]}mm, h={geom["height_above_ground_mm"]}mm
"""
import os
import numpy as np

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0
except ImportError:
    raise ImportError("openEMS not installed.")

f_max = {freq_hz * 3:.1f}
f_center = {freq_hz:.1f}
trace_l = {geom["trace_length_mm"]:.4f}
trace_w = {geom["trace_width_mm"]:.4f}
height = {geom["height_above_ground_mm"]:.4f}
sub_er = {geom["dielectric_er"]:.2f}

unit = 1e-3

FDTD = openEMS(NrTS=50000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_center, f_center)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# Ground plane
gnd_size = trace_l * 3
copper.AddBox([-gnd_size/2, -gnd_size/2, 0], [gnd_size/2, gnd_size/2, 0], priority=10)

# Substrate
substrate.AddBox([-gnd_size/2, -gnd_size/2, 0], [gnd_size/2, gnd_size/2, height], priority=1)

# Trace
copper.AddBox([-trace_l/2, -trace_w/2, height], [trace_l/2, trace_w/2, height], priority=10)

# NF2FF box for radiation pattern
nf2ff = FDTD.CreateNF2FFBox()

mesh.SmoothMeshLines("all", C0 / f_max / unit / 20)

sim_path = os.path.join(os.path.dirname(__file__), "trace_antenna_sim")
FDTD.Run(sim_path, cleanup=True)

# Calculate radiation pattern
freq_calc = np.array([f_center])
theta = np.arange(0, 181, 5)
phi = np.array([0, 90])
nf2ff_res = nf2ff.CalcNF2FF(sim_path, freq_calc, theta, phi)
print(f"Directivity: {{nf2ff_res.Dmax[0]:.2f}} dBi")
print(f"Radiated power: {{nf2ff_res.Prad[0]:.6f}} W")
'''

    # =================================================================
    # Coupled-line models (differential pair simulation)
    # =================================================================

    def generate_coupled_microstrip_model(
        self,
        trace_width_mm: float,
        spacing_mm: float,
        dielectric_height_mm: float,
        er: float = 4.3,
        trace_length_mm: float = 50.0,
        frequency_ghz: float = 1.0,
        trace_thickness_mm: float = 0.035,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for edge-coupled differential microstrip.

        Two parallel traces over a ground plane with 4 lumped ports
        (near/far end of each trace).
        """
        freq_hz = frequency_ghz * 1e9
        c0 = 299792458.0
        wavelength_mm = (c0 / freq_hz / math.sqrt(er)) * 1000
        margin_mm = max(5.0, dielectric_height_mm * 10)

        geometry = {
            "trace_width_mm": trace_width_mm,
            "spacing_mm": spacing_mm,
            "trace_length_mm": trace_length_mm,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "dielectric_er": er,
            "substrate_width_mm": trace_length_mm + 2 * margin_mm,
            "substrate_depth_mm": (spacing_mm + 2 * trace_width_mm) * 10,
            "air_height_mm": dielectric_height_mm * 10,
            "wavelength_mm": wavelength_mm,
        }

        model = OpenEMSModel(
            model_type="coupled_microstrip",
            description=(
                f"Coupled microstrip: w={trace_width_mm}mm, s={spacing_mm}mm, "
                f"h={dielectric_height_mm}mm, er={er}, f={frequency_ghz}GHz"
            ),
            geometry=geometry,
            frequency_range_hz=(0, freq_hz * 2),
            mesh_resolution=20,
        )
        model.script = self._generate_coupled_microstrip_script(geometry, freq_hz)
        return model

    def generate_coupled_stripline_model(
        self,
        trace_width_mm: float,
        spacing_mm: float,
        total_dielectric_height_mm: float,
        er: float = 4.3,
        trace_length_mm: float = 50.0,
        frequency_ghz: float = 1.0,
        trace_thickness_mm: float = 0.018,
    ) -> OpenEMSModel:
        """Generate OpenEMS model for edge-coupled differential stripline.

        Two parallel traces centered between two ground planes with 4 lumped ports.
        """
        freq_hz = frequency_ghz * 1e9
        c0 = 299792458.0
        wavelength_mm = (c0 / freq_hz / math.sqrt(er)) * 1000

        geometry = {
            "trace_width_mm": trace_width_mm,
            "spacing_mm": spacing_mm,
            "trace_length_mm": trace_length_mm,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_height_mm": total_dielectric_height_mm / 2,
            "total_height_mm": total_dielectric_height_mm,
            "dielectric_er": er,
            "substrate_width_mm": trace_length_mm + 20,
            "substrate_depth_mm": (spacing_mm + 2 * trace_width_mm) * 10,
            "wavelength_mm": wavelength_mm,
        }

        model = OpenEMSModel(
            model_type="coupled_stripline",
            description=(
                f"Coupled stripline: w={trace_width_mm}mm, s={spacing_mm}mm, "
                f"b={total_dielectric_height_mm}mm, er={er}, f={frequency_ghz}GHz"
            ),
            geometry=geometry,
            frequency_range_hz=(0, freq_hz * 2),
            mesh_resolution=20,
        )
        model.script = self._generate_coupled_stripline_script(geometry, freq_hz)
        return model

    # =================================================================
    # Dispatcher: SimulationCandidate -> OpenEMSModel
    # =================================================================

    def generate_from_candidate(self, candidate: "SimulationCandidate") -> OpenEMSModel:
        """Route a SimulationCandidate to the appropriate model generator."""
        st = candidate.structure_type

        if st == "microstrip":
            return self.generate_microstrip_model(
                trace_width_mm=candidate.trace_width_mm,
                dielectric_height_mm=candidate.dielectric_height_mm,
                trace_thickness_mm=candidate.copper_thickness_mm,
                er=candidate.dielectric_er,
                frequency_ghz=candidate.frequency_ghz,
                trace_length_mm=candidate.trace_length_mm,
            )
        elif st == "stripline":
            return self.generate_stripline_model(
                trace_width_mm=candidate.trace_width_mm,
                dielectric_height_mm=candidate.dielectric_height_mm,
                trace_thickness_mm=candidate.copper_thickness_mm,
                er=candidate.dielectric_er,
                frequency_ghz=candidate.frequency_ghz,
                trace_length_mm=candidate.trace_length_mm,
            )
        elif st == "coupled_microstrip":
            return self.generate_coupled_microstrip_model(
                trace_width_mm=candidate.trace_width_mm,
                spacing_mm=candidate.spacing_mm or 0.2,
                dielectric_height_mm=candidate.dielectric_height_mm,
                er=candidate.dielectric_er,
                trace_length_mm=candidate.trace_length_mm,
                frequency_ghz=candidate.frequency_ghz,
                trace_thickness_mm=candidate.copper_thickness_mm,
            )
        elif st == "coupled_stripline":
            return self.generate_coupled_stripline_model(
                trace_width_mm=candidate.trace_width_mm,
                spacing_mm=candidate.spacing_mm or 0.2,
                total_dielectric_height_mm=candidate.dielectric_height_mm,
                er=candidate.dielectric_er,
                trace_length_mm=candidate.trace_length_mm,
                frequency_ghz=candidate.frequency_ghz,
                trace_thickness_mm=candidate.copper_thickness_mm,
            )
        elif st == "via_transition":
            return self.generate_via_model(
                drill_diameter_mm=candidate.via_drill_mm or 0.3,
                pad_diameter_mm=candidate.via_pad_mm or 0.6,
                board_thickness_mm=candidate.dielectric_height_mm,
                er=candidate.dielectric_er,
                frequency_ghz=candidate.frequency_ghz,
            )
        else:
            raise ValueError(f"Unknown structure_type '{st}'")

    def generate_batch(
        self, candidates: list["SimulationCandidate"]
    ) -> list[OpenEMSModel]:
        """Generate OpenEMS models for a list of candidates."""
        models: list[OpenEMSModel] = []
        for c in candidates:
            try:
                models.append(self.generate_from_candidate(c))
            except Exception:
                pass  # skip candidates that fail
        return models

    # =================================================================
    # Script generators for coupled-line models
    # =================================================================

    def _generate_coupled_microstrip_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS script for edge-coupled differential microstrip."""
        return f'''#!/usr/bin/env python3
"""OpenEMS coupled microstrip (differential pair) simulation.

Auto-generated by MCP PCB EMCopilot.
Traces: w={geom["trace_width_mm"]}mm, s={geom["spacing_mm"]}mm, h={geom["dielectric_height_mm"]}mm, er={geom["dielectric_er"]}
"""
import os
import numpy as np

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0, EPS0, MUE0
except ImportError:
    raise ImportError(
        "openEMS not installed. Install via: "
        "conda install -c conda-forge openems"
    )

# --- Simulation Parameters ---
f_max = {freq_hz * 2:.1f}  # Hz
trace_w = {geom["trace_width_mm"]:.4f}  # mm
trace_s = {geom["spacing_mm"]:.4f}  # mm  (center-to-center)
trace_l = {geom["trace_length_mm"]:.4f}  # mm
trace_t = {geom["trace_thickness_mm"]:.4f}  # mm
sub_h = {geom["dielectric_height_mm"]:.4f}  # mm
sub_er = {geom["dielectric_er"]:.2f}
sub_w = {geom["substrate_width_mm"]:.4f}  # mm
sub_d = {geom["substrate_depth_mm"]:.4f}  # mm
air_h = {geom["air_height_mm"]:.4f}  # mm

unit = 1e-3  # mm

# Edge-to-edge gap
gap = trace_s - trace_w  # approximate edge gap from center-to-center
if gap < 0.01:
    gap = 0.01  # minimum gap

# Trace Y positions (symmetric about Y=0)
y1_center = -trace_s / 2   # trace 1 center
y2_center = trace_s / 2    # trace 2 center

# --- Setup FDTD ---
FDTD = openEMS(NrTS=60000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

# --- Materials ---
substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# --- Geometry ---
# Ground plane
copper.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, 0], priority=10)

# Substrate
substrate.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, sub_h], priority=1)

# Trace margins
margin_x = (sub_w - trace_l) / 2
trace_start_x = margin_x
trace_end_x = margin_x + trace_l

# Trace 1 (P)
copper.AddBox(
    [trace_start_x, y1_center - trace_w/2, sub_h],
    [trace_end_x, y1_center + trace_w/2, sub_h + trace_t],
    priority=10
)

# Trace 2 (N)
copper.AddBox(
    [trace_start_x, y2_center - trace_w/2, sub_h],
    [trace_end_x, y2_center + trace_w/2, sub_h + trace_t],
    priority=10
)

# --- 4 Lumped Ports ---
# Port 1: Trace 1 near end
port1 = FDTD.AddLumpedPort(1, 50,
    [trace_start_x, y1_center - trace_w/2, 0],
    [trace_start_x, y1_center + trace_w/2, sub_h], "z", excite=1)
# Port 2: Trace 1 far end
port2 = FDTD.AddLumpedPort(2, 50,
    [trace_end_x, y1_center - trace_w/2, 0],
    [trace_end_x, y1_center + trace_w/2, sub_h], "z")
# Port 3: Trace 2 near end
port3 = FDTD.AddLumpedPort(3, 50,
    [trace_start_x, y2_center - trace_w/2, 0],
    [trace_start_x, y2_center + trace_w/2, sub_h], "z")
# Port 4: Trace 2 far end
port4 = FDTD.AddLumpedPort(4, 50,
    [trace_end_x, y2_center - trace_w/2, 0],
    [trace_end_x, y2_center + trace_w/2, sub_h], "z")

# --- Mesh ---
mesh.AddLine("x", np.concatenate([
    np.array([0, sub_w]),
    np.linspace(trace_start_x, trace_end_x, 40),
]))
mesh.AddLine("y", np.concatenate([
    np.array([-sub_d/2, sub_d/2]),
    np.linspace(y1_center - trace_w, y1_center + trace_w, 8),
    np.linspace(y2_center - trace_w, y2_center + trace_w, 8),
]))
mesh.AddLine("z", np.concatenate([
    np.array([-air_h, sub_h + air_h]),
    np.linspace(0, sub_h + trace_t, 10),
]))
mesh.SmoothMeshLines("all", C0 / f_max / unit / 20)

# --- Run ---
sim_path = os.path.join(os.path.dirname(__file__), "coupled_microstrip_sim")
FDTD.Run(sim_path, cleanup=True)

# --- Post-process: 4-port S-parameters ---
freq = np.linspace(1e6, f_max, 1000)
port1.CalcPort(sim_path, freq)
port2.CalcPort(sim_path, freq)
port3.CalcPort(sim_path, freq)
port4.CalcPort(sim_path, freq)

# Single-ended S-parameters
s11 = port1.uf_ref / port1.uf_inc
s21 = port2.uf_ref / port1.uf_inc
s31 = port3.uf_ref / port1.uf_inc  # near-end coupling
s41 = port4.uf_ref / port1.uf_inc  # far-end coupling

# Approximate differential impedance from port 1 excitation
Z0_se = port1.uf_tot / port1.if_tot

# Mixed-mode: Zdiff ~ 2 * Zodd, Zcomm ~ Zeven / 2
fc_idx = len(freq) // 2
print(f"=== Coupled Microstrip Results at {{freq[fc_idx]/1e9:.2f}} GHz ===")
print(f"Z0 (single-ended):  {{np.real(Z0_se[fc_idx]):.1f}} ohms")
print(f"S11: {{20*np.log10(np.abs(s11[fc_idx])):.1f}} dB")
print(f"S21 (through):  {{20*np.log10(np.abs(s21[fc_idx])):.1f}} dB")
print(f"S31 (NEXT):     {{20*np.log10(np.abs(s31[fc_idx])):.1f}} dB")
print(f"S41 (FEXT):     {{20*np.log10(np.abs(s41[fc_idx])):.1f}} dB")
'''

    def _generate_coupled_stripline_script(self, geom: dict, freq_hz: float) -> str:
        """Generate OpenEMS script for edge-coupled differential stripline."""
        return f'''#!/usr/bin/env python3
"""OpenEMS coupled stripline (differential pair) simulation.

Auto-generated by MCP PCB EMCopilot.
Traces: w={geom["trace_width_mm"]}mm, s={geom["spacing_mm"]}mm, b={geom["total_height_mm"]}mm, er={geom["dielectric_er"]}
"""
import os
import numpy as np

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from openEMS.physical_constants import C0
except ImportError:
    raise ImportError("openEMS not installed.")

# --- Simulation Parameters ---
f_max = {freq_hz * 2:.1f}
trace_w = {geom["trace_width_mm"]:.4f}
trace_s = {geom["spacing_mm"]:.4f}  # center-to-center
trace_l = {geom["trace_length_mm"]:.4f}
trace_t = {geom["trace_thickness_mm"]:.4f}
sub_h = {geom["dielectric_height_mm"]:.4f}  # half-height (trace at center)
total_h = {geom["total_height_mm"]:.4f}
sub_er = {geom["dielectric_er"]:.2f}
sub_w = {geom["substrate_width_mm"]:.4f}
sub_d = {geom["substrate_depth_mm"]:.4f}

unit = 1e-3

# Trace Y positions
y1_center = -trace_s / 2
y2_center = trace_s / 2

# --- Setup FDTD ---
FDTD = openEMS(NrTS=60000, EndCriteria=1e-5)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(unit)

substrate = CSX.AddMaterial("substrate", epsilon=sub_er)
copper = CSX.AddMetal("copper")

# Bottom ground
copper.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, 0], priority=10)
# Top ground
copper.AddBox([0, -sub_d/2, total_h], [sub_w, sub_d/2, total_h], priority=10)
# Dielectric fill
substrate.AddBox([0, -sub_d/2, 0], [sub_w, sub_d/2, total_h], priority=1)

# Traces centered vertically
trace_z = sub_h
margin_x = (sub_w - trace_l) / 2
trace_start_x = margin_x
trace_end_x = margin_x + trace_l

# Trace 1 (P)
copper.AddBox(
    [trace_start_x, y1_center - trace_w/2, trace_z],
    [trace_end_x, y1_center + trace_w/2, trace_z + trace_t],
    priority=10
)

# Trace 2 (N)
copper.AddBox(
    [trace_start_x, y2_center - trace_w/2, trace_z],
    [trace_end_x, y2_center + trace_w/2, trace_z + trace_t],
    priority=10
)

# --- 4 Lumped Ports ---
port1 = FDTD.AddLumpedPort(1, 50,
    [trace_start_x, y1_center - trace_w/2, 0],
    [trace_start_x, y1_center + trace_w/2, trace_z], "z", excite=1)
port2 = FDTD.AddLumpedPort(2, 50,
    [trace_end_x, y1_center - trace_w/2, 0],
    [trace_end_x, y1_center + trace_w/2, trace_z], "z")
port3 = FDTD.AddLumpedPort(3, 50,
    [trace_start_x, y2_center - trace_w/2, 0],
    [trace_start_x, y2_center + trace_w/2, trace_z], "z")
port4 = FDTD.AddLumpedPort(4, 50,
    [trace_end_x, y2_center - trace_w/2, 0],
    [trace_end_x, y2_center + trace_w/2, trace_z], "z")

# --- Mesh ---
mesh.SmoothMeshLines("all", C0 / f_max / unit / 20)

# --- Run ---
sim_path = os.path.join(os.path.dirname(__file__), "coupled_stripline_sim")
FDTD.Run(sim_path, cleanup=True)

# --- Post-process ---
freq = np.linspace(1e6, f_max, 1000)
port1.CalcPort(sim_path, freq)
port2.CalcPort(sim_path, freq)
port3.CalcPort(sim_path, freq)
port4.CalcPort(sim_path, freq)

s11 = port1.uf_ref / port1.uf_inc
s21 = port2.uf_ref / port1.uf_inc
s31 = port3.uf_ref / port1.uf_inc
s41 = port4.uf_ref / port1.uf_inc
Z0_se = port1.uf_tot / port1.if_tot

fc_idx = len(freq) // 2
print(f"=== Coupled Stripline Results at {{freq[fc_idx]/1e9:.2f}} GHz ===")
print(f"Z0 (single-ended):  {{np.real(Z0_se[fc_idx]):.1f}} ohms")
print(f"S11: {{20*np.log10(np.abs(s11[fc_idx])):.1f}} dB")
print(f"S21 (through):  {{20*np.log10(np.abs(s21[fc_idx])):.1f}} dB")
print(f"S31 (NEXT):     {{20*np.log10(np.abs(s31[fc_idx])):.1f}} dB")
print(f"S41 (FEXT):     {{20*np.log10(np.abs(s41[fc_idx])):.1f}} dB")
'''
