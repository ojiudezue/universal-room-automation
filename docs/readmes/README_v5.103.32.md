# v5.103.32: one Lighting menu instead of two

**Card:** `ROOM-LIGHTING-SETUP-REDESIGN-1` (operator 2026-10-02: "The old light automation menu still exists. Duplication?").

The room options menu had "Lighting Automation" (entry/exit action, dark threshold, brightness, fade-in/out, collapsed flap-sensitivity) AND the new "Light Roles & Looks" (which lights do what). The old step's fields now sit at the top of the single **"💡 Lighting"** step, and the old menu item is gone. Same keys, same values, no behaviour change; the old step handler remains for compatibility. The flap-sensitivity section is flattened on save exactly as before.

**Tests:** menu test updated (one lighting item); dialog meta-test covers the merged step.
**Live:** room options menu shows one "💡 Lighting" item whose form starts with Lights on Entry / Exit.
