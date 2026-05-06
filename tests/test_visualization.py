"""Tests for PCB design visualization — board renderer, stackup renderer, annotator.

Creates mock PCBDesignData and exercises all four visualization MCP tools
through their dispatch handlers.
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBLayer,
    PCBNet,
    PCBTrace,
    PCBVia,
    PCBZone,
)

# ---------------------------------------------------------------------------
# Shared mock design
# ---------------------------------------------------------------------------

def make_mock_design() -> PCBDesignData:
    """Create a realistic 4-layer PCB with components, traces, vias, zones."""
    design = PCBDesignData(
        source_file="test_viz.kicad_pcb",
        source_format="kicad",
        board_width_mm=80.0,
        board_height_mm=60.0,
        board_thickness_mm=1.6,
        layer_count=4,
        title="Visualization Test Board",
    )

    # Stackup
    design.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
        PCBLayer(name="Prepreg1", number=1, layer_type="dielectric", thickness_mm=0.2, material="FR-4", dielectric_constant=4.3),
        PCBLayer(name="In1.Cu", number=2, layer_type="plane", thickness_mm=0.035, copper_weight_oz=1.0),
        PCBLayer(name="Core", number=3, layer_type="dielectric", thickness_mm=1.0, material="FR-4", dielectric_constant=4.3),
        PCBLayer(name="In2.Cu", number=4, layer_type="plane", thickness_mm=0.035, copper_weight_oz=1.0),
        PCBLayer(name="Prepreg2", number=5, layer_type="dielectric", thickness_mm=0.2, material="FR-4", dielectric_constant=4.3),
        PCBLayer(name="B.Cu", number=6, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
    ]

    # Components
    design.components = [
        PCBComponent(reference="U1", value="STM32F4", package="LQFP48", layer="F.Cu", x_mm=30.0, y_mm=35.0, rotation=0),
        PCBComponent(reference="U2", value="LDO3V3", package="SOT-23-5", layer="F.Cu", x_mm=15.0, y_mm=50.0),
        PCBComponent(reference="R1", value="10k", package="0402", layer="F.Cu", x_mm=40.0, y_mm=30.0),
        PCBComponent(reference="R2", value="4.7k", package="0402", layer="F.Cu", x_mm=42.0, y_mm=30.0),
        PCBComponent(reference="C1", value="100nF", package="0402", layer="F.Cu", x_mm=28.0, y_mm=38.0),
        PCBComponent(reference="C2", value="10uF", package="0805", layer="F.Cu", x_mm=10.0, y_mm=48.0),
        PCBComponent(reference="J1", value="USB-C", package="USB_C_Receptacle", layer="F.Cu", x_mm=5.0, y_mm=30.0),
        PCBComponent(reference="D1", value="LED", package="0603", layer="F.Cu", x_mm=60.0, y_mm=10.0),
        PCBComponent(reference="Q1", value="2N7002", package="SOT-23", layer="F.Cu", x_mm=55.0, y_mm=20.0),
        PCBComponent(reference="Y1", value="8MHz", package="HC49", layer="F.Cu", x_mm=35.0, y_mm=42.0),
    ]

    # Nets
    design.nets = [
        PCBNet(name="GND", index=0, net_class="power"),
        PCBNet(name="VCC3V3", index=1, net_class="power"),
        PCBNet(name="USB_D+", index=2),
        PCBNet(name="USB_D-", index=3),
        PCBNet(name="CLK", index=4, max_frequency_hz=8e6),
        PCBNet(name="SDA", index=5),
        PCBNet(name="SCL", index=6),
    ]

    # Traces
    design.traces = [
        # USB_D+ trace
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=5.0, y1_mm=30.0, x2_mm=15.0, y2_mm=30.0, net_index=2, net_name="USB_D+"),
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=15.0, y1_mm=30.0, x2_mm=25.0, y2_mm=35.0, net_index=2, net_name="USB_D+"),
        # USB_D- trace
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=5.0, y1_mm=32.0, x2_mm=15.0, y2_mm=32.0, net_index=3, net_name="USB_D-"),
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=15.0, y1_mm=32.0, x2_mm=25.0, y2_mm=37.0, net_index=3, net_name="USB_D-"),
        # CLK
        PCBTrace(layer="F.Cu", width_mm=0.2, x1_mm=35.0, y1_mm=42.0, x2_mm=30.0, y2_mm=35.0, net_index=4, net_name="CLK"),
        # GND trace on B.Cu
        PCBTrace(layer="B.Cu", width_mm=0.5, x1_mm=10.0, y1_mm=10.0, x2_mm=70.0, y2_mm=10.0, net_index=0, net_name="GND"),
        # Power trace
        PCBTrace(layer="F.Cu", width_mm=0.3, x1_mm=10.0, y1_mm=48.0, x2_mm=28.0, y2_mm=38.0, net_index=1, net_name="VCC3V3"),
    ]

    # Vias
    design.vias = [
        PCBVia(x_mm=25.0, y_mm=35.0, drill_mm=0.3, pad_diameter_mm=0.6, net_index=2, net_name="USB_D+"),
        PCBVia(x_mm=25.0, y_mm=37.0, drill_mm=0.3, pad_diameter_mm=0.6, net_index=3, net_name="USB_D-"),
        PCBVia(x_mm=15.0, y_mm=45.0, drill_mm=0.4, pad_diameter_mm=0.8, net_index=0, net_name="GND"),
        PCBVia(x_mm=40.0, y_mm=45.0, drill_mm=0.4, pad_diameter_mm=0.8, net_index=0, net_name="GND"),
        PCBVia(x_mm=60.0, y_mm=45.0, drill_mm=0.4, pad_diameter_mm=0.8, net_index=0, net_name="GND"),
    ]

    # Zones (ground fill on In1.Cu)
    design.zones = [
        PCBZone(
            layer="In1.Cu",
            net_name="GND",
            net_index=0,
            zone_type="fill",
            outline=[[0, 0], [80, 0], [80, 60], [0, 60]],
            area_mm2=4800.0,
        ),
    ]

    return design


# ---------------------------------------------------------------------------
# BoardRenderer tests
# ---------------------------------------------------------------------------

class TestBoardRenderer:
    """Tests for board_renderer.py."""

    def test_render_board_returns_valid_svg(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        renderer = BoardRenderer(design, width_px=800)
        svg = renderer.render_board()

        assert svg.startswith('<svg')
        assert svg.strip().endswith('</svg>')
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_render_board_contains_outline(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Should have a rect (board outline fallback) or polygon
        assert '<rect' in svg or '<polygon' in svg

    def test_render_board_contains_components(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Check several component ref-des labels
        assert 'U1' in svg
        assert 'R1' in svg
        assert 'J1' in svg
        assert 'C1' in svg

    def test_render_board_component_colour_coding(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # ICs should be blue (#4A90D9)
        assert '#4A90D9' in svg
        # Passives (R, C) should be green (#5CB85C)
        assert '#5CB85C' in svg
        # Connectors (J) should be orange (#E88D3F)
        assert '#E88D3F' in svg

    def test_render_board_contains_traces(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Should have line elements for traces
        assert '<line' in svg

    def test_render_board_contains_vias(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Vias are circles
        assert '<circle' in svg

    def test_render_board_contains_dimensions(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        assert '80.0 mm' in svg  # board width
        assert '60.0 mm' in svg  # board height

    def test_render_board_contains_scale_bar(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Scale bar should have a mm label
        assert 'mm</text>' in svg

    def test_render_board_with_net_highlight(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board(highlight_nets=["USB_D+"])
        # Highlighted net traces should be in highlight colour
        assert '#FF4136' in svg

    def test_render_board_with_component_highlight(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board(highlight_components=["U1", "J1"])
        # Highlighted components have stroke
        assert '#FF4136' in svg
        # Non-highlighted components have low opacity
        assert 'opacity="0.25"' in svg

    def test_render_board_with_layer_filter(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board(layers=["B.Cu"])
        # Layer title reference
        assert '<svg' in svg

    def test_render_board_custom_width(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        renderer = BoardRenderer(design, width_px=1200)
        svg = renderer.render_board()
        assert 'width="1200"' in svg

    def test_render_board_with_zones(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_board()
        # Zone outline polygon should exist
        assert 'stroke-dasharray' in svg


class TestBoardRendererNet:
    """Tests for net-specific rendering."""

    def test_render_net_valid(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_net("USB_D+")
        assert svg.startswith('<svg')
        assert 'USB_D+' in svg
        assert '#FF4136' in svg  # highlight colour

    def test_render_net_shows_stats(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_net("USB_D+")
        assert 'Traces:' in svg
        assert 'Vias:' in svg
        assert 'Length:' in svg

    def test_render_net_not_found_raises(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        renderer = BoardRenderer(design)
        try:
            renderer.render_net("NONEXISTENT_NET")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e)

    def test_render_net_dimmed_background(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_net("GND")
        # Background elements should be dimmed
        assert 'opacity="0.12"' in svg


class TestBoardRendererLayer:
    """Tests for layer-specific rendering."""

    def test_render_layer(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = make_mock_design()
        svg = BoardRenderer(design).render_layer("F.Cu")
        assert svg.startswith('<svg')
        assert 'Layer: F.Cu' in svg


# ---------------------------------------------------------------------------
# StackupRenderer tests
# ---------------------------------------------------------------------------

class TestStackupRenderer:
    """Tests for stackup_renderer.py."""

    def test_render_stackup_returns_valid_svg(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert svg.startswith('<svg')
        assert svg.strip().endswith('</svg>')

    def test_render_stackup_contains_layer_names(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'F.Cu' in svg
        assert 'In1.Cu' in svg
        assert 'In2.Cu' in svg
        assert 'B.Cu' in svg

    def test_render_stackup_contains_dielectric_layers(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'Prepreg1' in svg
        assert 'Core' in svg

    def test_render_stackup_contains_thicknesses(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert '0.035' in svg  # copper thickness
        assert '0.200' in svg  # prepreg thickness
        assert '1.000' in svg  # core thickness

    def test_render_stackup_contains_designations(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'SIGNAL' in svg
        assert 'PLANE' in svg
        assert 'DIELECTRIC' in svg

    def test_render_stackup_contains_title(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'Layer Stackup' in svg
        assert '4L' in svg

    def test_render_stackup_total_thickness(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert '1.60' in svg  # total board thickness

    def test_render_stackup_dielectric_constant(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'Er=4.3' in svg

    def test_render_stackup_no_layers_synthesizes(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = PCBDesignData(
            source_file="empty.kicad_pcb",
            board_width_mm=50.0,
            board_height_mm=50.0,
            layer_count=4,
            board_thickness_mm=1.6,
        )
        svg = StackupRenderer(design).render()
        assert svg.startswith('<svg')
        assert 'F.Cu' in svg
        assert 'B.Cu' in svg


# ---------------------------------------------------------------------------
# Annotator tests
# ---------------------------------------------------------------------------

class TestAnnotator:
    """Tests for annotator.py."""

    def test_render_annotations_returns_valid_svg(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "arrow", "x": 30.0, "y": 35.0, "text": "MCU"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert svg.startswith('<svg')
        assert svg.strip().endswith('</svg>')

    def test_render_arrow_annotation(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "arrow", "x": 30.0, "y": 35.0, "text": "Main IC"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert 'Main IC' in svg
        assert '<polygon' in svg  # arrowhead
        assert '<line' in svg     # arrow shaft

    def test_render_text_annotation(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "text", "x": 10.0, "y": 50.0, "text": "Power Section"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert 'Power Section' in svg
        # Background pill
        assert 'fill-opacity="0.7"' in svg

    def test_render_text_with_leader_line(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "text", "x": 10.0, "y": 55.0, "text": "LDO", "target_x": 15.0, "target_y": 50.0},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert 'LDO' in svg
        assert 'stroke-dasharray="3,2"' in svg  # leader line

    def test_render_highlight_rect(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "highlight", "x": 30.0, "y": 35.0, "width": 10.0, "height": 10.0, "color": "#00FF00"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert '#00FF00' in svg
        assert 'fill-opacity="0.15"' in svg

    def test_render_highlight_circle(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "highlight", "x": 30.0, "y": 35.0, "shape": "circle", "radius": 5.0},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert '<circle' in svg
        assert 'fill-opacity="0.2"' in svg

    def test_render_warning_marker(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "warning", "x": 40.0, "y": 30.0, "text": "Clearance violation", "severity": "warning"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert 'Clearance violation' in svg
        assert '#FFD700' in svg  # warning colour
        assert '!' in svg        # exclamation mark

    def test_render_error_marker(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "warning", "x": 40.0, "y": 30.0, "text": "DRC error", "severity": "error"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert '#FF4136' in svg  # error colour

    def test_render_multiple_annotations(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "arrow", "x": 30.0, "y": 35.0, "text": "MCU"},
            {"type": "text", "x": 10.0, "y": 50.0, "text": "Power"},
            {"type": "highlight", "x": 5.0, "y": 30.0, "width": 8.0, "height": 6.0},
            {"type": "warning", "x": 60.0, "y": 10.0, "text": "LED too close"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert 'MCU' in svg
        assert 'Power' in svg
        assert 'LED too close' in svg

    def test_render_annotated_board(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "arrow", "x": 30.0, "y": 35.0, "text": "U1 - STM32"},
            {"type": "warning", "x": 5.0, "y": 30.0, "text": "USB connector"},
        ]
        svg = Annotator(design).render_annotated_board(annotations)
        # Should be a single SVG with both board features and annotations
        assert svg.startswith('<svg')
        assert svg.strip().endswith('</svg>')
        # Board features present
        assert 'U1' in svg
        assert 'R1' in svg
        # Annotations present
        assert 'U1 - STM32' in svg
        assert 'USB connector' in svg
        # Annotation group
        assert 'id="annotations"' in svg

    def test_unknown_annotation_type_ignored(self):
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "nonexistent_type", "x": 10.0, "y": 10.0},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert svg.startswith('<svg')
        # Should not crash, just ignore


# ---------------------------------------------------------------------------
# Server dispatch integration tests
# ---------------------------------------------------------------------------

class TestServerDispatch:
    """Test visualization tools through server._dispatch."""

    def _create_session(self) -> tuple:
        """Create a session with mock design data."""
        from mcp_pcb_emcopilot.server import _dispatch, sessions
        design = make_mock_design()
        sid = sessions.create_session(design)
        return sid, _dispatch

    def test_pcb_render_board(self):
        sid, dispatch = self._create_session()
        result = dispatch("pcb_render_board", {"session_id": sid})
        assert result.get("success", True)
        svg = result["svg"]
        assert svg.startswith('<svg')
        assert 'U1' in svg
        assert result["width_px"] == 800

    def test_pcb_render_board_with_highlight(self):
        sid, dispatch = self._create_session()
        result = dispatch("pcb_render_board", {
            "session_id": sid,
            "highlight_nets": ["USB_D+"],
            "highlight_components": ["U1"],
            "width_px": 1000,
        })
        svg = result["svg"]
        assert 'width="1000"' in svg
        assert '#FF4136' in svg

    def test_pcb_render_stackup(self):
        sid, dispatch = self._create_session()
        result = dispatch("pcb_render_stackup", {"session_id": sid})
        assert result.get("success", True)
        svg = result["svg"]
        assert svg.startswith('<svg')
        assert 'F.Cu' in svg
        assert 'SIGNAL' in svg

    def test_pcb_render_net(self):
        sid, dispatch = self._create_session()
        result = dispatch("pcb_render_net", {"session_id": sid, "net_name": "USB_D+"})
        assert result.get("success", True)
        svg = result["svg"]
        assert 'USB_D+' in svg
        assert result["net_name"] == "USB_D+"

    def test_pcb_render_net_not_found(self):
        sid, dispatch = self._create_session()
        try:
            dispatch("pcb_render_net", {"session_id": sid, "net_name": "FAKE_NET"})
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_pcb_annotate_board(self):
        sid, dispatch = self._create_session()
        annotations = [
            {"type": "arrow", "x": 30.0, "y": 35.0, "text": "MCU"},
            {"type": "highlight", "x": 5.0, "y": 30.0, "shape": "circle", "radius": 4.0},
            {"type": "warning", "x": 60.0, "y": 10.0, "text": "Check LED", "severity": "error"},
        ]
        result = dispatch("pcb_annotate_board", {
            "session_id": sid,
            "annotations": annotations,
        })
        assert result.get("success", True)
        svg = result["svg"]
        assert svg.startswith('<svg')
        assert result["annotation_count"] == 3
        assert 'MCU' in svg
        assert 'Check LED' in svg
        assert 'id="annotations"' in svg

    def test_pcb_render_board_invalid_session(self):
        from mcp_pcb_emcopilot.errors import SessionError
        from mcp_pcb_emcopilot.server import _dispatch
        try:
            _dispatch("pcb_render_board", {"session_id": "nonexistent"})
            assert False, "Should have raised"
        except (ValueError, SessionError):
            pass


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_design(self):
        """Render a design with no components, traces, or vias."""
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = PCBDesignData(
            source_file="empty.kicad_pcb",
            board_width_mm=50.0,
            board_height_mm=30.0,
        )
        svg = BoardRenderer(design).render_board()
        assert svg.startswith('<svg')
        assert '50.0 mm' in svg

    def test_very_small_board(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = PCBDesignData(
            source_file="tiny.kicad_pcb",
            board_width_mm=5.0,
            board_height_mm=3.0,
        )
        svg = BoardRenderer(design, width_px=400).render_board()
        assert 'width="400"' in svg

    def test_very_large_board(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = PCBDesignData(
            source_file="large.kicad_pcb",
            board_width_mm=500.0,
            board_height_mm=400.0,
        )
        svg = BoardRenderer(design).render_board()
        assert svg.startswith('<svg')

    def test_zero_size_board_handled(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = PCBDesignData(
            source_file="zero.kicad_pcb",
            board_width_mm=0.0,
            board_height_mm=0.0,
        )
        svg = BoardRenderer(design).render_board()
        assert svg.startswith('<svg')

    def test_board_outline_from_vertices(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import BoardRenderer
        design = PCBDesignData(
            source_file="polygon.kicad_pcb",
            board_width_mm=80.0,
            board_height_mm=60.0,
            board_outline=[[0, 0], [80, 0], [80, 60], [0, 60]],
        )
        svg = BoardRenderer(design).render_board()
        assert '<polygon' in svg

    def test_stackup_with_copper_weight(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert '1 oz' in svg

    def test_stackup_with_material_label(self):
        from mcp_pcb_emcopilot.visualization.stackup_renderer import StackupRenderer
        design = make_mock_design()
        svg = StackupRenderer(design).render()
        assert 'FR-4' in svg

    def test_annotator_colour_alias(self):
        """Test that both 'color' and 'colour' keys work."""
        from mcp_pcb_emcopilot.visualization.annotator import Annotator
        design = make_mock_design()
        annotations = [
            {"type": "arrow", "x": 10.0, "y": 10.0, "colour": "#00FF00"},
        ]
        svg = Annotator(design).render_annotations(annotations)
        assert '#00FF00' in svg

    def test_package_size_estimation(self):
        from mcp_pcb_emcopilot.visualization.board_renderer import _estimate_package_size
        assert _estimate_package_size("0402")[0] < _estimate_package_size("0805")[0]
        assert _estimate_package_size("LQFP48")[0] > _estimate_package_size("0402")[0]
        assert _estimate_package_size("BGA256")[0] > _estimate_package_size("SOT-23")[0]
        assert _estimate_package_size("")[0] > 0  # default returns non-zero


# ---------------------------------------------------------------------------
# Run with pytest or standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
