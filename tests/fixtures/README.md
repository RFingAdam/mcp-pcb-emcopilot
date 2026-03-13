# Test Fixtures

All fixture files in this directory are **synthetic** designs created for automated testing.
They contain no customer or proprietary data.

## Files

### simple_2layer.kicad_pcb
A minimal 2-layer KiCad PCB design (KiCad 6+ S-expression format).
- 2 copper layers (F.Cu, B.Cu)
- Board area: ~50x30mm
- 5 components: U1 (MCU), R1-R2 (resistors), C1 (capacitor), J1 (USB-C connector)
- 8 named nets including USB differential pair (USB_D_P, USB_D_N)
- 10 trace segments, 3 vias, 1 ground zone
- 2 net classes (Default, USB with diff pair settings)

### mixed_signal_4layer.kicad_pcb
A more complex 4-layer mixed-signal KiCad PCB design.
- 4 copper layers (F.Cu, In1.Cu/GND plane, In2.Cu/PWR plane, B.Cu)
- Board area: ~80x60mm
- 15 components: SOC MCU (BGA), DDR memory, USB PHY, 3 LDOs, passives, crystal, USB connector
- 24 named nets including DDR, USB, SPI, I2C, UART
- 25 trace segments, 10 vias, 2 zone pours
- 3 net classes (Default, USB, DDR) with impedance/diff pair targets
- Full stackup definition with prepreg/core dielectrics

### sample_top_copper.gbr
A minimal valid RS-274X Gerber file representing a top copper layer.
- Format: RS-274X with FSLAX34Y34
- Units: millimeters
- 5 aperture definitions (circles and rectangles)
- Multiple D01 draw, D02 move, and D03 flash commands
- Gerber X2 attributes (FileFunction, FilePolarity, etc.)

### sample_design.xml
A minimal valid IPC-2581 Rev C XML file.
- 4-layer stackup (TOP, GND plane, PWR plane, BOTTOM)
- 8 components placed on TOP and BOTTOM layers
- 5 named nets (GND, VCC_3V3, USB_D_P, USB_D_N, SPI_CLK)
- 6 trace segments across 2 layers
- 3 vias with pad stack definitions
- 3 design rules (min width, clearance, drill)
- Board outline: 80x60mm
