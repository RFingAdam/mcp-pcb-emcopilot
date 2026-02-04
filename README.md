<p align="center">
  <img src="assets/logo.svg" alt="MCP PCB EM Copilot" width="400">
</p>

<p align="center">
  <strong>PCB design review, EMC analysis, and signal integrity via MCP</strong>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#features">Features</a> •
  <a href="#usage-examples">Usage</a> •
  <a href="#tool-reference">Tool Reference</a>
</p>

---

An MCP server that enables AI assistants to analyze PCB designs for impedance control, signal integrity, and EMC compliance. Essential tools for RF, high-speed digital, and mixed-signal PCB design.

## Features

### Impedance Calculators
- **pcb_calc_microstrip_impedance** - Calculate surface trace impedance (IPC-2141)
- **pcb_calc_stripline_impedance** - Calculate buried trace impedance
- **pcb_calc_differential_impedance** - Calculate differential pair impedance (USB, HDMI, etc.)
- **pcb_calc_trace_width** - Calculate trace width for current capacity (IPC-2221)

### Signal Integrity Analysis
- **pcb_analyze_timing** - Analyze setup/hold margins for high-speed signals
- **pcb_analyze_crosstalk** - Estimate NEXT and FEXT between parallel traces
- **pcb_analyze_via** - Analyze via inductance, capacitance, and impedance

### EMC Analysis
- **pcb_analyze_current_loop** - Estimate radiated emissions for compliance
- **pcb_estimate_bandwidth** - Calculate bandwidth and EMC concerns from rise time

### Reference Data
- **pcb_get_stackup_templates** - Common PCB stackup configurations
- **pcb_get_material_properties** - Dielectric properties for FR4, Rogers, etc.

## Installation

### 1. Clone and install

```bash
git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
cd mcp-pcb-emcopilot
uv pip install -e .
```

### 2. Add to your MCP client

**Claude Code:**
```bash
claude mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Codex CLI:**
```bash
codex mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Config file format:**
```json
{
  "command": "uv",
  "args": ["run", "--directory", "/path/to/mcp-pcb-emcopilot", "mcp-pcb-emcopilot"]
}
```

## Usage Examples

### Design 50-ohm USB traces

```
I need to route USB 2.0 differential pairs on a 4-layer FR4 board with 1.6mm thickness.
Calculate the trace dimensions for 90 ohms differential impedance.
```

The AI will:
1. Use `pcb_calc_differential_impedance` to iterate on trace width/spacing
2. Provide exact dimensions for your stackup

### Check power trace capacity

```
What trace width do I need for 5A on an external layer with 2oz copper and 20°C rise?
```

The AI will use `pcb_calc_trace_width` with IPC-2221 formulas.

### Analyze signal integrity

```
I have a 100mm DDR4 data trace at 2400 MT/s. The signal has 200ps rise time.
Check if timing will work with 250ps setup and 150ps hold requirements.
```

The AI will use `pcb_analyze_timing` to verify margins.

### Check crosstalk

```
I have two 0.15mm traces spaced 0.2mm apart running parallel for 50mm on a 0.1mm dielectric.
What's the expected crosstalk with 500ps rise time?
```

The AI will use `pcb_analyze_crosstalk` and recommend spacing improvements.

### EMC pre-compliance check

```
I have a 100MHz clock with 10mA current and a return path that creates a 50mm² loop.
Will this pass FCC Class B?
```

The AI will use `pcb_analyze_current_loop` to estimate emissions and margin.

## Tool Reference

### Impedance Formulas

The impedance calculators use industry-standard IPC-2141 formulas:

| Trace Type | Typical Applications | Formula Basis |
|------------|---------------------|---------------|
| Microstrip | Top/bottom layer signals | Hammerstad & Jensen |
| Stripline | Inner layer signals | Cohn |
| Differential | USB, HDMI, LVDS, DDR | Coupled line theory |

### Supported Standards

- **IPC-2221** - Generic PCB design standard (current capacity)
- **IPC-2141** - Controlled impedance design
- **FCC Part 15** - EMC limits for radiated emissions analysis

### Material Database

Built-in properties for:
- FR4 (standard and high-Tg)
- Rogers RO4003C, RO4350B
- Isola I-Speed
- Panasonic Megtron 6
- Polyimide (flex circuits)

## Output Examples

### Microstrip Impedance
```json
{
  "success": true,
  "impedance_ohms": 50.2,
  "effective_er": 3.21,
  "propagation_delay_ps_per_inch": 151.8,
  "trace_type": "microstrip",
  "parameters": {
    "trace_width_mm": 0.3,
    "dielectric_height_mm": 0.2,
    "trace_thickness_mm": 0.035,
    "dielectric_constant": 4.3
  }
}
```

### EMC Current Loop Analysis
```json
{
  "success": true,
  "e_field_dbuv_m": 35.2,
  "fcc_class_b_limit_dbuv_m": 40,
  "margin_db": 4.8,
  "compliant": true,
  "margin_acceptable": false,
  "recommendations": [
    "Reduce loop area by routing signal and return paths closer together",
    "Consider adding bypass capacitors near high-frequency sources"
  ]
}
```

## Common Design Targets

| Interface | Single-Ended (Ω) | Differential (Ω) |
|-----------|------------------|------------------|
| General purpose | 50 | - |
| USB 2.0 | - | 90 |
| USB 3.x | - | 85 |
| HDMI | - | 100 |
| DDR4 | 40 | 80 |
| PCIe | - | 85 |
| Ethernet | - | 100 |

## License

Apache-2.0

## Author

Adam Engelbrecht - [@RFingAdam](https://github.com/RFingAdam)
