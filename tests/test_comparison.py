"""Tests for design revision comparison module."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from mcp_pcb_emcopilot.analyzers.comparison import (
    ComponentChange,
    DesignComparator,
    DesignComparison,
    NetChange,
)


def _make_comp(ref_des, x=0, y=0, value="", package="", rotation=0):
    return SimpleNamespace(
        ref_des=ref_des, reference=ref_des,
        x_mm=x, y_mm=y, x=x, y=y,
        value=value, package=package, rotation=rotation,
    )


def _make_net(name):
    return SimpleNamespace(name=name, net_name=name)


def _make_design(
    source_file="test.kicad_pcb",
    board_width_mm=50.0,
    board_height_mm=40.0,
    layer_count=2,
    components=None,
    nets=None,
):
    return SimpleNamespace(
        source_file=source_file,
        board_width_mm=board_width_mm,
        board_height_mm=board_height_mm,
        layer_count=layer_count,
        components=components or [],
        nets=nets or [],
    )


class TestIdenticalDesigns:
    def test_no_changes(self):
        comps = [_make_comp("U1", 10, 10, "STM32"), _make_comp("R1", 20, 20, "10k")]
        nets = [_make_net("GND"), _make_net("VCC")]
        a = _make_design(components=comps, nets=nets)
        b = _make_design(components=comps, nets=nets)
        result = DesignComparator().compare(a, b)
        assert result.total_changes == 0
        assert not result.board_size_changed
        assert not result.layer_count_changed

    def test_summary_says_no_changes(self):
        a = _make_design()
        result = DesignComparator().compare(a, a)
        assert "No significant changes" in result.summary


class TestBoardChanges:
    def test_board_size_changed(self):
        a = _make_design(board_width_mm=50, board_height_mm=40)
        b = _make_design(board_width_mm=60, board_height_mm=45)
        result = DesignComparator().compare(a, b)
        assert result.board_size_changed
        assert result.old_dimensions == (50, 40)
        assert result.new_dimensions == (60, 45)

    def test_board_size_unchanged_within_tolerance(self):
        a = _make_design(board_width_mm=50.0)
        b = _make_design(board_width_mm=50.005)
        result = DesignComparator().compare(a, b)
        assert not result.board_size_changed

    def test_layer_count_changed(self):
        a = _make_design(layer_count=2)
        b = _make_design(layer_count=4)
        result = DesignComparator().compare(a, b)
        assert result.layer_count_changed
        assert result.old_layer_count == 2
        assert result.new_layer_count == 4

    def test_layer_count_unchanged(self):
        result = DesignComparator().compare(_make_design(layer_count=4), _make_design(layer_count=4))
        assert not result.layer_count_changed


class TestComponentChanges:
    def test_component_added(self):
        a = _make_design(components=[_make_comp("U1")])
        b = _make_design(components=[_make_comp("U1"), _make_comp("R1", value="10k")])
        result = DesignComparator().compare(a, b)
        assert result.components_added == 1
        added = [c for c in result.component_changes if c.change_type == "added"]
        assert added[0].ref_des == "R1"

    def test_component_removed(self):
        a = _make_design(components=[_make_comp("U1"), _make_comp("C1")])
        b = _make_design(components=[_make_comp("U1")])
        result = DesignComparator().compare(a, b)
        assert result.components_removed == 1

    def test_component_moved(self):
        a = _make_design(components=[_make_comp("U1", x=10, y=10)])
        b = _make_design(components=[_make_comp("U1", x=15, y=10)])
        result = DesignComparator().compare(a, b)
        assert result.components_moved == 1
        moved = [c for c in result.component_changes if c.change_type == "moved"]
        assert "5.00mm" in moved[0].detail

    def test_component_not_moved_below_threshold(self):
        a = _make_design(components=[_make_comp("U1", x=10, y=10)])
        b = _make_design(components=[_make_comp("U1", x=10.3, y=10)])
        result = DesignComparator().compare(a, b)
        assert result.components_moved == 0

    def test_component_rotated(self):
        a = _make_design(components=[_make_comp("U1", rotation=0)])
        b = _make_design(components=[_make_comp("U1", rotation=90)])
        result = DesignComparator().compare(a, b)
        rotated = [c for c in result.component_changes if c.change_type == "rotated"]
        assert len(rotated) == 1

    def test_component_value_changed(self):
        a = _make_design(components=[_make_comp("R1", value="10k")])
        b = _make_design(components=[_make_comp("R1", value="4.7k")])
        result = DesignComparator().compare(a, b)
        changed = [c for c in result.component_changes if c.change_type == "value_changed"]
        assert changed[0].old_value == "10k"
        assert changed[0].new_value == "4.7k"

    def test_multiple_changes(self):
        a = _make_design(components=[_make_comp("U1", x=10), _make_comp("R1", value="10k"), _make_comp("C1")])
        b = _make_design(components=[_make_comp("U1", x=20), _make_comp("R1", value="4.7k"), _make_comp("R2")])
        result = DesignComparator().compare(a, b)
        assert result.components_added == 1
        assert result.components_removed == 1
        assert result.components_moved == 1


class TestNetChanges:
    def test_net_added(self):
        a = _make_design(nets=[_make_net("GND")])
        b = _make_design(nets=[_make_net("GND"), _make_net("VCC")])
        result = DesignComparator().compare(a, b)
        assert result.nets_added == 1

    def test_net_removed(self):
        a = _make_design(nets=[_make_net("GND"), _make_net("CLK")])
        b = _make_design(nets=[_make_net("GND")])
        result = DesignComparator().compare(a, b)
        assert result.nets_removed == 1

    def test_nets_unchanged(self):
        nets = [_make_net("GND"), _make_net("VCC")]
        result = DesignComparator().compare(_make_design(nets=nets), _make_design(nets=nets))
        assert result.nets_added == 0
        assert result.nets_removed == 0


class TestOutput:
    def test_total_changes(self):
        a = _make_design(board_width_mm=50, components=[_make_comp("U1")], nets=[_make_net("GND")])
        b = _make_design(board_width_mm=60, components=[_make_comp("U1"), _make_comp("R1")], nets=[_make_net("GND"), _make_net("VCC")])
        result = DesignComparator().compare(a, b)
        assert result.total_changes == 3

    def test_to_dict_structure(self):
        a = _make_design(components=[_make_comp("U1")])
        b = _make_design(components=[_make_comp("U1"), _make_comp("R1")])
        c = DesignComparator()
        d = c.to_dict(c.compare(a, b))
        assert "design_a" in d
        assert "component_changes" in d
        assert d["component_changes"]["added"] == 1

    def test_to_dict_details(self):
        c = DesignComparator()
        d = c.to_dict(c.compare(_make_design(), _make_design(components=[_make_comp("U1", value="MCU")])))
        assert d["component_changes"]["details"][0]["ref_des"] == "U1"


class TestEdgeCases:
    def test_empty_designs(self):
        result = DesignComparator().compare(_make_design(components=[], nets=[]), _make_design(components=[], nets=[]))
        assert result.total_changes == 0

    def test_missing_attributes(self):
        result = DesignComparator().compare(SimpleNamespace(source_file="a"), SimpleNamespace(source_file="b"))
        assert result.total_changes == 0

    def test_none_dimensions(self):
        result = DesignComparator().compare(_make_design(board_width_mm=None, board_height_mm=None), _make_design(board_width_mm=50, board_height_mm=40))
        assert result.board_size_changed
