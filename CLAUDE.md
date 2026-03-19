# swf-remote AI Guidelines

External PanDA monitoring frontend for the ePIC experiment. Consumes
swf-monitor REST endpoints via SSH tunnel from pandaserver02 at BNL.

Sister project to swf-monitor, swf-testbed, swf-common-lib.

## Architecture

- **Web pages**: DataTables views calling monitor_client for data, formatting
  responses with local URLs. Templates mirror swf-monitor's pandamon pages.
- **MCP server**: Re-exposes PanDA data for LLM access outside BNL.
- **Data source**: Thin REST endpoints on swf-monitor wrapping panda/queries.py.
- **No local PanDA data**: All data comes from swf-monitor through the tunnel.

## Conventions

Follow swf-monitor conventions: python-decouple, single settings.py, same
URL structure under /panda/.

## Critical Thinking Requirements

Before implementing ANY solution, explain:
1. Data Flow — Where does data come from, get stored, get used?
2. Problem Definition — What is the actual problem?
3. Solution Validation — Why will this work? What could go wrong?

DO NOT CODE UNTIL you can trace the complete data flow.
