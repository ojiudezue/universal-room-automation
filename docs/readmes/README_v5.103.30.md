# v5.103.30: the new lighting menu item has a name, and colour temperatures are picked on a colour slider

**Card:** `ROOM-LIGHTING-SETUP-REDESIGN-1` (operator feedback 2026-10-02 on the live v5.103.29 dialogs).

- The room options menu showed a blank row for the new Lighting behaviour step. It is now **"💡 Light Roles & Looks"** (strings.json + en.json). A test now fails if any room menu step lacks a label.
- Every colour-temperature field (evening colour, evening night-light colour, night-light day/sleep colour) uses HA's colour-temperature selector in kelvin (2000–6500 K): a slider shaded warm orange → cool blue, instead of a typed number. Stored values are unchanged (live values 2000 K / 4000 K fit the range). A test fails if a typed "K" number field returns.
- No behaviour change.

**Live:** room options menu shows "Light Roles & Looks"; the colour fields show a shaded slider.
