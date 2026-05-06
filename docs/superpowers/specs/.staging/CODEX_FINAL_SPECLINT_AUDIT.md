# Codex Final Spec-Lint Audit

Spec: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`

Scope: structural lint only. Spec file not edited.

## Summary

Spec lint verdict: FAIL. The document is close enough to parse, but not structurally clean enough for final sign-off. Section 11 numbering has one unexpected block, 11.1.0, and it appears before its parent 11.1; all requested expected 11.x headings otherwise exist in order. Markdown tables mostly parse, but Block 2 table has two rows with one extra cell because inline shell pipes are not escaped in rows 25 and 29. Heading hierarchy passes when fenced code is ignored; the apparent # heading inside the Mei parameter fence is not a real heading. Cross-reference integrity fails on one external-looking A.1 citation, missing Appendix B.8 through B.10 references, and unresolved PR #5 references after the runway split into 5a and 5b. PR uniqueness fails because moved rows for 6, 7, and 10 remain in Block 1 while active rows reuse those IDs in Block 4; struck rows still reserve the numbers. Strikethrough syntax fails for three deferred conditional rows, B5-CI1, B5-DEP4, and B5-DEP5, whose first cells are not struck. AUTO-APPLIED markers and code fences are balanced.

## Task Results

| Task | Verdict | Issues |
|---|---|---|
| 1. Block-numbering integrity | FAIL | Unexpected `§11.1.0` at line 1713; it appears before parent `§11.1` at line 1723. Expected sections `§11.0` through `§11.12` otherwise exist in requested order. |
| 2. Markdown table syntax | FAIL | Block 2 table starting line 1756 has 7 columns, but line 1767 has 8 columns and line 1771 has 8 columns. Cause: unescaped inline command pipes (`| grep -n ...`) inside table cells. |
| 3. Heading hierarchy | PASS | No heading-level jumps outside fenced code blocks. `#` inside the line 2525-2539 code fence was ignored correctly. |
| 4. Internal cross-references | FAIL | Unresolved section refs: `§A.1` line 1620; `§B.8` line 2285; `§B.9` line 2286; `§B.10` lines 2287 and 2301. Unresolved PR row refs: `PR #5` line 1630, bare PR list `#5` line 2265, and `PR #5` line 2820. `PR #5a` and `PR #5b` rows exist; `PR #5` does not. |
| 5. No duplicate PR numbers | FAIL | Duplicate PR row id `6` at lines 1737 and 1809; duplicate `7` at lines 1739 and 1810; duplicate `10` at lines 1742 and 1811. Struck moved rows still reserve the numbers. |
| 6. Deferred/struck-through rows | FAIL | Deferred rows not struck through in first cell: `B5-CI1` line 1928, `B5-DEP4` line 1952, `B5-DEP5` line 1953. Existing struck rows use balanced `~~...~~` syntax. |
| 7. `[AUTO-APPLIED]` markers | PASS | 18 markers found. Brackets balanced; no broken `[AUTO-APPLIED ...]` spans detected. |
| 8. Code-block fences | PASS | 130 fence markers found. Count is even; no unclosed fenced block detected. |

## Specific Issue List

1. Line 1713: `### 11.1.0 Fix 1.0 ...` is not in requested block sequence and is placed before `### 11.1`.
2. Line 1767: Block 2 PR 25 row has raw pipe in inline command, splitting table into 8 cells.
3. Line 1771: Block 2 PR 29 row has raw pipe in inline command, splitting table into 8 cells.
4. Line 1620: `§A.1` has no matching section heading in this spec.
5. Lines 2285, 2286, 2287, 2301: `§B.8`, `§B.9`, and `§B.10` have no matching Appendix B headings in this spec.
6. Lines 1630, 2265, 2820: `PR #5` references do not resolve to a row in `§11.1-§11.5`; only `5a` and `5b` exist.
7. Lines 1737/1809, 1739/1810, 1742/1811: PR ids `6`, `7`, and `10` appear twice.
8. Lines 1928, 1952, 1953: deferred conditional rows should be struck through if they are meant to be deferred/reserved rows.
