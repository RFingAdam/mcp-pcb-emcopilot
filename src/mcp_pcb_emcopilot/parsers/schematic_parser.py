"""Schematic file parsers for KiCad and other EDA formats.

Supports:
- KiCad .kicad_sch (S-expression format) - Priority #1
- Future: Altium, OrCAD, Eagle formats
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedComponent:
    """Component extracted from schematic."""
    reference: str
    value: Optional[str] = None
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    footprint: Optional[str] = None
    sheet_number: int = 1
    x_coord: float = 0.0
    y_coord: float = 0.0
    properties: dict = field(default_factory=dict)
    pins: list[dict] = field(default_factory=list)


@dataclass
class ParsedNet:
    """Net extracted from schematic."""
    net_name: str
    net_code: Optional[int] = None
    pins: list[dict] = field(default_factory=list)
    is_power: bool = False
    is_ground: bool = False


@dataclass
class ParsedSchematicData:
    """Complete parsed schematic data."""
    components: list[ParsedComponent] = field(default_factory=list)
    nets: list[ParsedNet] = field(default_factory=list)
    sheet_count: int = 1
    title: Optional[str] = None
    revision: Optional[str] = None
    designer: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


class KiCadSchematicParser:
    """Parser for KiCad .kicad_sch files (S-expression format)."""

    def __init__(self):
        self.components: list[ParsedComponent] = []
        self.nets: dict[str, ParsedNet] = {}
        self.warnings: list[str] = []

    def parse(self, file_path: str) -> ParsedSchematicData:
        """Parse KiCad schematic file.

        Args:
            file_path: Path to .kicad_sch file

        Returns:
            ParsedSchematicData with components and nets

        Raises:
            ValueError: If file format is invalid
        """
        logger.info(f"Parsing KiCad schematic: {file_path}")

        try:
            with open(file_path, encoding='utf-8') as f:
                content = f.read()

            # Parse S-expression structure
            self._parse_kicad_sch(content)

            # Build result
            result = ParsedSchematicData(
                components=self.components,
                nets=list(self.nets.values()),
                warnings=self.warnings,
            )

            logger.info(f"Parsed {len(result.components)} components, {len(result.nets)} nets")
            return result

        except Exception as e:
            logger.error(f"Failed to parse KiCad schematic: {e}")
            raise ValueError(f"KiCad schematic parse error: {str(e)}") from e

    def _parse_kicad_sch(self, content: str) -> None:
        """Parse KiCad schematic S-expression content."""
        # Extract symbols (components)
        symbol_pattern = r'\(symbol\s+\(lib_id\s+"([^"]+)"\)'
        symbols = re.finditer(symbol_pattern, content)

        for match in symbols:
            try:
                component = self._parse_symbol_section(content, match.start())
                if component:
                    self.components.append(component)
            except Exception as e:
                self.warnings.append(f"Failed to parse symbol: {str(e)}")

        # Extract nets from hierarchical labels and global labels
        self._extract_nets_from_labels(content)

        # Extract power symbols (VCC, GND, etc.)
        self._extract_power_nets(content)

    def _parse_symbol_section(self, content: str, start_pos: int) -> Optional[ParsedComponent]:
        """Parse individual symbol section."""
        # Find the complete symbol block
        depth = 0
        end_pos = start_pos
        for i in range(start_pos, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        symbol_text = content[start_pos:end_pos]

        # Extract reference designator
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', symbol_text)
        if not ref_match:
            return None

        reference = ref_match.group(1)

        # Skip power symbols (like #PWR)
        if reference.startswith('#'):
            return None

        # Extract value
        value_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', symbol_text)
        value = value_match.group(1) if value_match else None

        # Extract footprint
        footprint_match = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', symbol_text)
        footprint = footprint_match.group(1) if footprint_match else None

        # Extract datasheet/part number
        datasheet_match = re.search(r'\(property\s+"Datasheet"\s+"([^"]+)"', symbol_text)
        part_number = datasheet_match.group(1) if datasheet_match else None

        # Extract position
        pos_match = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', symbol_text)
        x_coord = float(pos_match.group(1)) if pos_match else 0.0
        y_coord = float(pos_match.group(2)) if pos_match else 0.0

        # Build component
        component = ParsedComponent(
            reference=reference,
            value=value,
            part_number=part_number,
            footprint=footprint,
            x_coord=x_coord,
            y_coord=y_coord,
        )

        # Extract pins
        component.pins = self._extract_pins(symbol_text, reference)

        return component

    def _extract_pins(self, symbol_text: str, reference: str) -> list[dict]:
        """Extract pin information from symbol."""
        pins = []

        # Find all pin declarations
        pin_pattern = r'\(pin\s+\w+\s+line\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+\d+\)'
        pin_matches = re.finditer(pin_pattern, symbol_text)

        pin_num = 1
        for match in pin_matches:
            pins.append({
                "pin_number": str(pin_num),
                "x_offset": float(match.group(1)),
                "y_offset": float(match.group(2)),
            })
            pin_num += 1

        return pins

    def _extract_nets_from_labels(self, content: str) -> None:
        """Extract nets from hierarchical and global labels."""
        # Hierarchical labels
        hier_label_pattern = r'\(hierarchical_label\s+"([^"]+)"'
        for match in re.finditer(hier_label_pattern, content):
            net_name = match.group(1)
            if net_name not in self.nets:
                self.nets[net_name] = ParsedNet(net_name=net_name)

        # Global labels
        global_label_pattern = r'\(global_label\s+"([^"]+)"'
        for match in re.finditer(global_label_pattern, content):
            net_name = match.group(1)
            if net_name not in self.nets:
                self.nets[net_name] = ParsedNet(net_name=net_name)

    def _extract_power_nets(self, content: str) -> None:
        """Extract power symbols and classify as power/ground nets."""
        # Power port pattern (e.g., +3V3, VCC, GND, etc.)
        power_pattern = r'\(lib_id\s+"power:([^"]+)"\)'

        for match in re.finditer(power_pattern, content):
            power_symbol = match.group(1)

            if power_symbol not in self.nets:
                is_ground = any(gnd in power_symbol.upper() for gnd in ['GND', 'VSS', 'EARTH'])
                is_power = not is_ground

                self.nets[power_symbol] = ParsedNet(
                    net_name=power_symbol,
                    is_power=is_power,
                    is_ground=is_ground,
                )


class SchematicParserFactory:
    """Factory to create appropriate parser based on file type."""

    @staticmethod
    def create_parser(file_path: str) -> Any:
        """Create parser based on file extension.

        Args:
            file_path: Path to schematic file

        Returns:
            A parser instance whose ``.parse(file_path)`` returns
            :class:`ParsedSchematicData`. Typed as ``Any`` because the
            concrete class varies by extension (``KiCadSchematicParser``,
            ``AltiumSchematicParser``) and they share a duck-typed parse
            surface rather than an abstract base class.

        Raises:
            ValueError: If file type is not supported
        """
        path = Path(file_path)
        extension = path.suffix.lower()

        if extension == '.kicad_sch':
            return KiCadSchematicParser()
        elif extension == '.schdoc':
            # Altium schematic format
            from .altium_parser import AltiumSchematicParser
            return AltiumSchematicParser()
        elif extension == '.sch':
            # Could be OrCAD or legacy format - not yet supported
            raise ValueError(f"Legacy .sch format not yet supported: {extension}")
        else:
            raise ValueError(f"Unknown schematic file format: {extension}")

    @staticmethod
    def parse(file_path: str) -> ParsedSchematicData:
        """Parse schematic file with automatic format detection.

        Args:
            file_path: Path to schematic file

        Returns:
            ParsedSchematicData

        Raises:
            ValueError: If file format is not supported
        """
        parser = SchematicParserFactory.create_parser(file_path)
        result: ParsedSchematicData = parser.parse(file_path)
        return result
