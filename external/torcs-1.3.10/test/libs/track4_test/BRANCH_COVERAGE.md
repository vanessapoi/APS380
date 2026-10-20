# Track V4 Source Branch Matrix

This matrix records the manual source-level branch audit for
`src/modules/track/track4.cpp`. The project does not currently have an
instrumented native branch-coverage tool, so this is not a compiler-generated
coverage percentage.

The audit treats every `if`, `else if`, loop condition, `switch` case, and
short-circuit operand as a branch. Fixed-count loops are covered through entry,
iteration, and termination. Conditions inside the `TSTX`, `TSTY`, and `TSTZ`
macros are covered with extents on both sides of the initial zero bounds.

## Test Seams

`track4_test.cpp` includes `track4.cpp` and `track.cpp` in one test translation
unit. The normal path calls the real TORCS dependencies. Test-only wrappers
provide deterministic failure of `malloc`, `calloc`, `vsnprintf`, duplicate
hash lookup, and parameter-handle release tracking. The fatal wrapper prints
and returns after diagnostics, matching the shipped Windows `GfFatal` macro. A
test-only exit wrapper marks explicit process termination. No production test
hooks are required.

`TrackBuildExTest` verifies that extended builds own their parameter handle,
clear it during shutdown, and release the previous track before a repeated
build.

`TrackShutdownTest` verifies that partially initialized track state without a
segment ring can still be released safely.

## Branch Mapping

