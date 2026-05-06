# CODEX FINAL DEPGRAPH AUDIT

Source: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`

Scope: section 11.1 through 11.6.1. Parsed every non-struck PR table row, extracted the live `Deps` cell, built directed graph from `PR -> declared dependency`, then checked cycles, missing nodes, block-order inversions, deferred blockers, Phase 4 NEW nodes, and ASCII graph agreement.

## Executive Summary

I parsed the section 11 PR tables, excluding struck moved/dropped rows, then built the dependency graph from each live Deps cell. Result: the graph is acyclic, but the dependency contract is not clean. The spec says 114 PRs, and the prompt repeats B5b=39, yet the live tables contain 125 non-struck PR rows: B1=15, B2=22, B3=11, B4=12, B5a=6, B5b=43, Block 6=13, DEFERRED-3.4=3. That count drift must be fixed before execution tracking, or agents will argue from different universes. I found two orphan dependencies: PR #23 depends on #1.0, which has no row, and B5-D2 still depends on promoted/struck B5-D1 instead of #15.5. I found two textual cross-block forward references: #6.5 in Block 1 depends on #6 in Block 4, and #64 in Block 4 depends on B5-C2 in Block 5b. No active pilot PR depends on Block 6 or DEFERRED-3.4. The #15.5 and #14 relation stayed unidirectional: #14 depends on #15.5, while #15.5 depends on none. Phase 4 NEW PRs introduced no cycles. The ASCII graph does not match textual deps and should not be used as execution truth. Fix count drift and orphan edges before autonomous PR scheduling starts. Replace diagram after textual columns are corrected and re-counted before launch.

## Verdict

| Check | Result |
|---|---:|
| Total raw PR table rows parsed | 136 |
| Struck/moved/dropped rows excluded | 11 |
| Total PRs analyzed as graph nodes | 125 |
| Total declared dependency edges | 140 |
| Cycles found | 0 |
| Orphan deps | 2 |
| Cross-block forward refs | 2 |
| Deferred-PR deps blocking pilot | 0 |
| Phase 4 NEW circular deps | 0 |
| DAG validity verdict | ACYCLIC |
| ASCII graph matches textual `Deps` columns | NO |

## Count Drift

Live table counts do not match the stated 114-PR inventory.

| Logical block | Parsed non-struck rows |
|---|---:|
| B1 | 15 |
| B2 | 22 |
| B3 | 11 |
| B4 | 12 |
| B5a | 6 |
| B5b | 43 |
| Block 6 | 13 |
| DEFERRED-3.4 | 3 |
| Total | 125 |

Finding: B5b is 43 in the live rows, not 39. Either the count prose is stale or four B5b rows should be retagged/removed.

## Cycles

None. Graph is a DAG after excluding struck/moved/dropped rows.

## Orphan Deps

| PR | Line | Declared missing dep | Why orphan |
|---|---:|---|---|
| #23 | 1765 | #1.0 | No non-struck PR row exists for `#1.0`. Text likely means cite-refresh prereq, but it is encoded as a PR dep. |
| B5-D2 | 1906 | B5-D1 | `B5-D1` is struck/promoted to #15.5 at line 1905. Active B5-D2 still points at inactive row. |

Required fix: change `B5-D2` deps from `B5-D1` to `#15.5`, or restore a real B5-D1 row. For `#23`, add an explicit `#1.0` row or rename the dep to a non-PR prereq.

## Cross-Block Forward Refs

| PR | Line | Block | Depends on | Dep block | Issue |
|---|---:|---|---|---|---|
| #6.5 | 1738 | B1 | #6 | B4 | Block 1 waits on Block 4 polish row. This violates forward-only block execution. |
| #64 | 1825 | B4 | B5-C2 | B5b | Block 4 waits on Block 5b coherence row. This violates B4-before-B5 ordering. |

Note: #6.5 may be intentional traceability after #6 moved to B4, but as a real `Deps` cell it is still a forward ref.

## Deferred-PR Deps Blocking Pilot

None found. No B1/B2/B3/B4/B5a/B5b pilot PR depends on a Block 6 or DEFERRED-3.4 node.

Pilot caveat: B5-D2 depends on inactive/moved B5-D1. That is not a Block 6/DEFERRED dep, but it is still an active-pilot scheduling blocker.

## #15.5 vs #14

Verified fixed and unidirectional.

| PR | Line | Deps |
|---|---:|---|
| #15.5 | 1748 | none |
| #14 | 1746 | #15.5 |
| #18 | 1760 | #14, #15, #15.5 |

No #15.5 -> #14 edge exists. No #14 <-> #15.5 cycle exists.

## Phase 4 NEW PRs

Phase 4 NEW set checked: B5-U-NAV, B5-U15 through B5-U22, B5-C7 through B5-C12, B5-D5 through B5-D8, B5-T8 through B5-T10, and #65.

Cycles involving Phase 4 NEW PRs: none.

