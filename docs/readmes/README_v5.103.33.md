# v5.103.33: one darkness setting per room

**Card:** `ROOM-LIGHTING-SETUP-REDESIGN-1` (operator 2026-10-02: "That would mean 2 if dark settings? You need to dedup").

After merging the lighting menus, the Lighting step showed two "only when dark" controls: the room's entry action ("Smart (Only When Dark)") and the per-light "only when dark" picker.

- The room setting is now THE darkness control: **"Turn lights on when someone enters": Never (I switch them) / Always / Only when dark.**
- The per-light picker is an **Advanced** exception, relabelled **"Wait for dark (exceptions)"**: "Only used when the room is set to Always: these lights still wait for dark."
- Labels only; stored keys, values and behaviour unchanged.
