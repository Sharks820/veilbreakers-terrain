# Codex Final Cross-Reference Audit - Section 11 v3 CE Fixes

Source: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`

Audit date: 2026-05-06

## Verdict

FAIL.

Major blockers:

- `[AUTO-APPLIED]` count is 18, not canonical 16.
- Only 15 of 18 `[AUTO-APPLIED]` markers carry `Decision 3.1` through `Decision 3.5`.
- Decision 3.2 propagation fails: required MicroSplat references still say `$40` / `$20`, with zero `MicroSplat $0` mentions.
- Section 11.0.4 milestone #2 says `Block 1 PR #19`, but PR #19 lives in section 11.2 / Block 2.
- Section 11 table row counts are not consistently aligned with header/footer wording unless implicit "active/group/core" conventions are applied.
- Section 11.0 block-count cell does not say canonical `9 blocks`; it says `5 pilot blocks + Block 6 post-pilot maturity`.

Passes:

- TODO marker scan is clean: `TODO`, `TBD`, `FIXME`, `XXX` all count 0.
- Section 11.0 `Cuts surfaced` says 20 and section 11.7 has exactly 20 numbered cuts.
- Section 11.0 `Open deferrals` says 14 and section 11.8 has exactly 14 numbered deferrals.
- Decision 3.4 has Path 1 chosen at section 11.7 #3 and #9, and B5-CI1 / B5-DEP4 / B5-DEP5 are deferred by Path 1.

## Per-Section Table Row Counts

Counting method: physical markdown data rows in each requested table. Header/separator rows excluded. Struck rows and deferred rows are still physical rows unless noted.

| Section | Physical data rows | Header count/status | Footer/body count/status | Result |
|---|---:|---|---|---|
| 11.1 | 18 | Header says 14 PRs. | Footer says 14 PR groups / 15 active rows; struck moved rows #6/#7/#10 preserved. | FAIL vs physical; OK only under group/active convention. |
| 11.2 | 22 | Header says 22 PRs. | Footer says 22 PRs. | PASS. |
| 11.3 | 11 | Header says 11 PRs. | Footer says 11 PRs. | PASS. |
| 11.4 | 18 | Header says 12 PRs after Phase 4 fixes. | Footer says 12 active PRs; struck deferred #49-#54 preserved. | FAIL vs physical; OK only under active convention. |
| 11.5.1 | 23 | Header arithmetic is 5 blocking + 9 polish + 9 Phase 4 = 23. | No local footer count; Block 5 footer counts 6 Block 5a + 17 Unity 5b entries from this section. | PASS. |
| 11.5.2 | 12 | Header says 11 total. | B5-C4 is struck, leaving 11 active rows. | FAIL vs physical; OK only under active convention. |
| 11.5.3 | 8 | Header says 8 total. | Block 5 footer counts 3 base + 4 Phase 4 = 7 Block 5b rows; B5-D1 is struck/promoted. | MIXED: header matches physical, footer convention excludes B5-D1. |
| 11.5.4 | 12 | Header says 8 PRs core + B5-CI1 conditional + 3 Phase 4 = 11 total core. | Physical rows include B5-CI1 deferred, so 12 physical / 11 core. | OK only under core-plus-conditional convention. |
| 11.5.5 | 4 | Header says 4 PRs. | Body says all 4 are Block 5b. | PASS. |
| 11.5.6 | 4 | Header says 2 PRs core + B5-DEP4/DEP5 conditional. | Physical rows include 2 core + 2 deferred-by-Decision-3.4 rows. | PASS with convention. |
| 11.5.7 | 4 | Header says 4 PRs. | Body says all 4 are Block 6. | PASS. |
| 11.6.1 | 4 source rows | Header has no row count. | Footer says Block 6 totals 13 PRs: 2 + 5 + 2 + 4. Table source rows expand to 13 PR IDs. | PASS. |

## Canonical Total Checks

