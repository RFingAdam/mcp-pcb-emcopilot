"""Tests for KiCad plugin (without KiCad dependency)."""
import pytest
import json
import os


class TestPluginMetadata:
    def test_metadata_valid_json(self):
        metadata_path = os.path.join(
            os.path.dirname(__file__), "..", "kicad_plugin", "metadata.json"
        )
        with open(metadata_path) as f:
            data = json.load(f)
        assert data["name"] == "MCP PCB EMCopilot"
        assert data["type"] == "plugin"
        assert data["license"] == "Apache-2.0"

    def test_metadata_has_version(self):
        metadata_path = os.path.join(
            os.path.dirname(__file__), "..", "kicad_plugin", "metadata.json"
        )
        with open(metadata_path) as f:
            data = json.load(f)
        assert len(data["versions"]) > 0
        assert "version" in data["versions"][0]


class TestPluginModule:
    def test_plugin_importable(self):
        """Plugin module can be imported (without KiCad)."""
        # Just test that the file is valid Python
        plugin_path = os.path.join(
            os.path.dirname(__file__), "..", "kicad_plugin", "emcopilot_plugin.py"
        )
        with open(plugin_path) as f:
            code = f.read()
        compile(code, plugin_path, "exec")

    def test_plugin_class_defined(self):
        """EMCopilotPlugin class exists in source."""
        plugin_path = os.path.join(
            os.path.dirname(__file__), "..", "kicad_plugin", "emcopilot_plugin.py"
        )
        with open(plugin_path) as f:
            code = f.read()
        assert "class EMCopilotPlugin" in code
        assert "def Run" in code
