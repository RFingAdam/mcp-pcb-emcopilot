"""Tests for STEP file parser, 3D clearance analysis, and enclosure fit check.

Tests STEP text parsing with inline mock STEP content, component extraction,
clearance calculation, enclosure fit check, and dispatch through server.py.
"""

import json
import math
import os
import sys
import tempfile

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
from mcp_pcb_emcopilot.parsers.step_parser import (
    STEPParser,
    check_enclosure_fit,
    compute_3d_clearances,
)

# =============================================================================
# Mock STEP content — minimal but realistic EDA export structure
# =============================================================================

MOCK_STEP_CONTENT = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('PCB Assembly'),'2;1');
FILE_NAME('test_pcb.step','2026-03-01',('Test'),('Test'),'','KiCad','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));
ENDSEC;
DATA;
#1 = APPLICATION_CONTEXT('automotive design');
#2 = APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2010,#1);

/* Board product */
#10 = PRODUCT('PCB','Main Board','',($));
#11 = PRODUCT_DEFINITION_FORMATION('','',#10);
#12 = PRODUCT_DEFINITION('design','',#11,#13);
#13 = PRODUCT_DEFINITION_CONTEXT('detail design',#1,'design');

/* Board shape */
#20 = PRODUCT_DEFINITION_SHAPE('','',#12);
#21 = SHAPE_DEFINITION_REPRESENTATION(#20,#22);
#22 = ADVANCED_BREP_SHAPE_REPRESENTATION('PCB_Shape',(#30),#100);

/* Board body — CLOSED_SHELL with 6 faces for 100x80x1.6mm board */
#30 = CLOSED_SHELL('Board_Body',(#31,#32,#33,#34,#35,#36));
#31 = ADVANCED_FACE('',(#60),.F.);
#32 = ADVANCED_FACE('',(#61),.F.);
#33 = ADVANCED_FACE('',(#62),.F.);
#34 = ADVANCED_FACE('',(#63),.F.);
#35 = ADVANCED_FACE('',(#64),.F.);
#36 = ADVANCED_FACE('',(#65),.F.);

/* Board corner points (100mm x 80mm x 1.6mm) */
#40 = CARTESIAN_POINT('',( 0.0, 0.0, 0.0));
#41 = CARTESIAN_POINT('',(100.0, 0.0, 0.0));
#42 = CARTESIAN_POINT('',(100.0, 80.0, 0.0));
#43 = CARTESIAN_POINT('',( 0.0, 80.0, 0.0));
#44 = CARTESIAN_POINT('',( 0.0, 0.0, 1.6));
#45 = CARTESIAN_POINT('',(100.0, 0.0, 1.6));
#46 = CARTESIAN_POINT('',(100.0, 80.0, 1.6));
#47 = CARTESIAN_POINT('',( 0.0, 80.0, 1.6));

/* Wire the points into the closed shell via vertex points and edges */
#50 = VERTEX_POINT('',#40);
#51 = VERTEX_POINT('',#41);
#52 = VERTEX_POINT('',#42);
#53 = VERTEX_POINT('',#43);
#54 = VERTEX_POINT('',#44);
#55 = VERTEX_POINT('',#45);
#56 = VERTEX_POINT('',#46);
#57 = VERTEX_POINT('',#47);

/* Bottom face edges */
#60 = EDGE_LOOP('',(#50,#51,#52,#53));
/* Top face edges */
#61 = EDGE_LOOP('',(#54,#55,#56,#57));
/* Side face edges */
#62 = EDGE_LOOP('',(#50,#51,#55,#54));
#63 = EDGE_LOOP('',(#51,#52,#56,#55));
#64 = EDGE_LOOP('',(#52,#53,#57,#56));
#65 = EDGE_LOOP('',(#53,#50,#54,#57));

#90 = DIRECTION('',(1.0,0.0,0.0));
#91 = DIRECTION('',(0.0,1.0,0.0));
#92 = DIRECTION('',(-1.0,0.0,0.0));
#93 = DIRECTION('',(0.0,-1.0,0.0));

/* Geometry context */
#100 = ( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#101)) GLOBAL_UNIT_ASSIGNED_CONTEXT((#102,#103,#104)) REPRESENTATION_CONTEXT('Context3D','3D Context') );
#101 = UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#102,'distance_accuracy_value','');
#102 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
#103 = ( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) );
#104 = ( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() );

/* Component 1: R1 — Resistor at (10, 15, 1.6) with small body */
#200 = PRODUCT('R1','Resistor 0402','',($));
#201 = PRODUCT_DEFINITION_FORMATION('','',#200);
#202 = PRODUCT_DEFINITION('design','',#201,#13);
#203 = PRODUCT_DEFINITION_SHAPE('','',#202);
#204 = SHAPE_DEFINITION_REPRESENTATION(#203,#205);
#205 = ADVANCED_BREP_SHAPE_REPRESENTATION('R1_Shape',(#210),#100);
#210 = CLOSED_SHELL('R1_Body',(#211));
#211 = ADVANCED_FACE('',(),.F.);

/* R1 body points — 1.0mm x 0.5mm x 0.35mm */
#220 = CARTESIAN_POINT('',(9.5, 14.75, 1.6));
#221 = CARTESIAN_POINT('',(10.5, 14.75, 1.6));
#222 = CARTESIAN_POINT('',(10.5, 15.25, 1.6));
#223 = CARTESIAN_POINT('',(9.5, 15.25, 1.6));
#224 = CARTESIAN_POINT('',(9.5, 14.75, 1.95));
#225 = CARTESIAN_POINT('',(10.5, 14.75, 1.95));
#226 = CARTESIAN_POINT('',(10.5, 15.25, 1.95));
#227 = CARTESIAN_POINT('',(9.5, 15.25, 1.95));

/* Component 2: U1 — IC at (50, 40, 1.6) with taller body */
#300 = PRODUCT('U1','Microcontroller QFP48','',($));
#301 = PRODUCT_DEFINITION_FORMATION('','',#300);
#302 = PRODUCT_DEFINITION('design','',#301,#13);
#303 = PRODUCT_DEFINITION_SHAPE('','',#302);
#304 = SHAPE_DEFINITION_REPRESENTATION(#303,#305);
#305 = ADVANCED_BREP_SHAPE_REPRESENTATION('U1_Shape',(#310),#100);
#310 = CLOSED_SHELL('U1_Body',(#311));
#311 = ADVANCED_FACE('',(),.F.);

/* U1 body points — 7.0mm x 7.0mm x 1.4mm */
#320 = CARTESIAN_POINT('',(46.5, 36.5, 1.6));
#321 = CARTESIAN_POINT('',(53.5, 36.5, 1.6));
#322 = CARTESIAN_POINT('',(53.5, 43.5, 1.6));
#323 = CARTESIAN_POINT('',(46.5, 43.5, 1.6));
#324 = CARTESIAN_POINT('',(46.5, 36.5, 3.0));
#325 = CARTESIAN_POINT('',(53.5, 36.5, 3.0));
#326 = CARTESIAN_POINT('',(53.5, 43.5, 3.0));
#327 = CARTESIAN_POINT('',(46.5, 43.5, 3.0));

/* Component 3: J1 — Connector at (95, 40, 1.6) protruding above board */
#400 = PRODUCT('J1','USB-C Connector','',($));
#401 = PRODUCT_DEFINITION_FORMATION('','',#400);
#402 = PRODUCT_DEFINITION('design','',#401,#13);
#403 = PRODUCT_DEFINITION_SHAPE('','',#402);
#404 = SHAPE_DEFINITION_REPRESENTATION(#403,#405);
#405 = ADVANCED_BREP_SHAPE_REPRESENTATION('J1_Shape',(#410),#100);
#410 = CLOSED_SHELL('J1_Body',(#411));
#411 = ADVANCED_FACE('',(),.F.);

/* J1 body points — 9.0mm x 7.5mm x 3.2mm (tall connector) */
#420 = CARTESIAN_POINT('',(90.5, 36.25, 1.6));
#421 = CARTESIAN_POINT('',(99.5, 36.25, 1.6));
#422 = CARTESIAN_POINT('',(99.5, 43.75, 1.6));
#423 = CARTESIAN_POINT('',(90.5, 43.75, 1.6));
#424 = CARTESIAN_POINT('',(90.5, 36.25, 4.8));
#425 = CARTESIAN_POINT('',(99.5, 36.25, 4.8));
#426 = CARTESIAN_POINT('',(99.5, 43.75, 4.8));
#427 = CARTESIAN_POINT('',(90.5, 43.75, 4.8));

/* Component 4: C1 — Capacitor near edge */
#500 = PRODUCT('C1','Cap 100nF 0603','',($));
#501 = PRODUCT_DEFINITION_FORMATION('','',#500);
#502 = PRODUCT_DEFINITION('design','',#501,#13);
#503 = PRODUCT_DEFINITION_SHAPE('','',#502);
#504 = SHAPE_DEFINITION_REPRESENTATION(#503,#505);
#505 = ADVANCED_BREP_SHAPE_REPRESENTATION('C1_Shape',(#510),#100);
#510 = CLOSED_SHELL('C1_Body',(#511));
#511 = ADVANCED_FACE('',(),.F.);

/* C1 body points — 1.6mm x 0.8mm x 0.45mm, near left edge */
#520 = CARTESIAN_POINT('',(0.5, 40.0, 1.6));
#521 = CARTESIAN_POINT('',(2.1, 40.0, 1.6));
#522 = CARTESIAN_POINT('',(2.1, 40.8, 1.6));
#523 = CARTESIAN_POINT('',(0.5, 40.8, 1.6));
#524 = CARTESIAN_POINT('',(0.5, 40.0, 2.05));
#525 = CARTESIAN_POINT('',(2.1, 40.0, 2.05));
#526 = CARTESIAN_POINT('',(2.1, 40.8, 2.05));
#527 = CARTESIAN_POINT('',(0.5, 40.8, 2.05));

ENDSEC;
END-ISO-10303-21;
"""


# =============================================================================
# Test: STEP entity parsing
# =============================================================================

def test_step_entity_parsing():
    """Test that STEP entities are correctly parsed from text."""
    parser = STEPParser()
    result = parser.parse_content(MOCK_STEP_CONTENT)

    # Should find entities
    assert len(parser.entities) > 0, "No entities parsed"

    # Should find PRODUCT entities
    product_types = [e for e in parser.entities.values() if e.type_name == "PRODUCT"]
    assert len(product_types) >= 4, f"Expected >= 4 PRODUCTs, got {len(product_types)}"

    # Should find CARTESIAN_POINTs
    cp_types = [e for e in parser.entities.values() if e.type_name == "CARTESIAN_POINT"]
    assert len(cp_types) >= 30, f"Expected >= 30 CARTESIAN_POINTs, got {len(cp_types)}"

    # Should find CLOSED_SHELL entities
    cs_types = [e for e in parser.entities.values() if e.type_name == "CLOSED_SHELL"]
    assert len(cs_types) >= 5, f"Expected >= 5 CLOSED_SHELLs, got {len(cs_types)}"

    print(f"  Parsed {len(parser.entities)} entities")
    print(f"  {len(product_types)} PRODUCTs, {len(cp_types)} CARTESIAN_POINTs, {len(cs_types)} CLOSED_SHELLs")


def test_cartesian_point_extraction():
    """Test that cartesian points are correctly extracted."""
    parser = STEPParser()
    parser.parse_content(MOCK_STEP_CONTENT)

    # Check board corner point #40 = (0, 0, 0)
    assert 40 in parser._cartesian_points, "Point #40 not found"
    pt = parser._cartesian_points[40]
    assert pt == (0.0, 0.0, 0.0), f"Point #40 expected (0,0,0), got {pt}"

    # Check board corner point #46 = (100, 80, 1.6)
    assert 46 in parser._cartesian_points
    pt = parser._cartesian_points[46]
    assert abs(pt[0] - 100.0) < 0.001
    assert abs(pt[1] - 80.0) < 0.001
    assert abs(pt[2] - 1.6) < 0.001

    # Check U1 corner point #320 = (46.5, 36.5, 1.6)
    assert 320 in parser._cartesian_points
    pt = parser._cartesian_points[320]
    assert abs(pt[0] - 46.5) < 0.001

    print(f"  Extracted {len(parser._cartesian_points)} cartesian points")


def test_param_parsing():
    """Test STEP parameter list parsing."""
    parser = STEPParser()

    # String params
    params = parser._parse_param_list("'R1','Resistor 0402','',($)")
    assert params[0] == "R1"
    assert params[1] == "Resistor 0402"
    assert params[2] == ""

    # Numeric params in tuple
    params = parser._parse_param_list("'',(100.0, 80.0, 1.6)")
    assert params[0] == ""
    assert isinstance(params[1], list)
    assert abs(params[1][0] - 100.0) < 0.001
    assert abs(params[1][1] - 80.0) < 0.001
    assert abs(params[1][2] - 1.6) < 0.001

    # Entity references
    params = parser._parse_param_list("'test',#123,#456")
    assert params[0] == "test"
    assert params[1] == 123
    assert params[2] == 456

    # Special tokens
    params = parser._parse_param_list("$,*,.TRUE.")
    assert params[0] is None
    assert params[1] == '*'
    assert params[2] == "TRUE"

    print("  Parameter parsing OK")


# =============================================================================
# Test: Component extraction
# =============================================================================

def test_component_extraction():
    """Test that components are extracted from STEP products."""
    parser = STEPParser()
    result = parser.parse_content(MOCK_STEP_CONTENT)
    components = result["step_components"]

    # Should find R1, U1, J1, C1 (not PCB — that's the board)
    refs = {c["reference"] for c in components}
    assert "R1" in refs, f"R1 not found in components: {refs}"
    assert "U1" in refs, f"U1 not found in components: {refs}"
    assert "J1" in refs, f"J1 not found in components: {refs}"
    assert "C1" in refs, f"C1 not found in components: {refs}"
    assert "PCB" not in refs, "PCB should not be a component"

    print(f"  Found {len(components)} components: {refs}")


def test_component_has_required_fields():
    """Test that extracted components have all required fields."""
    parser = STEPParser()
    result = parser.parse_content(MOCK_STEP_CONTENT)
    components = result["step_components"]

    required_fields = {"reference", "x", "y", "z", "width", "depth", "height"}
    for comp in components:
        for field in required_fields:
            assert field in comp, f"Component {comp.get('reference', '?')} missing field '{field}'"

    print("  All components have required fields")


def test_refdes_detection():
    """Test reference designator detection."""
    parser = STEPParser()

    # Valid ref des
    assert parser._is_refdes("R1") is True
    assert parser._is_refdes("C23") is True
    assert parser._is_refdes("U5") is True
    assert parser._is_refdes("J1") is True
    assert parser._is_refdes("FB2") is True
    assert parser._is_refdes("LED3") is True
    assert parser._is_refdes("SW1") is True

    # Not ref des
    assert parser._is_refdes("PCB") is False
    assert parser._is_refdes("Main Board") is False
    assert parser._is_refdes("") is False
    assert parser._is_refdes("Resistor") is False

    print("  Reference designator detection OK")


# =============================================================================
# Test: Board dimensions
# =============================================================================

def test_board_dimensions():
    """Test board outline extraction from STEP data."""
    parser = STEPParser()
    result = parser.parse_content(MOCK_STEP_CONTENT)
    board_3d = result["board_3d"]

    # Board should be ~100mm x 80mm x 1.6mm
    assert abs(board_3d["width"] - 100.0) < 0.1, f"Board width: {board_3d['width']}"
    assert abs(board_3d["depth"] - 80.0) < 0.1, f"Board depth: {board_3d['depth']}"
    assert abs(board_3d["thickness"] - 1.6) < 0.1, f"Board thickness: {board_3d['thickness']}"

    # Bounding box should be present
    bbox = board_3d["bounding_box"]
    assert "min_x" in bbox
    assert "max_x" in bbox
    assert abs(bbox["min_x"] - 0.0) < 0.1
    assert abs(bbox["max_x"] - 100.0) < 0.1

    print(f"  Board: {board_3d['width']}mm x {board_3d['depth']}mm x {board_3d['thickness']}mm")


# =============================================================================
# Test: Clearance calculation
# =============================================================================

def test_clearance_calculation():
    """Test 3D clearance computation between components and board edges."""
    board_3d = {
        "width": 100.0,
        "depth": 80.0,
        "thickness": 1.6,
        "bounding_box": {
            "min_x": 0.0, "min_y": 0.0, "min_z": 0.0,
            "max_x": 100.0, "max_y": 80.0, "max_z": 1.6,
        },
    }

    components = [
        {"reference": "R1", "x": 10.0, "y": 15.0, "z": 1.6, "width": 1.0, "depth": 0.5, "height": 0.35},
        {"reference": "U1", "x": 50.0, "y": 40.0, "z": 1.6, "width": 7.0, "depth": 7.0, "height": 1.4},
        {"reference": "J1", "x": 95.0, "y": 40.0, "z": 1.6, "width": 9.0, "depth": 7.5, "height": 3.2},
    ]

    result = compute_3d_clearances(board_3d, components)

    # Should have component-to-component clearances
    assert len(result["component_clearances"]) == 3  # 3 pairs from 3 components
    assert result["component_count"] == 3

    # R1 to U1 distance should be ~45mm (center-to-center)
    r1_u1 = next(c for c in result["component_clearances"]
                  if c["component_1"] == "R1" and c["component_2"] == "U1")
    assert r1_u1["center_distance_mm"] > 40

    # Should have edge clearances for each component
    assert len(result["edge_clearances"]) == 3

    # J1 should be close to the right edge
    j1_edge = next(c for c in result["edge_clearances"] if c["component"] == "J1")
    assert j1_edge["right_mm"] < 10, f"J1 right edge clearance should be small: {j1_edge['right_mm']}"

    print(f"  {len(result['component_clearances'])} component clearances")
    print(f"  {len(result['edge_clearances'])} edge clearances")
    print(f"  {len(result['issues'])} issues found")


def test_clearance_tight_spacing():
    """Test that tight clearances generate appropriate warnings."""
    board_3d = {
        "width": 50.0, "depth": 50.0, "thickness": 1.6,
        "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 50, "max_y": 50, "max_z": 1.6},
    }

    # Two components very close together
    components = [
        {"reference": "U1", "x": 25.0, "y": 25.0, "z": 1.6, "width": 10.0, "depth": 10.0, "height": 2.0},
        {"reference": "U2", "x": 30.0, "y": 25.0, "z": 1.6, "width": 10.0, "depth": 10.0, "height": 2.0},
    ]

    result = compute_3d_clearances(board_3d, components)

    # Should flag tight clearance or overlap
    assert len(result["issues"]) > 0, "Should flag tight spacing between U1 and U2"
    print(f"  Issues: {result['issues']}")


# =============================================================================
# Test: Enclosure fit check
# =============================================================================

def test_enclosure_fit_passes():
    """Test enclosure fit check — board fits in large enclosure."""
    board_3d = {
        "width": 100.0, "depth": 80.0, "thickness": 1.6,
        "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 100, "max_y": 80, "max_z": 1.6},
    }
    components = [
        {"reference": "U1", "x": 50.0, "y": 40.0, "z": 1.6, "width": 7.0, "depth": 7.0, "height": 3.0},
    ]

    result = check_enclosure_fit(
        board_3d=board_3d,
        step_components=components,
        enclosure_width_mm=150.0,
        enclosure_depth_mm=120.0,
        enclosure_height_mm=20.0,
        clearance_mm=2.0,
    )

    assert result["fits"] is True, f"Should fit: {result['issues']}"
    assert result["margins"]["width_mm"] > 0
    assert result["margins"]["depth_mm"] > 0
    assert result["margins"]["height_mm"] > 0
    assert result["assembly_height_mm"] > board_3d["thickness"]

    print(f"  Fits: {result['fits']}")
    print(f"  Assembly height: {result['assembly_height_mm']}mm")
    print(f"  Margins: W={result['margins']['width_mm']}mm, "
          f"D={result['margins']['depth_mm']}mm, H={result['margins']['height_mm']}mm")


def test_enclosure_fit_fails_width():
    """Test enclosure fit check — board too wide."""
    board_3d = {
        "width": 100.0, "depth": 80.0, "thickness": 1.6,
        "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 100, "max_y": 80, "max_z": 1.6},
    }

    result = check_enclosure_fit(
        board_3d=board_3d,
        step_components=[],
        enclosure_width_mm=90.0,  # Too narrow!
        enclosure_depth_mm=120.0,
        enclosure_height_mm=20.0,
        clearance_mm=1.0,
    )

    assert result["fits"] is False
    assert result["margins"]["width_mm"] < 0
    assert any("wide" in i.lower() for i in result["issues"])

    print(f"  Fits: {result['fits']} (expected False)")
    print(f"  Issues: {result['issues']}")


def test_enclosure_fit_fails_height():
    """Test enclosure fit check — assembly too tall."""
    board_3d = {
        "width": 100.0, "depth": 80.0, "thickness": 1.6,
        "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 100, "max_y": 80, "max_z": 1.6},
    }
    components = [
        {"reference": "J1", "x": 95.0, "y": 40.0, "z": 1.6, "width": 9.0, "depth": 7.5, "height": 15.0},
    ]

    result = check_enclosure_fit(
        board_3d=board_3d,
        step_components=components,
        enclosure_width_mm=150.0,
        enclosure_depth_mm=120.0,
        enclosure_height_mm=10.0,  # Too short for 15mm connector
        clearance_mm=1.0,
    )

    assert result["fits"] is False
    assert result["margins"]["height_mm"] < 0
    assert result["tallest_component_above"] == "J1"

    print(f"  Fits: {result['fits']} (expected False)")
    print(f"  Tallest above: {result['tallest_component_above']}")


# =============================================================================
# Test: Parse from file
# =============================================================================

def test_parse_step_file():
    """Test parsing STEP content from a file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.step', delete=False) as f:
        f.write(MOCK_STEP_CONTENT)
        tmp_path = f.name

    try:
        parser = STEPParser()
        result = parser.parse_file(tmp_path)

        assert "board_3d" in result
        assert "step_components" in result
        assert result["board_3d"]["width"] > 0
        print(f"  Parsed from file: {len(result['step_components'])} components")
    finally:
        os.unlink(tmp_path)


def test_parse_step_file_not_found():
    """Test that missing file raises FileNotFoundError."""
    parser = STEPParser()
    try:
        parser.parse_file("/nonexistent/path/board.step")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        print("  FileNotFoundError raised correctly")


# =============================================================================
# Test: Parser dispatch integration
# =============================================================================

def test_format_detection():
    """Test that STEP format is detected from file extension."""
    from mcp_pcb_emcopilot.parsers import detect_format

    assert detect_format("board.step") == "step"
    assert detect_format("board.stp") == "step"
    assert detect_format("BOARD.STEP") == "step"
    assert detect_format("path/to/assembly.STP") == "step"
    print("  Format detection OK for .step and .stp")


def test_parse_pcb_file_step():
    """Test STEP file through the parse_pcb_file dispatcher."""
    from mcp_pcb_emcopilot.parsers import parse_pcb_file

    with tempfile.NamedTemporaryFile(mode='w', suffix='.step', delete=False) as f:
        f.write(MOCK_STEP_CONTENT)
        tmp_path = f.name

    try:
        data = parse_pcb_file(tmp_path)

        assert data.source_format == "step"
        assert data.board_width_mm > 0
        assert data.board_height_mm > 0
        assert len(data.step_components) > 0
        assert len(data.board_3d) > 0

        # Standard components should also be populated
        assert len(data.components) > 0
        refs = {c.reference for c in data.components}
        assert "R1" in refs or "U1" in refs

        print(f"  Dispatched parse: {data.source_format}, "
              f"{data.board_width_mm}x{data.board_height_mm}mm, "
              f"{len(data.components)} components")
    finally:
        os.unlink(tmp_path)


# =============================================================================
# Test: Server dispatch integration
# =============================================================================

def test_server_dispatch_parse_step():
    """Test pcb_parse_step through server._dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    with tempfile.NamedTemporaryFile(mode='w', suffix='.step', delete=False) as f:
        f.write(MOCK_STEP_CONTENT)
        tmp_path = f.name

    try:
        result = _dispatch("pcb_parse_step", {"file_path": tmp_path})

        assert result["success"] is True
        assert "session_id" in result
        assert result["component_count"] > 0
        assert result["board_3d"]["width"] > 0

        sid = result["session_id"]

        # Verify session was created
        session_data = sessions.get_session(sid)
        assert session_data is not None
        assert len(session_data.step_components) > 0

        # Clean up
        sessions.close_session(sid)
        print(f"  Server dispatch pcb_parse_step: session={sid}, "
              f"{result['component_count']} components")
    finally:
        os.unlink(tmp_path)


def test_server_dispatch_get_3d_clearances():
    """Test pcb_get_3d_clearances through server._dispatch."""
    from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    # Create a session with 3D data
    data = PCBDesignData(
        source_file="test.step",
        source_format="step",
        board_width_mm=100.0,
        board_height_mm=80.0,
        board_3d={
            "width": 100.0, "depth": 80.0, "thickness": 1.6,
            "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0,
                             "max_x": 100, "max_y": 80, "max_z": 1.6},
        },
        step_components=[
            {"reference": "R1", "x": 10.0, "y": 15.0, "z": 1.6,
             "width": 1.0, "depth": 0.5, "height": 0.35},
            {"reference": "U1", "x": 50.0, "y": 40.0, "z": 1.6,
             "width": 7.0, "depth": 7.0, "height": 1.4},
        ],
    )
    sid = sessions.create_session(data)

    try:
        result = _dispatch("pcb_get_3d_clearances", {"session_id": sid})

        assert "component_clearances" in result
        assert "edge_clearances" in result
        assert result["component_count"] == 2

        print(f"  Server dispatch pcb_get_3d_clearances: "
              f"{len(result['component_clearances'])} clearances, "
              f"{len(result['issues'])} issues")
    finally:
        sessions.close_session(sid)


def test_server_dispatch_check_enclosure_fit():
    """Test pcb_check_enclosure_fit through server._dispatch."""
    from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    data = PCBDesignData(
        source_file="test.step",
        source_format="step",
        board_width_mm=100.0,
        board_height_mm=80.0,
        board_3d={
            "width": 100.0, "depth": 80.0, "thickness": 1.6,
            "bounding_box": {"min_x": 0, "min_y": 0, "min_z": 0,
                             "max_x": 100, "max_y": 80, "max_z": 1.6},
        },
        step_components=[
            {"reference": "J1", "x": 95.0, "y": 40.0, "z": 1.6,
             "width": 9.0, "depth": 7.5, "height": 3.2},
        ],
    )
    sid = sessions.create_session(data)

    try:
        # Should fit in large enclosure
        result = _dispatch("pcb_check_enclosure_fit", {
            "session_id": sid,
            "enclosure_width_mm": 150.0,
            "enclosure_depth_mm": 120.0,
            "enclosure_height_mm": 20.0,
            "clearance_mm": 2.0,
        })

        assert result["fits"] is True
        assert result["tallest_component_above"] == "J1"

        # Should not fit in tiny enclosure
        result2 = _dispatch("pcb_check_enclosure_fit", {
            "session_id": sid,
            "enclosure_width_mm": 50.0,
            "enclosure_depth_mm": 50.0,
            "enclosure_height_mm": 3.0,
            "clearance_mm": 1.0,
        })

        assert result2["fits"] is False
        assert len(result2["issues"]) > 0

        print(f"  Server dispatch pcb_check_enclosure_fit: "
              f"large={result['fits']}, small={result2['fits']}")
    finally:
        sessions.close_session(sid)


def test_server_dispatch_no_3d_data_error():
    """Test that 3D tools fail gracefully when no STEP data is present."""
    from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    # Session without 3D data
    data = PCBDesignData(source_file="test.kicad_pcb", source_format="kicad")
    sid = sessions.create_session(data)

    try:
        try:
            _dispatch("pcb_get_3d_clearances", {"session_id": sid})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "STEP" in str(e) or "3D" in str(e)
            print(f"  Correct error for missing 3D data: {e}")

        try:
            _dispatch("pcb_check_enclosure_fit", {
                "session_id": sid,
                "enclosure_width_mm": 100,
                "enclosure_depth_mm": 100,
                "enclosure_height_mm": 20,
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "STEP" in str(e) or "3D" in str(e)
            print(f"  Correct error for missing 3D data: {e}")
    finally:
        sessions.close_session(sid)


def test_server_merge_step_into_existing_session():
    """Test merging STEP data into an existing session."""
    from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    # Create a KiCad-like session first
    data = PCBDesignData(
        source_file="test.kicad_pcb",
        source_format="kicad",
        board_width_mm=100.0,
        board_height_mm=80.0,
    )
    sid = sessions.create_session(data)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.step', delete=False) as f:
        f.write(MOCK_STEP_CONTENT)
        tmp_path = f.name

    try:
        # Merge STEP data into existing session
        result = _dispatch("pcb_parse_step", {
            "file_path": tmp_path,
            "session_id": sid,
        })

        assert result["session_id"] == sid
        assert result["component_count"] > 0

        # Verify 3D data was merged
        session_data = sessions.get_session(sid)
        assert len(session_data.step_components) > 0
        assert len(session_data.board_3d) > 0

        print(f"  Merged STEP into existing session {sid}: "
              f"{len(session_data.step_components)} 3D components")
    finally:
        sessions.close_session(sid)
        os.unlink(tmp_path)


# =============================================================================
# Test: PCBDesignData model changes
# =============================================================================

def test_pcb_design_data_new_fields():
    """Test that PCBDesignData has the new step_components and board_3d fields."""
    data = PCBDesignData(source_file="test.step")

    # New fields should exist and default to empty
    assert hasattr(data, 'step_components')
    assert hasattr(data, 'board_3d')
    assert data.step_components == []
    assert data.board_3d == {}

    # Should be assignable
    data.step_components = [{"reference": "R1", "x": 0, "y": 0, "z": 0, "width": 1, "depth": 1, "height": 1}]
    data.board_3d = {"width": 100, "depth": 80, "thickness": 1.6}
    assert len(data.step_components) == 1
    assert data.board_3d["width"] == 100

    print("  PCBDesignData new fields OK")


# =============================================================================
# Test: Edge cases
# =============================================================================

def test_empty_step_file():
    """Test parsing an empty/minimal STEP file."""
    content = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('empty'),'2;1');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""
    parser = STEPParser()
    result = parser.parse_content(content)

    assert result["step_components"] == []
    assert result["board_3d"]["width"] == 0
    print("  Empty STEP file handled gracefully")


def test_step_with_no_data_section():
    """Test parsing STEP content with no DATA section."""
    content = "ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;"
    parser = STEPParser()
    result = parser.parse_content(content)

    assert result["step_components"] == []
    assert len(result["warnings"]) > 0
    print("  No DATA section handled with warning")


def test_multiline_entity():
    """Test parsing entities that span multiple lines."""
    content = """\
ISO-10303-21;
HEADER;
ENDSEC;
DATA;
#1 = CARTESIAN_POINT('origin',
    (0.0,
     0.0,
     0.0));