| Check | Expected | Observed | Status |
|---|---:|---:|---|
| Section 11.0 PR count cell | 114 | 114 | PASS. |
| Raw PR-table physical rows across sections 11.1-11.5.7 | 114 | 136 | FAIL if interpreted literally. |
| Reconciled convention total | 114 | 114 | PASS only if counted as: Block 1 14 groups + Block 2 22 + Block 3 11 + Block 4 18 physical rows including deferred #49-#54 + Block 5a/5b pilot-supporting 49. |
| Section 11.0 block-count cell | 9 | `5 pilot blocks + Block 6 post-pilot maturity` | FAIL vs requested canonical 9. |
| Physical block headings | 9 | 8 if counting Block 1-5, 5a, 5b, Block 6; 9 only if Fix 1.0 is counted as a block-like prereq. | FAIL/AMBIGUOUS. |
| Section 11.0 Cuts surfaced | 20 | 20 | PASS. |
| Section 11.7 numbered cuts | 20 | 20, contiguous #1-#20 | PASS. |
| Section 11.0 Open deferrals | 14 | 14 | PASS. |
| Section 11.8 numbered deferrals | 14 | 14, contiguous #1-#14 | PASS. |

## AUTO-APPLIED Coherence

Observed marker count: 18.

Markers with valid `Decision 3.1`-`Decision 3.5` tag: 15.

Markers without valid Decision tag:

- Line 1690: `[AUTO-APPLIED - P3-Polish-1]`
- Line 1696: `[AUTO-APPLIED - P3-Polish-2]`
- Line 1916: `[AUTO-APPLIED - Phase 3 Theme 3.8 added]`

Decision-tagged marker distribution:

| Decision | Count | Lines |
|---|---:|---|
| 3.1 | 1 | 2104 |
| 3.2 | 6 | 50, 655, 723, 916, 1856, 2087 |
| 3.3 | 2 marker hits; 3 textual hits | 1629, 2066; plus line 1966 textual `[Decision 3.3]` |
| 3.4 | 5 marker hits; 12 textual hits | 1928, 1952, 1953, 2097, 2112; more textual refs at 1699, 1916, 1966, etc. |
| 3.5 | 1 | 2378 |

Status: FAIL. Canonical says 16 markers, all Decision-tagged. File has 18 markers, 3 without Decision number, 15 with Decision number.

## Decision Propagation

### Decision 3.1

Observed at section 11.7 #5, line 2104. No contradictory `Decision 3.1` references found.

Status: PASS.

### Decision 3.2

Required propagation: Q14, section 6.6, section 6.10, section 7.5, section 11.5.1 B5-U1, section 11.7 #1 must say MicroSplat 0 and have no remaining `$20` module mentions.

Observed:

- `MicroSplat $0`: 0 hits.
- `MicroSplat 0`: 0 hits.
- `MicroSplat $40`: 4 hits.
- `$20`: 12 hits.
- `$40`: 10 hits.
- Decision 3.2 markers: 6 hits, all still describe `$40` / `$20`.

Required locations checked:

- Q14 line 50: says `MicroSplat $40` and `$20 HDRP 2022` + `$20 Mesh Terrains`.
- Section 6.6 line 655/657: says `MicroSplat $40 default` and `$20 + $20 = $40`.
- Section 6.10 line 723: says `$40 total`.
- Section 7.5 line 916: says `MicroSplat $40` and `$20` modules.
- Section 11.5.1 B5-U1 line 1856: says `MicroSplat ... ($40, RECOMMENDED)` and `$20 + $20`.
- Section 11.7 #1 line 2087: says `MicroSplat $40` and `$20` modules.

Status: FAIL.

### Decision 3.3

Observed propagation:

- Section 11.0 dim table line 1629: 30-45 working days.
- Section 11.5 footer line 1966: 30-45 working days.
- Section 11.6 calendar minima line 2066: Decision marker present.

No contradictory 11-14 day active estimate found in section 11.

Status: PASS.

### Decision 3.4

Required propagation:

- Section 11.7 #3 marks Path 1 chosen.
- Section 11.7 #9 marks Path 1 chosen.
- B5-CI1, B5-DEP4, B5-DEP5 are deferred by Path 1.

Observed:

- Section 11.7 #3 line 2097: `[AUTO-APPLIED - Decision 3.4 ... Path 1 chosen for v1 pilot]`.
- Section 11.7 #9 line 2112: `[AUTO-APPLIED - Decision 3.4 / Path 1 chosen]`.
- B5-CI1 line 1928: `DEFERRED (Path 1 chosen per Decision 3.4)`.
- B5-DEP4 line 1952: `DEFERRED (Path 1 chosen per Decision 3.4)`.
- B5-DEP5 line 1953: `DEFERRED (Path 1 chosen per Decision 3.4)`.

Remaining inconsistency:

- Section 11.7 #3 still says `v1 pilot acceptance assumes a self-hosted GPU CI runner` and `CI without GPU runner cannot validate perf budget` immediately before choosing Path 1, which drops GPU perf gate from required checks. That wording conflicts with the chosen Path 1 framing unless rewritten as historical problem statement.

Status: PASS for requested anchors; FLAG for stale/conflicting explanatory wording in section 11.7 #3.

### Decision 3.5

Observed at section 11.12 hygiene runway, line 2378. It states post-pilot Block 6 hygiene PRs are a separate maintenance backlog, not pilot scope.

Status: PASS.

## TODO Marker Scan

Patterns scanned case-insensitively: `TODO`, `TBD`, `FIXME`, `XXX`.

| Marker | Count |
|---|---:|
| TODO | 0 |
| TBD | 0 |
| FIXME | 0 |
| XXX | 0 |

Status: PASS.

## Dim Table vs Body

| Field | Section 11.0 cell | Body count | Status |
|---|---|---:|---|
| Cuts surfaced | 20 | Section 11.7 has 20 numbered cuts. | PASS. |
| Open deferrals | 14 | Section 11.8 has 14 numbered deferrals. | PASS. |
| PR count | 114 | Reconciles to 114 only under implicit convention described above; raw rows = 136. | FLAG. |
| Block count | `5 pilot blocks + Block 6 post-pilot maturity` | Requested canonical says 9; physical heading count ambiguous. | FAIL. |

## Visible-Value Milestones

Section 11.0.4 milestone cross-reference checks:

| Milestone | Declared reference | Actual location | Status |
|---|---|---|---|
| #1 | Block 4 PR #6 + Block 1 PR #6.5 | PR #6 exists in section 11.4 line 1809; PR #6.5 exists in section 11.1 line 1738. | PASS. |
| #2 | Block 1 PR #19 | PR #19 exists in section 11.2 / Block 2 line 1761, not Block 1. | FAIL. |
| #3 | Block 2 PR #29 | PR #29 exists in section 11.2 line 1771. | PASS. |
| #4 | Block 5a PR B5-U1 | B5-U1 exists in section 11.5.1 line 1856, sub-block 5a. | PASS. |
| #5 | Block 5a PR B5-U2-U5 | B5-U2 through B5-U5 exist in section 11.5.1 lines 1857-1860, all sub-block 5a. | PASS. |

Additional stale wording:

- Section 11.0.4 intro says `shipping 90 PRs`, while section 11.0 dim table says `PR count ... 114`.

## 250-Word Summary

Section 11 is close enough to audit mechanically, but not internally clean enough to call cross-reference consistent. Physical table rows and stated counts diverge in several places because the document mixes physical rows, active rows, PR groups, core rows, conditional rows, and preserved struck trace rows. Some are explainable: section 11.1 has 18 physical rows but 14 groups / 15 active rows because moved #6/#7/#10 remain struck; section 11.4 has 18 physical rows but 12 active rows because #49-#54 are deferred. Others need cleanup language: section 11.5.2 says 11 but has 12 physical rows including struck B5-C4; section 11.5.3 says 8 physical rows while Block 5 totals count only 7 active Block 5b rows. The 114 PR total can be reconciled only through an implicit convention, not raw rows.

Decision propagation has one hard failure: Decision 3.2. All six required MicroSplat locations still say `$40` or `$20`; there are zero `MicroSplat $0` hits. Decision 3.4 mostly landed: Path 1 is chosen in section 11.7 #3 and #9, and B5-CI1/B5-DEP4/B5-DEP5 are deferred, but section 11.7 #3 still contains stale GPU-runner acceptance wording. Marker coherence also fails: 18 `[AUTO-APPLIED]` markers exist, not 16, and 3 lack Decision numbers. TODO scan passes at zero. Cuts and deferrals match: 20 and 14. Visible milestones mostly pass, except milestone #2 wrongly says Block 1 PR #19; PR #19 is in Block 2.

## Commands Used

```powershell
rg -n "^(#{2,6})\s+11(\.|\s)" docs\superpowers\specs\2026-05-05-biome-render-rebuild-design.md
rg -n "\[AUTO-APPLIED\]|TODO|TBD|FIXME|XXX|MicroSplat|Path 1|Decision 3\.[1-5]" docs\superpowers\specs\2026-05-05-biome-render-rebuild-design.md
Select-String -Path docs\superpowers\specs\2026-05-05-biome-render-rebuild-design.md -Pattern '\[AUTO-APPLIED[^\]]*\]' -AllMatches
```
