# Trackscene Directional Branch Coverage

The tests use `TR_SIDE_RGT == 0`, `TR_SIDE_LFT == 1`, geometry directions
`TR_RGT == 1`, `TR_LFT == 2`, `TR_STR == 3`, and vertex slots
`TR_SL/TR_SR/TR_EL/TR_ER == 0/1/2/3`.

| Area | Left | Right | Straight | Left curve | Right curve | Notes |
|---|---:|---:|---:|---:|---:|---|
| `countTrackVertices` | n/a | n/a | covered | covered | covered | Explicit expected allocation counts. |
| Main track | covered | covered | existing endpoint behavior only | covered | covered | Curve interior coordinates, pairing, and UVs. |
| Side (`TR_LSIDE`/`TR_RSIDE`) | covered | covered | covered | covered | covered | Side links, `TR_SL/TR_SR/TR_EL/TR_ER`, UV reversal, names; outer link past border covered on left. |
| Plan border (`TR_LBORDER`/`TR_RBORDER`) | covered | covered | covered | covered | covered | Pairing, UV reversal, and `t0LB`/`t0RB`. |
| Curb border | covered | covered | covered | covered | covered | Raised strips plus symmetric same-style, changed/missing-start, changed-end, and missing-end transition counts; exact serialized triangle winding is not decoded. |
| Wall border | covered | covered | covered | covered | covered | Three surface slots plus symmetric same-style, changed/missing-start, changed-end, and missing-end transition counts. |
| Fence barrier | covered | covered | covered | covered | covered | Both `barrier[]` slots, opposite vertical winding/UV, `B0/B1` names. |
| Wall barrier | covered | covered | covered | covered | covered | Both slots, all three surfaces, same-style/height continuation, and style/height transition caps. Pit-side exclusion is covered on both slots. |
| Pits | covered | covered | covered | n/a | n/a | Side-link traversal and mirrored offsets; full one-pit generators cover 6+10+6 vertices, point order, extent, and `P1ts`/`P2ts`/`P3ts` names. |
| Turn marks | covered | covered | covered | covered | covered | `turn...L/R` textures, mirrored placement, generated normal direction, and front/back `TuMk` lists. |
| Start bridge | covered | covered | covered | n/a | n/a | Zero-, one-, and two-link `lside`/`rside` traversal uses outermost `TR_SL`/`TR_SR` endpoints. |

Residual gaps are primarily bump/raceline texture modes, missing-next-border
behavior (the generator only caps when a next side exists but changes type or
style), and exact AC3D triangle winding after display-list serialization.