| Production area | Branch arms | Characterization tests |
|---|---|---|
| `formatTrackPath` | Valid formatting; invalid size, negative result, and truncation rejected | `Track4PathTest.FormatsValidPath`, `Track4PathTest.RejectsInvalidBufferSize`, `Track4PathTest.RejectsTruncatedPath`, `Track4PathTest.RejectsFormattingFailure` |
| `getTrackSurface` | Empty/nonempty list; head/later/not found; allocation success/failure | `ReusesSurfacesAndReadsConfiguredSurfaceProperties`, `ReportsSurfaceAllocationFailure` |
| `readDefaultSideParameters` | Both sides; level/nonlevel banking; plan/curb/wall borders; fence/wall barriers | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `BuildsConfiguredSidesBordersAndBarriers`, `ReadsWallAsDefaultBorderFallback` |
| `addSides` parameter reading | First/later profile step; plan/curb/wall overrides; fence/wall overrides | `BuildsConfiguredSidesBordersAndBarriers`, `AppliesSegmentSideOverridesAcrossProfileSteps` |
| `addSides` construction | Border present/absent; start width, end-only width, and no side; right/left; empty/nonempty side chain; barrier success/failure | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `BuildsConfiguredSidesBordersAndBarriers`, `AppliesSegmentSideOverridesAcrossProfileSteps`, `ReportsBarrierAllocationFailure` |
| Segment list and extensions | Ordinary/extended; empty/rejected list; missing/present type; missing/present marks; mark termination by string end and 256 limit; duplicate/not duplicate | `SkipsEntriesWithoutType`, `RejectsTrackWhenNoSegmentsAreConfigured`, `NonExtendedBuildIgnoresMarks`, `ExtendedBuildAllowsSegmentsWithoutMarks`, `ExtendedBuildStoresMarksOnlyOnFirstSubdivision`, `ExtendedBuildCapsTurnMarksAt256`, `ExtendedBuildRejectsDuplicateSegmentName` |
| Segment type parsing | Straight/left/right; unknown after valid and unknown first, both rejected | `BuildsStraightLeftAndRightGeometryInRingOrder`, `RejectsUnknownTypeAfterValidSegment`, `RejectsLeadingUnknownType` |
| Elevation parsing | Explicit/side-derived start; explicit/grade/side-average end; default/explicit banking | `ReadsExplicitElevationsBankingAndSharedTangents`, `DerivesLinearProfileEndFromGrade`, `UsesSideEndAverageWhenCenterEndAndGradeAreMissing`, `NormalizesNegativeAndPositiveTrackExtents` |
| Profile parsing | Spline/linear; one/explicit steps; zero/nonzero step length; shared tangents present/absent | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `ReadsExplicitElevationsBankingAndSharedTangents`, `DerivesLinearProfileEndFromGrade`, `SubdividesProfilesUsingGlobalAndExplicitStepCounts` |
| Radius subdivision | Equal/changing radius; one/multiple steps; zero/nonzero radius delta | `BuildsStraightLeftAndRightGeometryInRingOrder`, `BuildsChangingRadiusTurnsWithOneAndMultipleSteps` |
| Ring construction | First/subsequent allocation; all geometry switch cases; ordinary/marked subdivisions; straight/turn radius update; one/multiple source entries | `BuildsStraightLeftAndRightGeometryInRingOrder`, `SubdividesProfilesUsingGlobalAndExplicitStepCounts`, `ExtendedBuildStoresMarksOnlyOnFirstSubdivision` |
| Bounds updates | Min/max comparisons true and false for X/Y/Z; straight and discretized turn loops | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `BuildsStraightLeftAndRightGeometryInRingOrder`, `NormalizesNegativeAndPositiveTrackExtents` |
| Side geometry helpers | Straight/left/right; right/left side; level/tangent banking; growing/shrinking widths | `BuildsConfiguredSidesBordersAndBarriers`, `AppliesSegmentSideOverridesAcrossProfileSteps`, `BuildsSidesForBothTurnDirections` |
| Pit lookup | First/last generated segment; absent/present names; found/not found; match before/end of search; all four completeness operands | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `IgnoresPitDefinitionWithUnknownSegmentNames`, `IgnoresPitDefinitionWithoutExit`, `IgnoresPitDefinitionWithoutStart`, `IgnoresPitDefinitionWithoutEnd`, `BuildsRightSidePitsWithoutOuterSideSegment`, `ResolvesPitBoundariesWithinFirstSubdividedSourceSegment` |
| Pit range and placement | Ordinary/wrapping range; right/left; change/stay segment; residual skip/no skip; inner-only/inner-plus-outer side independently for right and left | `BuildsRightSidePitsWithoutOuterSideSegment`, `BuildsRightSidePitOffsetsWithBorderAndOuterSide`, `BuildsLeftSidePitOffsetsWithoutOuterSideSegment`, `BuildsWrappingLeftSidePitsWithBorderAndOuterSide`, `PitPlacementSkipsSegmentsShorterThanResidualOffset` |
| Pit marking | Pit-start/interior/pit-end; outer segment present/absent; both barrier sides | `BuildsRightSidePitsWithoutOuterSideSegment`, `BuildsWrappingLeftSidePitsWithBorderAndOuterSide` |
| Cameras | No/list present; allocation success/failure with failure rejected; first/subsequent insertion; immediate/later segment lookup; one/multiple assignment iterations; required field present/missing with missing fields rejected | `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `BuildsSingleCameraWithSingleSegmentAssignment`, `BuildsAndLinksMultipleCameras`, `ReportsCameraAllocationFailure`, `ReportsCameraWithoutSegment`, `ReportsCameraWithoutFovStart`, `ReportsCameraWithoutFovEnd` |
| Finalization | Last/start/normal race classification; no/one/two side levels; camera normalization absent/present and one/multiple cameras | `BuildsStraightLeftAndRightGeometryInRingOrder`, `BuildsMinimalStraightWithDefaultSurfacesAndBarriers`, `BuildsConfiguredSidesBordersAndBarriers`, `BuildsAndLinksMultipleCameras` |
| Model invariants | Ring links, IDs, cumulative lengths, adjacent boundaries, side attachment, teardown ownership | `MaintainsRingGeometryAndOwnershipInvariants` |
| `TrackSpline` dependency | Start, midpoint, and end behavior | `TrackSplineTest.PreservesEndpointsAndTangents` |

## Remaining Findings

No unresolved fatal fall-throughs remain from this audit.