Risk still present: B5-D5/B5-D6/B5-D7/B5-D8 are acyclic, but B5-D2 earlier in that chain has the B5-D1 orphan. Fix that before scheduling the D-chain.

## ASCII Diagram Check

Diagram verdict: does not match textual `Deps` columns.

Major mismatches:

| Diagram area | Diagram implies | Textual `Deps` says | Result |
|---|---|---|---|
| line 1985 | #15 tied to #2 | #15 depends #14; #2 depends #1 | Mismatch |
| lines 2013-2015 | #19 -> #21 -> #22 and #21 -> #46 -> #47 | #19 depends #2; #21 depends #3; #22 depends #5b,#20; #46 depends #3; #47 depends #21 | Mismatch |
| lines 2021-2023 | #11 -> #44 and #11 -> #48; labels #11 as atomicity | #44 depends #42; #48 depends #12,#44,#5b; atomicity PR is #12 | Mismatch |
| lines 2028-2032 | #43 and B5-A4 feed #55; B5-A4 feeds #56 | #55 depends #5b,#2,#11,#56; #56 depends #43; B5-A4 depends #43 | Mismatch |
| line 2040 | B5-U4 -> B5-U5 | B5-U5 depends #39 | Mismatch |
| line 2043 | B5-U16 -> B5-U17 -> B5-U18 | B5-U17 depends B5-U11; B5-U18 depends B5-U16 | Mismatch |
| line 2047 | #15.5 -> B5-D2 | B5-D2 depends B5-D1, which is struck | Mismatch plus orphan |
| line 2047 | B5-D6 -> B5-D7 | B5-D6 depends B5-D4; B5-D7 depends B5-D4 | Mismatch |
| lines 2049-2050 | B5-T1 -> B5-T7; B5-T1 -> B5-T9 -> B5-T10 | B5-T7 depends B5-T1,B5-T2; B5-T9 depends B5-U16,B5-T1; B5-T10 depends B5-T1 | Mismatch |
| line 2052 | B5-DOC1 -> B5-DOC2 | B5-DOC1 depends #55; B5-DOC2 depends none | Mismatch |

Coverage gap: diagram omits many live textual edges entirely, including B5-U6/U7/U9/U10/U12 -> #42, B5-U8 -> B5-U2, B5-U11 -> #42/#27, B5-U14 -> B5-U13, B5-C1/C2/C6, B5-T1, B5-A1/A2/A3/A4, and DEFERRED-3.4 edges.

Do not use the ASCII diagram as scheduling truth. Use textual `Deps` after fixing orphans/forward refs, then regenerate diagram from the graph.

## Per-PR Deps Inventory

