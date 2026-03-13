"""Shared test fixtures for PCB EMCopilot."""
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def simple_2layer_kicad():
    return str(FIXTURES_DIR / "simple_2layer.kicad_pcb")


@pytest.fixture
def mixed_signal_4layer_kicad():
    return str(FIXTURES_DIR / "mixed_signal_4layer.kicad_pcb")


@pytest.fixture
def sample_gerber():
    return str(FIXTURES_DIR / "sample_top_copper.gbr")


@pytest.fixture
def sample_ipc2581():
    return str(FIXTURES_DIR / "sample_design.xml")


@pytest.fixture
def sample_allegro():
    return str(FIXTURES_DIR / "sample_allegro.txt")


@pytest.fixture
def sample_design_data():
    """Create a minimal PCBDesignData for testing analyzers."""
    from mcp_pcb_emcopilot.models.pcb_data import (
        PCBComponent,
        PCBDesignData,
        PCBLayer,
        PCBNet,
        PCBTrace,
        PCBVia,
    )

    d = PCBDesignData(source_file="/tmp/test_board.kicad_pcb", source_format="kicad")
    d.board_width_mm = 100.0
    d.board_height_mm = 80.0
    d.layer_count = 4
    d.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
        PCBLayer(name="GND", number=1, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="PWR", number=2, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="B.Cu", number=3, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
    ]
    d.components = [
        PCBComponent(reference="U1", value="MCU", footprint="QFP-48", x_mm=50, y_mm=40, layer="F.Cu"),
        PCBComponent(reference="R1", value="10k", footprint="0402", x_mm=30, y_mm=20, layer="F.Cu"),
        PCBComponent(reference="C1", value="100nF", footprint="0402", x_mm=35, y_mm=25, layer="F.Cu"),
        PCBComponent(reference="J1", value="USB-C", footprint="USB-C-SMD", x_mm=0, y_mm=40, layer="F.Cu"),
    ]
    d.nets = [
        PCBNet(name="GND", index=0, pin_count=12),
        PCBNet(name="VCC_3V3", index=1, pin_count=6),
        PCBNet(name="USB_D_P", index=2, is_differential=True, differential_pair="USB_D_N", pin_count=2),
        PCBNet(name="USB_D_N", index=3, is_differential=True, differential_pair="USB_D_P", pin_count=2),
        PCBNet(name="SPI_CLK", index=4, pin_count=2),
        PCBNet(name="SPI_MOSI", index=5, pin_count=2),
        PCBNet(name="SPI_MISO", index=6, pin_count=2),
    ]
    d.traces = [
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=0, y1_mm=40, x2_mm=50, y2_mm=40, net_name="USB_D_P", net_index=2),
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=0, y1_mm=41, x2_mm=50, y2_mm=41, net_name="USB_D_N", net_index=3),
        PCBTrace(layer="F.Cu", width_mm=0.2, x1_mm=30, y1_mm=20, x2_mm=50, y2_mm=40, net_name="SPI_CLK", net_index=4),
    ]
    d.vias = [
        PCBVia(x_mm=25, y_mm=30, drill_mm=0.3, pad_diameter_mm=0.6, net_name="GND", net_index=0),
        PCBVia(x_mm=60, y_mm=50, drill_mm=0.3, pad_diameter_mm=0.6, net_name="VCC_3V3", net_index=1),
    ]
    return d