#2 = PRODUCT('R1',
    'Resistor',
    '',
    ($));
ENDSEC;
END-ISO-10303-21;
"""
    parser = STEPParser()
    result = parser.parse_content(content)

    assert 1 in parser._cartesian_points
    assert parser._cartesian_points[1] == (0.0, 0.0, 0.0)

    components = result["step_components"]
    refs = {c["reference"] for c in components}
    assert "R1" in refs

    print("  Multi-line entity parsing OK")


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    tests = [
        test_step_entity_parsing,
        test_cartesian_point_extraction,
        test_param_parsing,
        test_component_extraction,
        test_component_has_required_fields,
        test_refdes_detection,
        test_board_dimensions,
        test_clearance_calculation,
        test_clearance_tight_spacing,
        test_enclosure_fit_passes,
        test_enclosure_fit_fails_width,
        test_enclosure_fit_fails_height,
        test_parse_step_file,
        test_parse_step_file_not_found,
        test_format_detection,
        test_parse_pcb_file_step,
        test_server_dispatch_parse_step,
        test_server_dispatch_get_3d_clearances,
        test_server_dispatch_check_enclosure_fit,
        test_server_dispatch_no_3d_data_error,
        test_server_merge_step_into_existing_session,
        test_pcb_design_data_new_fields,
        test_empty_step_file,
        test_step_with_no_data_section,
        test_multiline_entity,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            print(f"\n{test.__name__}:")
            test()
            passed += 1
            print("  PASSED")
        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)
    print("All tests passed!")
