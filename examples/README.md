# Examples

Runnable walkthroughs showing how to drive mcp-pcb-emcopilot from a
Claude / MCP client. Each example targets one workflow — pick the one
closest to the question you're trying to answer.

## Available examples

| Example | Workflow | Use when |
|---|---|---|
| [`cispr25_quick_scan.md`](cispr25_quick_scan.md) | Automotive EMC pre-compliance | You have a layout and need a 60-second sanity check against CISPR-25 limits before sending to the EMC lab. |

## Running examples

Examples are written as Claude conversation scripts — the user prompts
and the expected tool calls. Reproduce them by:

1. Install the MCP server: `pip install git+https://github.com/RFingAdam/mcp-pcb-emcopilot.git`
2. Wire it into Claude Desktop or Claude Code via `claude_desktop_config.json`
3. Open a new chat in your client and paste the user prompts from the
   example, one at a time.

The expected tool calls are reference points — Claude may take a
slightly different path through the toolset depending on phrasing and
context. The end state (findings + report) should match.

## Adding new examples

If you have a workflow that's stable enough to share, follow the
pattern in `cispr25_quick_scan.md`:

- One markdown file
- "Scenario", "Inputs", "Conversation script", "Expected outputs"
  sections
- Cite the analyzer tools the example exercises
- Note any prerequisites (layout format, hardware, etc.)
