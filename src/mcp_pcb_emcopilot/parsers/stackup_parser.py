"""Stackup parser for extracting and computing layer stackup properties"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MaterialType(Enum):
    """Material types for PCB layers"""
    COPPER = "copper"
    FR4 = "fr4"
    PREPREG = "prepreg"
    CORE = "core"
    SOLDER_MASK = "solder_mask"
    ROGERS = "rogers"
    POLYIMIDE = "polyimide"
    PTFE = "ptfe"
    CUSTOM = "custom"


@dataclass
class MaterialProperties:
    """Material electrical and physical properties"""
    name: str
    material_type: MaterialType

    # Electrical properties
    dielectric_constant: float = 4.3  # Er
    loss_tangent: float = 0.02  # tan(d)
    conductivity_s_per_m: float = 5.8e7  # Copper default

    # Physical properties
    density_g_per_cm3: Optional[float] = None
    thermal_conductivity_w_per_mk: Optional[float] = None

    # Temperature characteristics
    tg_celsius: Optional[float] = None  # Glass transition temperature
    cte_ppm_per_c: Optional[float] = None  # Coefficient of thermal expansion


# Standard material library
MATERIAL_LIBRARY: Dict[str, MaterialProperties] = {
    "copper": MaterialProperties(
        name="Copper (1oz)",
        material_type=MaterialType.COPPER,
        dielectric_constant=1.0,
        loss_tangent=0.0,
        conductivity_s_per_m=5.8e7,
        density_g_per_cm3=8.96,
        thermal_conductivity_w_per_mk=401,
    ),
    "fr4": MaterialProperties(
        name="Standard FR4",
        material_type=MaterialType.FR4,
        dielectric_constant=4.3,
        loss_tangent=0.02,
        tg_celsius=130,
        cte_ppm_per_c=14,
    ),
    "fr4_high_tg": MaterialProperties(
        name="High Tg FR4",
        material_type=MaterialType.FR4,
        dielectric_constant=4.2,
        loss_tangent=0.018,
        tg_celsius=170,
        cte_ppm_per_c=12,
    ),
    "rogers_4350b": MaterialProperties(
        name="Rogers RO4350B",
        material_type=MaterialType.ROGERS,
        dielectric_constant=3.48,
        loss_tangent=0.0037,
        tg_celsius=280,
    ),
    "rogers_4003c": MaterialProperties(
        name="Rogers RO4003C",
        material_type=MaterialType.ROGERS,
        dielectric_constant=3.55,
        loss_tangent=0.0027,
        tg_celsius=280,
    ),
    "isola_370hr": MaterialProperties(
        name="Isola 370HR",
        material_type=MaterialType.FR4,
        dielectric_constant=4.04,
        loss_tangent=0.021,
        tg_celsius=180,
    ),
    "megtron6": MaterialProperties(
        name="Panasonic Megtron 6",
        material_type=MaterialType.CUSTOM,
        dielectric_constant=3.4,
        loss_tangent=0.002,
        tg_celsius=185,
    ),
    "nelco_n4000_13ep": MaterialProperties(
        name="Nelco N4000-13 EP",
        material_type=MaterialType.FR4,
        dielectric_constant=3.7,
        loss_tangent=0.008,
        tg_celsius=210,
    ),
    "polyimide": MaterialProperties(
        name="Polyimide (Flex)",
        material_type=MaterialType.POLYIMIDE,
        dielectric_constant=3.5,
        loss_tangent=0.003,
    ),
    "ptfe": MaterialProperties(
        name="PTFE/Teflon",
        material_type=MaterialType.PTFE,
        dielectric_constant=2.1,
        loss_tangent=0.0002,
    ),
    "solder_mask": MaterialProperties(
        name="Solder Mask",
        material_type=MaterialType.SOLDER_MASK,
        dielectric_constant=3.3,
        loss_tangent=0.035,
    ),
}


@dataclass
class StackupLayer:
    """Individual layer in stackup"""
    name: str
    layer_number: int
    layer_type: str  # signal, plane, dielectric, solder_mask

    # Physical dimensions
    thickness_mm: float
    thickness_um: float = 0  # Computed from thickness_mm

    # Material
    material: MaterialProperties = field(default_factory=lambda: MATERIAL_LIBRARY["fr4"])
    copper_weight_oz: Optional[float] = None  # For copper layers

    # Electrical properties (may override material defaults)
    dielectric_constant: Optional[float] = None
    loss_tangent: Optional[float] = None

    # Reference information
    reference_layer_number: Optional[int] = None  # For signal layers
    distance_to_reference_mm: Optional[float] = None

    def __post_init__(self) -> None:
        self.thickness_um = self.thickness_mm * 1000

    @property
    def effective_dielectric(self) -> float:
        """Get effective dielectric constant"""
        if self.dielectric_constant is not None:
            return self.dielectric_constant
        return self.material.dielectric_constant

    @property
    def effective_loss_tangent(self) -> float:
        """Get effective loss tangent"""
        if self.loss_tangent is not None:
            return self.loss_tangent
        return self.material.loss_tangent

    @property
    def copper_thickness_um(self) -> Optional[float]:
        """Get copper thickness in micrometers"""
        if self.copper_weight_oz is not None:
            return self.copper_weight_oz * 35.0  # 1 oz = 35um
        return None


@dataclass
class Stackup:
    """Complete PCB stackup definition"""
    name: str = "Default Stackup"
    layers: List[StackupLayer] = field(default_factory=list)

    # Summary properties
    total_thickness_mm: float = 0
    copper_layer_count: int = 0

    # Default properties
    default_material: str = "fr4"
    default_copper_weight_oz: float = 1.0

    def __post_init__(self) -> None:
        self._recalculate()

    def _recalculate(self) -> None:
        """Recalculate derived properties"""
        self.total_thickness_mm = sum(l.thickness_mm for l in self.layers)
        self.copper_layer_count = len([l for l in self.layers if l.layer_type in ("signal", "plane")])

    def add_layer(self, layer: StackupLayer) -> None:
        """Add a layer to the stackup"""
        self.layers.append(layer)
        self._recalculate()

    def get_layer_by_number(self, number: int) -> Optional[StackupLayer]:
        """Find layer by number"""
        for layer in self.layers:
            if layer.layer_number == number:
                return layer
        return None

    def get_copper_layers(self) -> List[StackupLayer]:
        """Get only copper (signal/plane) layers"""
        return [l for l in self.layers if l.layer_type in ("signal", "plane")]

    def get_dielectric_between(self, layer1_num: int, layer2_num: int) -> List[StackupLayer]:
        """Get dielectric layers between two copper layers"""
        min_num = min(layer1_num, layer2_num)
        max_num = max(layer1_num, layer2_num)

        return [
            l for l in self.layers
            if l.layer_type == "dielectric"
            and min_num < l.layer_number < max_num
        ]

    def get_height_between_layers(self, layer1_num: int, layer2_num: int) -> float:
        """Calculate total dielectric height between two layers"""
        dielectrics = self.get_dielectric_between(layer1_num, layer2_num)
        return sum(l.thickness_mm for l in dielectrics)

    def get_effective_er_between(self, layer1_num: int, layer2_num: int) -> float:
        """Calculate effective dielectric constant between two layers"""
        dielectrics = self.get_dielectric_between(layer1_num, layer2_num)
        if not dielectrics:
            return 4.3  # Default FR4

        # Weighted average by thickness
        total_thickness = sum(l.thickness_mm for l in dielectrics)
        if total_thickness == 0:
            return 4.3

        weighted_er = sum(l.thickness_mm * l.effective_dielectric for l in dielectrics)
        return weighted_er / total_thickness


class StackupParser:
    """
    Stackup parser and calculator.

    Creates stackups from various input formats and calculates
    electrical properties for RF/SI analysis.
    """

    # Standard copper weights and thicknesses
    COPPER_WEIGHTS = {
        0.5: 17.5,   # 0.5 oz = 17.5 um
        1.0: 35.0,   # 1 oz = 35 um
        2.0: 70.0,   # 2 oz = 70 um
        3.0: 105.0,  # 3 oz = 105 um
    }

    # Standard core thicknesses (mm)
    STANDARD_CORES = [0.1, 0.2, 0.36, 0.51, 0.71, 1.0, 1.2, 1.6]

    # Standard prepreg thicknesses (mm)
    STANDARD_PREPREGS = [0.05, 0.075, 0.1, 0.127, 0.15, 0.2]

    def __init__(self):
        self.material_library = MATERIAL_LIBRARY.copy()

    def create_standard_stackup(
        self,
        layer_count: int,
        total_thickness_mm: float = 1.6,
        copper_weight_oz: float = 1.0,
        material: str = "fr4",
    ) -> Stackup:
        """
        Create a standard symmetric stackup.

        Args:
            layer_count: Number of copper layers (2, 4, 6, 8, etc.)
            total_thickness_mm: Target total board thickness
            copper_weight_oz: Copper weight for all layers
            material: Dielectric material name

        Returns:
            Stackup with appropriate layers
        """
        if layer_count < 2 or layer_count % 2 != 0:
            raise ValueError("Layer count must be even and >= 2")

        stackup = Stackup(name=f"{layer_count}L Standard")
        mat = self.material_library.get(material, self.material_library["fr4"])

        # Calculate thicknesses
        copper_thickness_mm = (copper_weight_oz * 35.0) / 1000  # Convert um to mm
        total_copper = layer_count * copper_thickness_mm

        # Remaining thickness for dielectrics
        dielectric_thickness = total_thickness_mm - total_copper

        # For 2 layers: just one core
        # For 4+ layers: prepreg + core(s) + prepreg
        if layer_count == 2:
            # Add layers
            stackup.add_layer(StackupLayer(
                name="Top Solder Mask", layer_number=0, layer_type="solder_mask",
                thickness_mm=0.025, material=self.material_library["solder_mask"]
            ))
            stackup.add_layer(StackupLayer(
                name="L1-Top", layer_number=1, layer_type="signal",
                thickness_mm=copper_thickness_mm, material=self.material_library["copper"],
                copper_weight_oz=copper_weight_oz
            ))
            stackup.add_layer(StackupLayer(
                name="Core", layer_number=2, layer_type="dielectric",
                thickness_mm=dielectric_thickness, material=mat
            ))
            stackup.add_layer(StackupLayer(
                name="L2-Bottom", layer_number=3, layer_type="signal",
                thickness_mm=copper_thickness_mm, material=self.material_library["copper"],
                copper_weight_oz=copper_weight_oz
            ))
            stackup.add_layer(StackupLayer(
                name="Bottom Solder Mask", layer_number=4, layer_type="solder_mask",
                thickness_mm=0.025, material=self.material_library["solder_mask"]
            ))

        else:
            # Multi-layer stackup
            num_cores = layer_count // 2
            num_prepregs = layer_count // 2 - 1

            # Calculate dielectric distribution
            prepreg_thickness = 0.1  # mm
            core_thickness = (dielectric_thickness - num_prepregs * 2 * prepreg_thickness) / num_cores

            layer_num = 0

            # Top solder mask
            stackup.add_layer(StackupLayer(
                name="Top Solder Mask", layer_number=layer_num, layer_type="solder_mask",
                thickness_mm=0.025, material=self.material_library["solder_mask"]
            ))
            layer_num += 1

            # Build layer pairs
            for i in range(layer_count):
                is_outer = (i == 0 or i == layer_count - 1)
                layer_name = f"L{i+1}"

                if is_outer:
                    layer_name += "-Top" if i == 0 else "-Bottom"

                # Add copper layer
                stackup.add_layer(StackupLayer(
                    name=layer_name, layer_number=layer_num,
                    layer_type="signal" if i % 2 == 0 or i == layer_count - 1 else "plane",
                    thickness_mm=copper_thickness_mm, material=self.material_library["copper"],
                    copper_weight_oz=copper_weight_oz
                ))
                layer_num += 1

                # Add dielectric after copper (except last)
                if i < layer_count - 1:
                    if i % 2 == 0:
                        # Prepreg after odd copper layers
                        stackup.add_layer(StackupLayer(
                            name=f"Prepreg-{i//2 + 1}", layer_number=layer_num,
                            layer_type="dielectric",
                            thickness_mm=prepreg_thickness, material=mat
                        ))
                    else:
                        # Core after even copper layers
                        stackup.add_layer(StackupLayer(
                            name=f"Core-{i//2 + 1}", layer_number=layer_num,
                            layer_type="dielectric",
                            thickness_mm=core_thickness, material=mat
                        ))
                    layer_num += 1

            # Bottom solder mask
            stackup.add_layer(StackupLayer(
                name="Bottom Solder Mask", layer_number=layer_num, layer_type="solder_mask",
                thickness_mm=0.025, material=self.material_library["solder_mask"]
            ))

        return stackup

    def create_from_dict(self, data: Dict[str, Any]) -> Stackup:
        """
        Create stackup from dictionary data (e.g., from JSON config).

        Args:
            data: Dictionary with stackup definition

        Returns:
            Stackup object
        """
        stackup = Stackup(name=data.get("name", "Custom Stackup"))

        for i, layer_data in enumerate(data.get("layers", [])):
            material_name = layer_data.get("material", "fr4")
            material = self.material_library.get(
                material_name.lower(),
                self.material_library["fr4"]
            )

            layer = StackupLayer(
                name=layer_data.get("name", f"Layer-{i}"),
                layer_number=layer_data.get("number", i),
                layer_type=layer_data.get("type", "signal"),
                thickness_mm=layer_data.get("thickness_mm", 0.035),
                material=material,
                copper_weight_oz=layer_data.get("copper_weight_oz"),
                dielectric_constant=layer_data.get("er"),
                loss_tangent=layer_data.get("loss_tangent"),
            )
            stackup.add_layer(layer)

        return stackup

    def calculate_impedance_params(
        self,
        stackup: Stackup,
        signal_layer: int,
        reference_layer: int,
    ) -> Dict[str, float]:
        """
        Calculate impedance-related parameters for a signal/reference pair.

        Args:
            stackup: The stackup definition
            signal_layer: Signal layer number
            reference_layer: Reference (ground/power) layer number

        Returns:
            Dictionary with height, dielectric constant, etc.
        """
        height = stackup.get_height_between_layers(signal_layer, reference_layer)
        er = stackup.get_effective_er_between(signal_layer, reference_layer)

        # Get signal layer copper thickness
        sig_layer = stackup.get_layer_by_number(signal_layer)
        copper_t = 0.035  # Default 1oz
        if sig_layer and sig_layer.copper_thickness_um:
            copper_t = sig_layer.copper_thickness_um / 1000

        return {
            "height_mm": height,
            "height_um": height * 1000,
            "dielectric_constant": er,
            "copper_thickness_mm": copper_t,
            "copper_thickness_um": copper_t * 1000,
        }

    def add_custom_material(
        self,
        name: str,
        er: float,
        loss_tangent: float,
        material_type: MaterialType = MaterialType.CUSTOM,
        **kwargs: Any,
    ) -> None:
        """
        Add a custom material to the library.

        Args:
            name: Material name (key)
            er: Dielectric constant
            loss_tangent: Loss tangent
            material_type: Material category
            **kwargs: Additional MaterialProperties fields
        """
        self.material_library[name.lower()] = MaterialProperties(
            name=name,
            material_type=material_type,
            dielectric_constant=er,
            loss_tangent=loss_tangent,
            **kwargs
        )
