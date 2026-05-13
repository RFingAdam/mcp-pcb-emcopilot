# CISPR-25 quick scan walkthrough

A 60-second pre-compliance sanity check on an automotive PCB layout
before shipping it to the EMC lab. The goal: catch obvious return-path
breaks, decoupling gaps, and clock-EMI risks early — when changing them
is cheap.

## Scenario

You have a KiCad PCB for an automotive accessory — a switching regulator
+ MCU + CAN transceiver — and you want to know if it has any obvious
EMC red flags against CISPR-25 (vehicle-component radiated emissions)
before sending it out for testing.

## Inputs

- A `.kicad_pcb` file (or ODB++, IPC-2581, Altium `.PcbDoc`, Gerber set)
- Knowledge of which net carries the switching node (e.g. `SW_3V3`)
- Target class — CISPR-25 Class 5 is the common automotive bar

## Conversation script

```
You: I have a KiCad layout at /tmp/dashboard_accessory.kicad_pcb.
     Run a CISPR-25 Class 5 pre-compliance scan and flag the
     top 5 EMC risks.

Claude: [calls pcb_set_review_context with cispr_class=5,
         standard='CISPR-25', vehicle_class='passenger']
        [calls pcb_parse_layout with the .kicad_pcb path]
        [calls pcb_classify_nets to identify power, clocks, switching nodes]
        [calls pcb_analyze_return_paths]
        [calls pcb_analyze_decoupling]
        [calls pcb_analyze_smps_emi for the SW_3V3 net]
        [calls pcb_analyze_clock_emi for any clocks]
        [calls pcb_predict_emissions with the cispr25 limit set]

        Top 5 risks:
        1. Return path for SW_3V3 crosses a plane split near U3 ...
        2. Decoupling on U7 (MCU) inadequate above 200 MHz ...
        3. ...

You: Generate a DOCX report I can share with the EMC engineer.

Claude: [calls pcb_generate_docx_report with severity_threshold='medium']

        Report written to /tmp/dashboard_accessory_emc_review.docx
        (12 pages, 5 findings with board renders).
```

## Expected outputs

- **Top-N finding list** with severity badges and the analyzer that
  raised each finding.
- **A DOCX report** at the path you specify, with embedded board
  renders annotated at the offending coordinates.
- **A predicted emissions plot** vs the CISPR-25 Class 5 limit line.

## Tools exercised

This walkthrough exercises these tools from mcp-pcb-emcopilot's catalog:

- `pcb_set_review_context` — locks the standard + class
- `pcb_parse_layout` — KiCad parser
- `pcb_classify_nets` — finds clocks, power, and switching nodes
- `pcb_analyze_return_paths`, `pcb_analyze_decoupling`,
  `pcb_analyze_smps_emi`, `pcb_analyze_clock_emi` — domain analyzers
- `pcb_predict_emissions` — predicted-vs-limit comparison
- `pcb_get_cispr25_limit` — limit-line lookup
- `pcb_generate_docx_report` — final deliverable

## Notes and caveats

- **This is pre-compliance, not certification.** The predicted-emissions
  numbers are a sanity check, not a substitute for chamber measurement.
- **Layouts with stitched ground planes and short return paths score
  cleaner.** If the analyzer flags a return-path break, double-check
  by hand with `pcb_trace_return_path` before redesigning.
- **CISPR-25 limit lines are conducted + radiated; the analyzer's
  current focus is radiated.** Conducted-emissions work pairs better
  with measurement than with layout-time prediction.
