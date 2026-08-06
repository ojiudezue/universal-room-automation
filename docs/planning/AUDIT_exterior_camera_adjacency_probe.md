
---

## Operator ratification (2026-08-06)

Ratified with corrections. Physical truth overrides transition counts in
both directions:

1. **back_yard ↔ hot_tub: CONFIRMED adjacent** (data was thin at 2 obs;
   operator confirms).
2. **Pool service chain declared** (explains the pool_equipment oddity):
   service enters via rear_ptz and/or g5_bullet → picked up by the pool
   overhead camera (armcrest — operator CONFIRMED 2026-08-06) and back_yard → traverses
   hot_tub → then pool_equipment. Edges added: rear_ptz↔armcrest,
   rear_ptz↔back_yard, g5_bullet↔armcrest, g5_bullet↔back_yard,
   armcrest↔hot_tub, back_yard↔hot_tub, hot_tub↔pool_equipment.
3. **pool_equipment ↔ rear_ptz: REMOVED** (6 obs were missed-intermediate
   artifacts of the chain above, not direct adjacency).
4. **rear_ptz ↔ utilities_ptz: REMOVED** (17 obs; physically impossible
   directly — back route runs through the pool chain, front route
   through front_side_ptz).

Accepted residual (recorded): removed-but-co-firing pairs mean a missed
intermediate detection splits a real track into two threads —
over-alerting, the safe direction. If splits at these seams recur, fix
camera detection reliability, do NOT re-add false edges.

RATIFIED GRAPH (paste target for EXTERIOR_ADJACENCY_GRAPH; symmetrize in
code): all probe-proposed pairs EXCEPT the two removals above, PLUS the
chain edges in (2).
