# Room rules screen picks (draft, card AI-ROOM-RULES-TRUST-REPAIR-1)

The three screen choices left out of v5.108.39, built with the operator defaults.

## What changed for you

1. **"When" stays on Describe a rule.** No change: it was already there. You pick when the rule runs; the model
   only writes what it does.
2. **Rule writing model has its own menu item.** Coordinator Manager options now show "Rule writing model" as its
   own entry, after Optimizer. It is no longer inside the Optimizer AI settings. Your current choice carries over
   (same stored setting, nothing to redo). Saving the Optimizer form no longer touches it.
3. **Check your rule is a plain menu.** After the preview you see "Save" and "Change the wording" as two separate
   choices. When room rules are off in the room, a third choice comes first: "Save and turn on room rules here".
   Plain "Save" then keeps them off. "Change the wording" goes back to the step you came from (your words are kept
   for a described rule; the automation step for a Run-an-automation rule) and saves nothing.

## Live acceptance checks

- Coordinator Manager > Configure: the menu has "Rule writing model"; opening it shows the current value
  (expect `ai_task.claude_ai_task` unless changed). The Optimizer form's LLM section has no "Rule writing model".
- Change the model there and save; reopen: the new value shows. Open and save Optimizer: the model is unchanged.
- A room with room rules on: Room rules > Run an automation > pick one > Check your rule shows exactly "Save" and
  "Change the wording". Save adds the rule to Your rules.
- Same room, Describe a rule > Check your rule > Change the wording: back on Describe a rule with the text filled in;
  Your rules has nothing new.
- A room with room rules off: Check your rule shows "Save and turn on room rules here" first; picking it saves and
  turns the room's Room Rules switch on. Plain Save leaves the switch off.
- No reload storm: changing only the rule writing model does not reload room entries (key is still in the
  reload-suppress set).