| PR | Block | Line | Declared deps |
|---|---|---:|---|
| #1 | B1 | 1731 | none |
| #2 | B1 | 1732 | #1 |
| #3 | B1 | 1733 | #2 |
| #4 | B1 | 1734 | #3 |
| #5a | B1 | 1735 | #3 |
| #5b | B1 | 1736 | #5a |
| #6.5 | B1 | 1738 | #6 |
| #8 | B1 | 1740 | none |
| #9 | B1 | 1741 | none |
| #11 | B1 | 1743 | none |
| #12 | B1 | 1744 | #5b |
| #13 | B1 | 1745 | #12 |
| #14 | B1 | 1746 | #15.5 |
| #15 | B1 | 1747 | #14 |
| #15.5 | B1 | 1748 | none |
| #16 | B2 | 1758 | #4 |
| #17 | B2 | 1759 | #16 |
| #18 | B2 | 1760 | #14, #15, #15.5 |
| #19 | B2 | 1761 | #2 |
| #20 | B2 | 1762 | #5b |
| #21 | B2 | 1763 | #3 |
| #22 | B2 | 1764 | #5b, #20 |
| #23 | B2 | 1765 | #21, #1.0 |
| #24 | B2 | 1766 | #21 |
| #25 | B2 | 1767 | none |
| #26 | B2 | 1768 | #5b |
| #27 | B2 | 1769 | none |
| #28 | B2 | 1770 | #27 |
| #29 | B2 | 1771 | #4, #16, #17 |
| #30 | B2 | 1772 | none |
| #31 | B2 | 1773 | #21 |
| #32 | B2 | 1774 | #31 |
| #33 | B2 | 1775 | none |
| #34 | B2 | 1776 | none |
| #35 | B2 | 1777 | #36 |
| #36 | B2 | 1778 | #2 |
| #37 | B2 | 1779 | #5b, #29 |
| #38 | B3 | 1789 | #4 |
| #39 | B3 | 1790 | #38 |
| #40 | B3 | 1791 | #36 |
| #41 | B3 | 1792 | #36 |
| #42 | B3 | 1793 | #36, #41 |
| #43 | B3 | 1794 | #36, #35 |
| #44 | B3 | 1795 | #42 |
| #45 | B3 | 1796 | #4 |
| #46 | B3 | 1797 | #3 |
| #47 | B3 | 1798 | #21 |
| #48 | B3 | 1799 | #12, #44, #5b |
| #6 | B4 | 1809 | none |
| #7 | B4 | 1810 | none |
| #10 | B4 | 1811 | none |
| #55 | B4 | 1818 | #5b, #2, #11, #56 |
| #56 | B4 | 1819 | #43 |
| #57 | B4 | 1820 | #27, #28 |
| #58 | B4 | 1821 | #57 |
| #60 | B4 | 1822 | #2 |
| #61 | B4 | 1823 | #2 |
| #62 | B4 | 1824 | #5b, #18 |
| #64 | B4 | 1825 | #12, B5-C2 |
| #65 | B4 | 1826 | none |
| B5-U1 | B5a | 1856 | none |
| B5-U2 | B5a | 1857 | B5-U1 |
| B5-U3 | B5a | 1858 | B5-U1 |
| B5-U4 | B5a | 1859 | B5-U1 |
| B5-U5 | B5a | 1860 | #39 |
| B5-U6 | B5b | 1861 | #42 |
| B5-U7 | B5b | 1862 | #42 |
| B5-U8 | B5b | 1863 | B5-U2 |
| B5-U9 | B5b | 1864 | #42 |
| B5-U10 | B5b | 1865 | #42 |
| B5-U11 | B5b | 1866 | #42, #27 |
| B5-U12 | B5b | 1867 | #42 |
| B5-U13 | B5b | 1868 | #48 |
| B5-U14 | B5b | 1869 | B5-U13 |
| B5-U-NAV | B5a | 1870 | B5-U1 |
| B5-U15 | B5b | 1871 | B5-U1 |
| B5-U16 | B5b | 1872 | B5-U1 |
| B5-U17 | B5b | 1873 | B5-U11 |
| B5-U18 | B5b | 1874 | B5-U16 |
| B5-U19 | B5b | 1875 | B5-U1 |
| B5-U20 | B5b | 1876 | B5-U13 |
| B5-U21 | B5b | 1877 | B5-U1 |
| B5-U22 | B5b | 1878 | B5-U1, B5-U15 |
| B5-C1 | B5b | 1886 | #5a, #5b |
| B5-C2 | B5b | 1887 | #12, #48 |
| B5-C3 | B6 | 1888 | #55, #56 |
| B5-C5 | B6 | 1890 | #5b |
| B5-C6 | B5b | 1891 | #3, #4, #14 |
| B5-C7 | B5b | 1892 | #21 |
| B5-C8 | B5b | 1893 | #3, #21 |
| B5-C9 | B5b | 1894 | #21 |
| B5-C10 | B5b | 1895 | #21 |
| B5-C11 | B5b | 1896 | #21 |
| B5-C12 | B5b | 1897 | #5b, #21 |
| B5-D2 | B5b | 1906 | B5-D1 |
| B5-D3 | B5b | 1907 | B5-D2 |
| B5-D4 | B5b | 1908 | B5-D3 |
| B5-D5 | B5b | 1909 | #7 |
| B5-D6 | B5b | 1910 | B5-D4 |
| B5-D7 | B5b | 1911 | B5-D4 |
| B5-D8 | B5b | 1912 | B5-D7 |
| B5-T1 | B5b | 1920 | #6.5, #19, #29 |
| B5-T1b | B5b | 1921 | #6.5, B5-T1 |
| B5-T2 | B6 | 1922 | #2 |
| B5-T3 | B6 | 1923 | #2 |
| B5-T4 | B5b | 1924 | #42 |
| B5-T5 | B6 | 1925 | #21 |
| B5-T6 | B6 | 1926 | B5-T2 |
| B5-T7 | B6 | 1927 | B5-T1, B5-T2 |
| B5-CI1 | DEFERRED-3.4 | 1928 | B5-T2 |
| B5-T8 | B5b | 1929 | B5-U-NAV |
| B5-T9 | B5b | 1930 | B5-U16, B5-T1 |
| B5-T10 | B5b | 1931 | B5-T1 |
| B5-A1 | B5b | 1939 | #36, #43 |
| B5-A2 | B5b | 1940 | #42 |
| B5-A3 | B5b | 1941 | #41 |
| B5-A4 | B5b | 1942 | #43 |
| B5-DEP2 | B6 | 1950 | #2 |
| B5-DEP3 | B6 | 1951 | B5-DEP2 |
| B5-DEP4 | DEFERRED-3.4 | 1952 | B5-DEP3 |
| B5-DEP5 | DEFERRED-3.4 | 1953 | B5-DEP4 |
| B5-DOC1 | B6 | 1961 | #55 |
| B5-DOC2 | B6 | 1962 | none |
| B5-DOC3 | B6 | 1963 | none |
| B5-DOC4 | B6 | 1964 | #4 |
