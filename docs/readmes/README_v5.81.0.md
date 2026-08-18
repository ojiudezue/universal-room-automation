# URA v5.81.0 — Egress face-identity (D1): person_id on crossings + census identity fuse, behind a kill switch

Cycle 3 of the census/guest arc. v5.79.0 fixed **guest mode**, v5.80.0 fixed the **interior
count**; this closes the **`person_id=None` gap** at the egress emit sites so entry/exit
crossings carry a real identity, and fuses that identity into the census union (name-deduped,
never a sum). Frigate face is the source (resolvable post-v5.80.0). **D2 (UniFi Protect
corroboration) is NOT in this release** — it is hard-gated on a real captured webhook payload.

**Ships behind a kill switch, default OFF.** The feature is dormant on deploy; live validation
is: flip it on, watch for a real `person_id`. Rationale below.

## The problem this closes

Egress crossings (`ura_person_egress_event` + the DB entry/exit row) always carried
`person_id=None` — the identity slot was wired downstream (sensors default to "unidentified")
but never populated. So every entered/exited person was anonymous, and the census could not use
egress-derived identity to firm up who is actually home.

## What shipped (D1 only)

**Frigate `person_id` stamp.** A new `_resolve_egress_face_identity` on `EgressDirectionTracker`
resolves the freshest recognized face on the crossing camera's stem within `FACE_MATCH_WINDOW_S`
(60s) — reusing the existing census face readers, no parallel resolver — and stamps it at both
emit sites (event + DB). No face → `person_id=None` (identity requires evidence).

**Census identity fuse at BOTH writers.** The resolved name feeds a short-lived `egress_face_ids`
set (TTL `EGRESS_FACE_UNION_TTL_S`, 300s) unioned into the identity set at **both**
`_cross_correlate_persons` (raw) **and** `_apply_enhanced_house_census` (house-level — the writer
that actually survives to `identified_count`). Fusing only the first would have been a
silently-dead feature; a plan review caught that (the inverse of the 2026-08-17 double-count).

**URA-slug canonical namespace.** All names entering the union canonicalize to the URA person
slug (`oji_udezue`) via `tracked_persons` — so the `person.<slug>` "not_home" veto actually
fires, the persisted DB column doesn't drift, and `Oji`/`oji` can't count as two. The
canonicalizer **fails closed** (no identity + one warning) if two residents share a first name.

**Entry-gated register (the correctness core).** `register_egress_face` fires **only on
`direction=="entry"`**; `exit` evicts any prior registration; `ambiguous` does neither. Without
this gate a resident walking *out* would inject a phantom identified person for 5 minutes — i.e.
a phantom guest. This was found and fixed in review (bug class: double-count-into-GUEST).

**Kill switch + observability (parsimony).** `CONF_EGRESS_IDENTITY_ENABLED` (options-flow bool,
**default False**) — when off, the resolver returns None, register is a no-op, and normalization
is not applied, so both fuse sites are **byte-identical to pre-cycle**. Observability rides on the
existing `PersonsEnteredTodaySensor`: two attributes — `egress_face_ids_active` (live set size)
and `egress_identities_stamped` (cumulative). No new entities.

## Knobs

| Knob | Rung | Default |
|---|---|---|
| `CONF_EGRESS_IDENTITY_ENABLED` | options-flow bool (kill switch) | **False** |
| `FACE_MATCH_WINDOW_S` | module constant | 60 |
| `EGRESS_FACE_UNION_TTL_S` | module constant | 300 |

## Non-goals (explicit)

- **No D2 / Protect corroboration** — gated on a real `ura_kp_face_probe_received` payload
  (captured via the recorder after residents return); evaluated separately, default OFF.
- No BLE room-presence or `exterior_track_linker` sub_label writes (identity notions stay
  distinct). No interior head-count reinforcement. No retroactive backfill of past `None` rows.

## Review

Tier 2-DB — plan review (found the single-writer double-count trap) + 3 framing-disjoint reviews
(A correctness / B cross-coordinator+double-count / C lifecycle+test-authority), all returning
DO-NOT-SHIP/SHIP-with-fix, + a focused 4th adversarial re-review (found the kill switch was not
truly inert + a canonicalizer silent-merge). All CRIT/HIGH/MED fixed, mutation-anchored. Cycle
tests 29/29; blast-radius regression clean (name-diff vs baseline empty; 6 pre-existing presence
batch-order failures are unrelated, present on develop pre-merge).

## Acceptance criteria — live

Residents return Wed; the switch is OFF on deploy.

- **L1:** boot clean, zero URA ERROR; with switch OFF, census/guest behavior byte-identical to
  v5.80.0 (no `person_id` stamped, `egress_identities_stamped` stays 0).
- **L2 (flip on):** set `CONF_EGRESS_IDENTITY_ENABLED=True`. On the next real entry crossing on a
  face-covered camera, the DB entry row + `PersonsEnteredTodaySensor` last-entry carry the
  resident's URA slug (not "unidentified"); `egress_identities_stamped` increments.
  Discriminator: a crossing whose face was last recognized 30+ min earlier carries
  `person_id=None` (not the stale name).
- **L3 (no phantom guest):** a resident EXITING (with the switch on) does NOT raise
  `identified_count` or create a guest; `egress_face_ids_active` does not grow on exits.
- **L4:** `face_lookup_missing_count` per-tick delta does not regress vs pre-deploy baseline.

## Live Validation

_Pending — switch OFF on deploy; flip-on validation (L2/L3) runs on occupancy (Wed). L1
byte-identical check provable immediately post-restart._
