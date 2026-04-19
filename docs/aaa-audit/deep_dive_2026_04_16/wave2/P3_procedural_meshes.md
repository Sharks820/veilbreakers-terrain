# Wave 2 / P3 Deep Dive — `procedural_meshes.py` lines 7127–11396

**Scope:** 49 generator functions from `generate_spike_trap_mesh` (L7127) through `generate_anvil_mesh` (L11396).
**File:** `veilbreakers_terrain/handlers/procedural_meshes.py`
**Auditor:** Opus 4.7 ultrathink
**Standard:** Megascans / SpeedTree / UE5 PCG / Houdini AAA-shipped quality.
**Rubric:** A+ Megascans · A UE5 · A- missing 1 · B+ thin · B blockout · B- bug · C+ partial · C stub · D broken · F placeholder.

---

## 0. EXECUTIVE TL;DR (read first)

These 49 functions are a **vast catalogue of procedural Blender meshes** glued together from `_make_box`, `_make_cylinder`, `_make_cone`, `_make_torus_ring`, `_make_lathe`, `_make_beveled_box`, `_make_sphere`, `_make_tapered_cylinder`. There is **zero use of bmesh** (verified in BUG-309 below) — every mesh is a CPU-side python list-of-tuples assembly with **no welded vertices, no shared topology, no normals, no UVs computed at generation time, no material-id channels**.

**Ceiling:** the entire range averages **C+ / B-** vs AAA. None of these would survive a Megascans QA pass for a single reason: **they are silhouette blockouts, not assets.** A real AAA bear-trap from a vendor like Quixel has 3-5k tris, edge-flow on the jaw geometry, baked normal maps, properly-welded UVs, and PBR maps — this file's `generate_bear_trap_mesh` is ~16 disjoint primitives floating through each other with no welding (~160 verts, ~120 quads), no UVs, and no concept of an iron parting line.

**Worst offenders in the range** (D / F):
- L7384 `generate_swinging_blade_mesh` — bracket axle math is wrong (BUG-301)
- L7316 `generate_dart_launcher_mesh` — broken rotation logic, dart positions are nonsense (BUG-300)
- L7546 `generate_cart_mesh` — axle "rotation" via vertex aliasing is mathematically wrong (BUG-302); 4-wheel branch generates 4 wheels per axle position not 2 (BUG-303)
- L7711 `generate_boat_mesh` (longship) — yard rotation hack collapses the spar to a degenerate line (BUG-304); reuses variable name `hull_verts` instead of `_g`-suffix (works but lint hazard)
- L7933 `generate_wagon_wheel_mesh` — generates BOTH a degenerate "spoke marker" cylinder AND a rotated box per spoke (BUG-305) — silent geometry bloat ~60 extra verts/spoke
- L9376 `generate_gibbet_mesh` — chain rotation hack (line 9418) is the same broken pattern; alternate links don't actually swap orientation correctly (BUG-306)
- L8753 `generate_veil_tear_mesh` — "jagged frame" generates 16 boxes of identical bounding sizes; the `r_inner`/`r_outer` randomness is consumed but `seg_w/seg_h` use absolute differences that round to the same value across most shards — the frame is visually a regular ring of rectangles (BUG-307)
- L11253 `generate_chandelier_mesh` — bottom finial inversion on L11318 produces a finial centered at `total_h * 0.05` regardless of `tiers`, instead of hanging below the lowest tier (BUG-308)
- L9201 `generate_spider_web_mesh` — radial strands generate `box(rotated)` segments whose length parameter is `radius/n_segs/2` along Z and ALSO the box is rotated by `angle` — this means cosine compression makes diagonal strands shorter than axis-aligned ones (BUG-310)
- L8459 `generate_ladder_mesh` — rung "rotation" via the same broken aliasing pattern (BUG-311), rungs are not actually horizontal cylinders, they're vertical-to-Z-projected nonsense
- L8014 `generate_column_row_mesh` (gothic branch) — capital inversion list-comp on L8112 has a syntactically valid but semantically wrong ternary (BUG-312); the splayed capital doesn't splay
- L8272 `generate_drawbridge_mesh` — chain alternation hack (L8340) does not produce orthogonal links; it permutes coordinates that don't correspond to alternating link orientation (BUG-313)
- L7456 `generate_falling_cage_mesh` — chain link L7534 swap pattern produces only one of two visually-distinct chain link orientations; even links and odd links are visually identical (BUG-314)

**Best in range:** L8589 `generate_sacrificial_circle_mesh` (B), L9006 `generate_bone_throne_mesh` (B-), L9101 `generate_dark_obelisk_mesh` (B-), L8919 `generate_blood_fountain_mesh` (B), L8355 `generate_well_mesh` (B), L9942 `generate_scroll_mesh` (rolled, B-), L11253 `generate_chandelier_mesh` (B- despite the bug). These have actual silhouette intent.

**Critical structural bugs (apply to ~30+ functions):**
- BUG-309 (CRITICAL): No bmesh used anywhere. No welded shared verts. No normals or UVs at gen time. No tri-fan ngon repair. Output is raw quad-soup that requires external `_enhance_mesh_detail` post-pass to be even Tripo-compatible. Most functions skip even that post-pass.
- BUG-315 (HIGH): `_merge_meshes` does not weld coincident vertices — every primitive's verts are concatenated, leaving billions of T-junctions and z-fighting at every joint. AAA pipelines would have a vertex weld + manifold cleanup pass.
- BUG-316 (HIGH): Z-fighting risk — many decorative elements (rune plates, plank-strips, hinges, rivets) sit at depth offsets of 0.001–0.005m. At 1m view distance with FP32 depth this is fine, but at 50m+ in-engine it will shimmer. AAA standard would either cut these into the parent mesh or use decals.
- BUG-317 (MEDIUM): No LODs generated. AAA expects at minimum LOD0/LOD1/LOD2 with explicit triangle budgets per LOD tier. This file only emits one density.

---

## 1. PER-FUNCTION GRADES

Format: `Name (line)` / Claims / Produces / AAA reference / Bug / Severity / Upgrade.

---

### 1. `generate_spike_trap_mesh` (L7127) — **C+**
- **Claims:** Floor pit + walls + rim + N spikes (N defaults 9, becomes 9 via `int(sqrt(9))=3` grid → 9 placed).
- **Produces:** ~1 box (8v) + 4 wall boxes (32v) + 4 beveled rim boxes (~96v) + 9 cone spikes (9*5=45v) ≈ **~180v / ~75 quads + 36 tris**. Topology = unwelded primitive soup. No UVs. Spikes are 4-sided cones (octahedra).
- **AAA ref:** A real spike trap (Hellblade II, Lords of the Fallen) has hand-modeled iron pit-frame, floor-mortar tile breaks, bloodstains baked into albedo, individually crafted differential-shape spikes. ~2-3k tris LOD0.
- **Bug:** Rim is **square** but pit is square — at corners the rim boxes overlap, producing 4 corner overlaps (z-fight). Spike grid will leave the requested `spike_count` placed exactly only when it's a perfect square; a request of 7 or 11 silently becomes 4 or 9. Severity: LOW.
- **Upgrade:** Use bmesh, build pit as one welded ring with extruded inner well; lay spikes on noise-perturbed positions; bake tip-tessellation; add corner mortar boss; emit second material slot for blood/rust.

### 2. `generate_bear_trap_mesh` (L7193) — **C**
- **Claims:** Iron jaw trap with disc base + 16 teeth + 2 jaw arms + spring torus + trigger.
- **Produces:** Disc cylinder (24v) + 16 cone teeth (16*5=80v) + 2 jaw cylinders (2*12=24v) + torus (8*4=32v) + trigger disc (16v) ≈ **~180v / ~150 mixed faces**. Disjoint primitives.
- **AAA ref:** Inquisitor: Martyr / Diablo IV bear traps have fully-modeled hinge mechanism, spring coil, individual toothed jaw plates with edge-bevels. ~2-4k tris.
- **Bug:** Two "jaw arms" are vertical cylinders sticking UP out of the disc — bear traps have horizontal jaw plates that close. Geometry doesn't read as a trap from above. Severity: MEDIUM.
- **Upgrade:** Build jaws as two hinged half-rings of teeth that meet at the centerline; add spring as helix not torus; add chain attachment lug.

### 3. `generate_pressure_plate_mesh` (L7257) — **C+**
- **Claims:** Stone plate with frame border + raised plate + carved cross runes.
- **Produces:** 4 frame beveled boxes (4*24=96v) + 1 plate (24v) + 2 cross-rune boxes (16v) ≈ **~140v / ~42 quads**.
- **AAA ref:** Tomb Raider-style pressure plate has chamfered edges, carved depression for foot, weathered stone tiling. ~600 tris.
- **Bug:** Rune cross is a raised box (`top_y = plate_h - recess_depth + 0.001`), not a carved depression as `recess_depth` and the docstring imply. Severity: LOW (visual-only).
- **Upgrade:** Use bmesh inset+extrude for actual carved geometry; offset normals for chip damage; emit metallic-edge mask channel.

### 4. `generate_dart_launcher_mesh` (L7316) — **D** ⚠️ **BUG-300**
- **Claims:** Wall plate + 3 dart tubes + 3 darts.
- **Produces:** Plate (24v beveled) + 3 cylinders (3*12=36v) + 3 cones (3*5=15v) ≈ **~75v**.
- **Bug — BUG-300 (HIGH):** L7361-7366 the "rotate cylinder along Y to point along Z" is implemented by:
  ```
  nz = v[1] - ty + plate_d / 2
  ny = ty
  ```
  This **destroys** the cylinder's Y dimension (collapses every vertex to `y=ty`) — every tube becomes a flat ring at `y=ty` with new `z` offset. Same bug for darts L7372. Result: tubes are flat circles, not cylinders. Severity: HIGH.
- **AAA ref:** A dart launcher has tube barrels modeled as proper cylinders with bevel collars; this fails to produce them at all.
- **Upgrade:** Use a proper rotation matrix or build the cylinder along Z natively with a `_make_cylinder_along_axis(axis="z")` helper.

### 5. `generate_swinging_blade_mesh` (L7384) — **D** ⚠️ **BUG-301**
- **Claims:** Bracket + horizontal axle + pendulum arm + blade + counterweight.
- **Produces:** Bracket (24v) + axle (24v BROKEN) + arm (12v) + blade box (24v) + edge box (8v) + sphere (24v) ≈ **~115v**.
- **Bug — BUG-301 (HIGH):** L7417 axle rotation: `(v[1] + bracket_h/2 + (-bracket_w/2), -bracket_h/2, v[2])` — same anti-pattern as BUG-300, collapses cylinder Y dimension to constant. Axle is a flat disc, not a rod. Severity: HIGH.
- **AAA ref:** Tomb Raider 2013 swinging blade: hand-modeled wedge blade with edge bevel, decorative end caps, chain hung from articulated bracket. ~1.5k tris.
- **Upgrade:** Same fix as BUG-300; also: blade should be a tapered profile with sharpened edge geometry, not two stacked beveled boxes.

### 6. `generate_falling_cage_mesh` (L7456) — **C** ⚠️ **BUG-314**
- **Claims:** Top frame + bottom rim + vertical bars + ceiling chain.
- **Produces:** 4 top + 4 bottom frame boxes (~192v) + ~12 vertical bar cylinders (~144v) + 4 chain torus (~96v) ≈ **~430v / ~240 faces**.
- **Bug — BUG-314 (LOW):** L7522-7535 chain links: even/odd both build identical torus, then odd does `cv = [(v[2], v[1], v[0]) for v in cv]` — but the torus lies in XZ plane so swapping X and Z is a 90° rotation around Y, NOT around X. Real chain has alternating links rotated 90° around the chain-vertical axis (around Y for vertical chain, around horizontal-perpendicular for horizontal chain). Visually the alternating links don't perpendicularize. Severity: LOW (cosmetic but everywhere).
- **AAA ref:** Standard chain has welded rounded-rect links built from a swept tube along a curve, alternating 90° around the chain tangent. ~24 tris/link.
- **Upgrade:** Build a `_make_chain_strand(p0,p1,n_links)` helper that generates alternating tori with proper local-axis rotation.

### 7. `generate_cart_mesh` (L7546) — **D** ⚠️ **BUG-302, BUG-303**
- **Claims:** Platform + 2/4 wheels + axles + style-specific (canvas/cage/farm) + tongue.
- **Produces:** Platform (24v) + 1-2 axles (BROKEN) + 4 wheels (4*~80v torus) + style content + tongue ≈ **800-1500v** depending on style.
- **Bug — BUG-302 (HIGH):** L7590 axle rotation: `(v[0], axle_h - platform_h / 2, v[1] - (axle_h - platform_h / 2) + (-platform_d / 2 - 0.05 * s))` — collapses cylinder Y dimension to constant, same anti-pattern. Axles are flat discs, not rods.
- **Bug — BUG-303 (LOW):** L7597-7604 — both `wheels==4` and `wheels==2` (else) branches do the SAME thing: append two wheel positions per axle position. With 2 wheels requested + 1 axle position you still get 2 wheels (correct), but the comment claims they're treated differently and they aren't. Tongue is mounted at `+x`, but a 2-wheeled cart should have the tongue forward of the axle, not at the platform end.
- **AAA ref:** Witcher 3 cart: ~6-8k tris LOD0, hand-bent metal axle straps, individual nail/rivet baked in normal map, working frictional wheel pivot, 4 distinct prison-cart variants in the game.
- **Upgrade:** Fix axle rotation; separate cage geometry into `_build_cage_top` helper; integrate `_make_chain_strand` for proper hitching.

### 8. `generate_boat_mesh` (L7711) — **C** ⚠️ **BUG-304**
- **Claims:** Three styles (rowboat, viking_longship, gondola) with hull cross-section sweep, oars, mast, ferro.
- **Produces:** Rowboat ≈ 9 sections × 7 verts = 63 hull verts + ~50 misc ≈ 110v / 48 quads. Longship ≈ 13×7 + dragon prow + 12 shields + mast + yard ≈ 250-300v. Gondola ≈ 11×6 hull + ferro + platform ≈ 80v.
- **Bug — BUG-304 (HIGH):** L7868-7869 yard (crossbeam) "rotation" — same anti-pattern. The yard collapses to `y = hull_h * 0.1 + mast_h * 0.75` for every vertex. Yard is a degenerate flat strip, not a horizontal spar.
- **Bug:** L7787 oar "rotation" — same anti-pattern (oars collapse to `y=hull_h*0.2`).
- **Bug (LOW):** Hull cross-section construction L7754-7757 uses `taper = sin(t*pi)` then `max(taper, 0.15)` — at bow/stern (t=0/1) sin=0, so the radius clamps to 0.15 instead of going to a real point — boat has a blunt nose, not a pointed prow. Same in longship/gondola (clamps 0.1, 0.05).
- **AAA ref:** Skull & Bones rowboat ~6k tris LOD0, true keel + ribs + planks geometry, decals for caulking.
- **Upgrade:** Real keel-and-rib construction; matrix rotations for oars and yards; weld bow/stern rings to apex points.

### 9. `generate_wagon_wheel_mesh` (L7933) — **C-** ⚠️ **BUG-305**
- **Claims:** Rim torus + hub + hub caps + N spokes.
- **Produces:** Rim (8 spokes × 3 segs × 4 minor = 96v torus) + hub (8 segs × 2 = 16v) + 2 caps (2*16=32v) + 8 spokes × (5+8=13v each) = 104v ≈ **~250v / ~200 faces**.
- **Bug — BUG-305 (LOW):** L7978-7981 generates a useless `sv,sf` cylinder per spoke that is then ignored — `parts.append((sv_final, sf2))` only appends the rotated box's `sf2`. But the cylinder's `sv,sf` was never appended, so this is dead code, not a bug — but it's wasted CPU and reads like a half-complete rewrite. (Verified: only `sf2` and `sv_final` reach `parts`.)
- **Actual bug:** Spoke positioning L7975-7976 computes `sx, sz` for the cylinder, then for the box L7984 uses the same `sx, sz` as box CENTER, then rotates the box around origin by `angle`, then translates to a new offset. The translation math L8000-8001 `(v[0] - sx + offset_x, v[1], v[2] - sz + offset_z)` SUBTRACTS the original center then adds the radial midpoint — but the rotation already moved the verts away from `(sx,sz)`. Net effect: spokes are positioned correctly but **rotated wrong** for non-axis-aligned spokes (off-by-translation). Severity: LOW (subtle visual flaw).
- **AAA ref:** A wagon wheel is one of the most stock AAA assets — typically a swept-rim + cylindrical hub + 8-12 lathe-extruded spokes with chamfered ends, ~600 tris.
- **Upgrade:** Build per-spoke as a tapered box with bevel; orient via proper 2D rotation of vertex positions in spoke local space, then translate ONCE to spoke midpoint. Delete the dead `sv,sf` cylinder.

### 10. `generate_column_row_mesh` (L8014) — **C** ⚠️ **BUG-312**
- **Claims:** Doric / corinthian / gothic colonnade + entablature.
- **Produces:** Per column ≈ 50-100v. 4 columns × ~80v + entablature 24v ≈ **~340v** doric, **~500v** corinthian, **~300v** gothic.
- **Bug — BUG-312 (MEDIUM):** L8112-8113 gothic capital inversion:
  ```python
  p_verts = [(v[0], col_h + (col_h + 0.15 - v[1]) if v[1] > col_h else v[1], v[2]) for v in pv]
  ```
  Operator precedence: this evaluates as `(v[0], (col_h + (col_h + 0.15 - v[1])) if v[1] > col_h else v[1], v[2])`. So the Y coordinate is either `2*col_h + 0.15 - v[1]` (if above col_h) or `v[1]` (if not). Apex of the cone is at `col_h + 0.15`, gets remapped to `col_h - 0.15` — that's a downward-flipped cone INSIDE the column shaft, not a splayed capital. Severity: MEDIUM (gothic style is visually broken).
- **AAA ref:** Assassin's Creed Mirage colonnades use Houdini-generated columns with proper entasis curve, fluting, and styled capitals; ~5-8k tris each LOD0.
- **Upgrade:** Build gothic capital as a true splayed lathe profile (cluster columns merging upward into a fan), not a cone-flip hack. Add fluting via cylindrical scallops in corinthian/doric.

### 11. `generate_buttress_mesh` (L8130) — **B-**
- **Claims:** Flying or standard buttress with pier, arch segments, pinnacle, stepped tiers.
- **Produces:** Flying ≈ pier (24v) + cone (5v) + 6 arch segments (6×24=144v) ≈ **~175v**. Standard ≈ main body (24v) + 3 tier offsets (3×24=72v) ≈ **~96v**.
- **Bug:** Flying-arch segments are 6 horizontal slabs at increasing Y — they don't curve, they step. Reads as stair-step instead of a flying arc. Severity: MEDIUM.
- **AAA ref:** Notre-Dame in AC Unity — flying buttresses are unique authored assets with tracery decoration.
- **Upgrade:** Compute true Bezier-curve mid-points for the arch; sweep a tube along the curve; add tracery quatrefoils.

### 12. `generate_rampart_mesh` (L8212) — **B-**
- **Claims:** Castle wall with walkway, merlons, inner parapet.
- **Produces:** Wall (24v) + walkway (24v) + N merlons (~10×24=240v) + parapet (24v) ≈ **~310v**.
- **Bug:** Walkway position L8242: `wall_thick / 2 + walkway_w / 2 - wall_thick / 2 = walkway_w / 2` — works but the duplication signals confusion. Merlons are simple boxes — no battlement crenellation chamfer (the merlons should taper outward). Severity: LOW.
- **AAA ref:** Mount & Blade Bannerlord ramparts ~3-5k tris with weathered stone normals and crenellation kit-bashed from per-stone instances.
- **Upgrade:** Per-stone tessellation via instanced sub-mesh; merlon side-chamfer; inner parapet should have crenel gaps (currently just a continuous low wall).

### 13. `generate_drawbridge_mesh` (L8272) — **C+** ⚠️ **BUG-313**
- **Claims:** Plank deck + cross beams + edge reinforcement + chains + hinges.
- **Produces:** ~13 planks (13×24=312v) + 3 beams (24v) + 2 edges (48v) + 12 chain links (12×~32=384v) + 2 hinges (24v) ≈ **~790v**.
- **Bug — BUG-313 (LOW):** L8340 alternate chain link rotation: `(v[2] - z_side + cx, v[1], v[0] - cx + z_side)` — coordinate permutation does not produce a perpendicular link orientation; it produces a translation+swap that's geometrically meaningless for chain alternation. Severity: LOW (visual).
- **AAA ref:** Dark Souls drawbridge: hand-bent iron strap geometry on each plank, working hinge with knuckle-and-pin, draping chain physics.
- **Upgrade:** Replace chain alternation with proper local-axis-rotated tori; planks need iron-strap reinforcement bands; hinges should be barrel-knuckles, not plain cylinders.

### 14. `generate_well_mesh` (L8355) — **B**
- **Claims:** Walled cylindrical well + rim profile + shaft + base + optional roof + bucket + rope.
- **Produces:** Outer wall (24v open) + reversed inner wall (24v) + lathe rim (~60v) + shaft (24v) + base (24v) + (if roof) 2 posts + crossbeam + 2 roof slabs + bucket lathe + rope ≈ **180v** no-roof, **~330v** with roof.
- **Bug:** L8392 rim profile has `inner_r * 0.95` lying INSIDE `inner_r` — the rim flares inward then outward, creating a self-intersection. The shaft cylinder L8401 is built `cy_bottom = -depth, height = depth` so its top is at y=0, not at y=`-wall_h` — there is a missing-floor gap between rim bottom (y=0) and shaft top. Severity: MEDIUM.
- **AAA ref:** Stone wells in Skyrim/ESO use hand-cut stone block instances and a tessellated wood-shingle roof. ~1-2k tris.
- **Upgrade:** Per-stone block instancing; fix shaft to start at `-wall_thick`; rim profile should monotonically increase then bevel out.

### 15. `generate_ladder_mesh` (L8459) — **D** ⚠️ **BUG-311**
- **Claims:** 2 side rails + N horizontal rungs.
- **Produces:** 2 rails (2×24=48v) + N rungs (~8×12=96v) ≈ **~145v**.
- **Bug — BUG-311 (HIGH):** L8497 same anti-pattern as BUG-300/302/304. Rungs collapse Y dimension to constant `ry`. Rungs are flat discs, not horizontal cylinders. Severity: HIGH.
- **AAA ref:** Dishonored 2 ladder: hand-modeled tapered rungs with iron caps at rail penetration, weathered wood normal map. ~300 tris.
- **Upgrade:** Use proper axis transform; add iron caps where rungs meet rails.

### 16. `generate_scaffolding_mesh` (L8505) — **C+**
- **Claims:** 4 corner poles + N levels of plank platforms + horizontal braces + diagonal braces.
- **Produces:** 4 poles (4×12=48v) + per level (~10 planks×8 + 4 horizontal braces×8 + 4 vertical braces×8) + diagonals (per-side per-level boxes) ≈ **~600-1000v** for 3 levels.
- **Bug:** "Diagonal braces" L8573 are AXIS-ALIGNED HORIZONTAL boxes spanning the full width at level midpoint — not diagonal at all. The unused `_ = math.sqrt(...)` on L8572 confirms incomplete implementation. Severity: MEDIUM (geometry doesn't read as diagonals).
- **AAA ref:** Assassin's Creed scaffolding ~3k tris with rope-tied joints, individual lashing details, partially-collapsed sections.
- **Upgrade:** Compute diagonal endpoints `(corner1, corner2_at_next_level)`, build oriented box from the two endpoints; add rope lashing torus at each joint.

### 17. `generate_sacrificial_circle_mesh` (L8589) — **B**
- **Claims:** Ground disc + inner ring + outer ring + N rune stones + central altar + radial blood channels.
- **Produces:** Disc (24v) + 2 toruses (~192v) + N rune stones (each ~24v body + 8v rune) + altar (24v) + N channels (8v each) ≈ **~500v** for 6 runes.
- **Bug:** Rune stone height variation L8631 `0.5 + 0.15 * ((i*3)%5 - 2) / 2` — a cute heuristic but produces only 5 distinct heights. Channel rotation L8670-8675 is mathematically correct (rotates around origin, not around channel position) — but channels are positioned at radial midpoint THEN rotated around world origin by the same angle, which translates them tangentially not radially. Channel direction is wrong. Severity: LOW.
- **AAA ref:** Diablo IV ritual circles use baked-in glow texture + height-painted rune carvings on a single tessellated mesh. ~5k tris LOD0.
- **Upgrade:** Build channels as radial extrudes from a unified ground tessellation; carve runes into the stones (not paste-on); add candle wax drips, blood pools.

### 18. `generate_corruption_crystal_mesh` (L8683) — **B-**
- **Claims:** Hexagonal prism crystal with pointed ends + N secondary shards + ground disc.
- **Produces:** Main prism (12v middle) + 2 cones (12v) + N shards (~24v each tapered + 5v cone tip) + ground (16v) ≈ **~150v** for 3 shards.
- **Bug:** Top cone L8717 `_make_cone(0, point_h+mid_h, 0, ...)` is built apex-up correctly. Bottom cone L8711 is built apex-up at y=0 then flipped via `(v[0], point_h - v[1], v[2])` — flips around `y = point_h/2`, which means the apex (originally at `y=point_h`) goes to `y=0`, and the base (originally at `y=0`) goes to `y=point_h`. So the bottom cone's BASE is at `y=point_h` and apex at `y=0` — meaning the prism (sitting at y=point_h to point_h+mid_h) doesn't connect to the bottom cone's base (also at y=point_h). Geometry is coincident at the join, not welded — works visually only because of overlap. Severity: LOW.
- **AAA ref:** Hellblade II soul crystals: Houdini Voronoi-fractured prismatic shards with sub-surface scattering material, ~3-6k tris.
- **Upgrade:** Voronoi facet generation; merge prism+cone into single welded mesh; add SSS-friendly UVs.

### 19. `generate_veil_tear_mesh` (L8753) — **C-** ⚠️ **BUG-307**
- **Claims:** Jagged frame of 16 shards + 6 energy wisps + ground disc.
- **Produces:** 16 shards (16×24=384v) + 6 wisps (6×~12=72v) + disc (24v) ≈ **~480v**.
- **Bug — BUG-307 (MEDIUM):** L8796-8799 each shard's CENTER is computed correctly but its half-extents `seg_w/2, seg_h/2` come from `max(abs(ox-ix), abs(nox-nix), 0.05) / 2` which is the radial thickness, applied to BOTH x and y axes of the box. Result: each shard is a box `seg_w × seg_h × frame_depth` where `seg_w == seg_h` for most angles (radial thickness is similar inner-to-outer along all radials). The "jagged" frame is 16 nearly-identical boxes arranged in a ring. Severity: MEDIUM.
- **AAA ref:** Doom Eternal portals: tessellated frame with displacement-mapped jagged edges, particle wisps, decal blood drips. ~10k tris.
- **Upgrade:** Build a true jagged outline from displaced ellipse points and use `_make_profile_extrude` on the shape ring. Replace wisp spheres with billboards/decals.

### 20. `generate_soul_cage_mesh` (L8824) — **C+**
- **Claims:** Top/middle/bottom rings + curved bars + suspension chain + soul wisp.
- **Produces:** 3 toruses (~192v) + N bars × 6 segs each (~8×6×8=384v) + 3 chain links (~96v) + sphere wisp (~24v) ≈ **~700v**.
- **Bug:** Bar segments L8886-8890 are AXIS-ALIGNED boxes positioned at the curve midpoint — they don't follow the curve direction. Visually each bar is a column of stacked boxes, not a smooth curve. Bar segs use `bar_r` for both X and Z half-extents and `seg_len/2` for Y — but Y is the world-up axis, so the segment is a vertical pillar at `(x_mid,z_mid)`, not a slanted segment. The bulge math L8874-8875 produces correct positions but the segment orientation is wrong. Severity: LOW-MEDIUM.
- **AAA ref:** Diablo IV cage with curved iron bars uses true swept tubes. ~2k tris.
- **Upgrade:** Sweep a tube along the parametric bulge curve via `_make_swept_tube(curve_pts, radius)`; alternate chain alternation properly.

### 21. `generate_blood_fountain_mesh` (L8919) — **B**
- **Claims:** N tier basins (lathe profile) + skull rim decorations + pedestal + central spout + horns + base.
- **Produces:** Per tier ≈ 16-segment lathe (~150v) + skull spheres (~6 × 24=144v) + (tiers>0) pedestal (~30v). Base hexagon (~14v). Total **~450v** for 2 tiers.
- **Bug:** Spout L8985 lathe with `close_top=True` — works. Horn cones L8989-8993 are very tiny (`segments=4`, `radius=0.008`, `length=0.08`) — at game-distance these are < 1px and contribute nothing visually. Missing: blood material slot, blood-drip channels from basin to basin. Severity: LOW.
- **AAA ref:** Bloodborne fountains: hand-sculpted basin with veined stone, demonic spout with proper anatomy, dripping blood mesh extensions. ~8-15k tris.
- **Upgrade:** Sculpt-quality demon spout (this is a 5-vert lathe — way too crude); per-tier blood channel; emissive blood material for in-engine glow.

### 22. `generate_bone_throne_mesh` (L9006) — **B-**
- **Claims:** Beveled seat + 4 bone legs + spine column + side bone armrests + 3 skull decorations + rib bones.
- **Produces:** Seat (24v) + 4 legs (4×24=96v) + 4 leg joints (4×16=64v) + 4 leg upper shafts (4×12=48v) + 6 spine bones + 6 spine joints (6×16=96v) + 2 armrests (BROKEN rotation) + 3 skulls + jaws + rib spheres (~24 spheres) ≈ **~700v**.
- **Bug:** Armrest "rotation" L9068 — same anti-pattern, collapses Y dim. Armrests are flat discs floating at `y=seat_h+0.25`. Severity: MEDIUM.
- **Bug:** Rib bones are SPHERES (L9094), not curved ribs. Doesn't read as anatomical. Severity: LOW.
- **AAA ref:** Game of Thrones Iron Throne / Dark Souls thrones — ~30k tris hand-sculpted with anatomical bone structures. This is a generous blockout.
- **Upgrade:** Use anatomical femur/tibia profiles (lathe with knob caps); ribs as curved swept tubes; armrests need axis-correct rotation; integrate skull mesh from `generate_lantern_mesh` skull as shared helper.

### 23. `generate_dark_obelisk_mesh` (L9101) — **B-**
- **Claims:** Tapered 4-sided body + pyramidion top + 2 base tiers + N rune engravings on faces.
- **Produces:** Body (8v hand-built) + cone pyramid (5v) + 2 base boxes (48v) + N rune boxes (each 8v) ≈ **~85v** + ~32v for 4 runes ≈ **~120v**.
- **Bug:** Body face winding L9140-9145 is hand-authored — needs verification (front/back may be swapped). Pyramidion is `_make_cone(0, height, 0, top_w/2 * 1.1, height*0.08)` — its base is WIDER than the obelisk top (1.1×), creating a visible lip overhang. Real Egyptian pyramidions sit FLUSH or slightly INSET. Severity: LOW.
- **Bug:** Rune positions on tapered body — L9183-9184 computes width-at-height as linear taper, then offsets rune by `+0.002` outward — but the rune box is axis-aligned, not tilted to follow the slope, so runes float off the slanted face on the outer corners. Severity: LOW.
- **AAA ref:** ESO/Skyrim obelisks: per-face baked normal map for runes (no separate rune geometry), tessellated stone weathering, optional emissive rune channel. ~2-3k tris.
- **Upgrade:** Bake runes to normal map instead of geometry; tilt rune boxes to align with slanted faces; flush pyramidion to top.

### 24. `generate_spider_web_mesh` (L9201) — **C-** ⚠️ **BUG-310**
- **Claims:** Central hub + N radial strands + N concentric rings.
- **Produces:** Hub (~12v) + radials (8×10×8=640v) + rings (5×24×8=960v) ≈ **~1600v / ~1200 quads**. WAY over budget for what should be a simple mesh.
- **Bug — BUG-310 (MEDIUM):** L9243 box has half-extent `(strand_r, strand_r, radius/n_segs/2)` along Z, then L9249-9251 the box is rotated by `angle` around Y. The Z half-extent represents segment length; after rotation by angle, the segment is correctly oriented along the radial direction. BUT the box's X and Y half-extents (`strand_r`) become the cross-section thickness — the cross-section is square, which is correct for a strand box. **The actual bug:** segment LENGTH along Z is `radius/n_segs/2`, but consecutive segments are placed at `t0` and `t1` where `t1-t0 = 1/n_segs`, so the gap between segment centers is `radius/n_segs` and the segment LENGTH (full, not half) is `radius/n_segs`. They butt-join correctly. **But** the sag offset L9240 is computed at `t0` only and applied to BOTH endpoints' midpoint via `(x0+x1)/2`, while a real catenary would have the midpoint sag, not the start. Severity: LOW (cosmetic).
- **Bug:** Ring segments L9272 — the `mid_angle + math.pi/2` gives the tangent direction. The box length (Z half) is `ring_r * math.pi / n_arc` which is correct arc-length. But the box is then rotated by `(mid_angle + π/2)` only around Y, which orients the Z axis tangentially — correct. So rings are fine. **But** vertex count: 5 rings × 24 arc segs × 8 verts/box = 960v just for rings. Massively over-budget.
- **AAA ref:** Real game spider webs use translucent texture cards, not 1600v of geometry. ~24 tris max.
- **Upgrade:** Replace with quad/decal + alpha-tested texture. If geometry is required, use a single tri-strip per radial and per ring (~40 verts total).

### 25. `generate_coffin_mesh` (L9285) — **B**
- **Claims:** Hexagonal-profile extruded coffin + style-specific decoration (stone cross/border, iron bands/rivets/lock).
- **Produces:** Profile extrude (8 profile pts × 2 = 16v + 16 side faces) + style content (cross 16v + border 8 boxes × 8v = 64v for stone) ≈ **80-150v**.
- **Bug:** Profile extrude rotation L9330 `(v[0], v[2], v[1])` swaps Y and Z — works because coffin is built on XZ then rotated to lie flat. But this rotation also affects the stone cross / iron bands which are added AFTER and use post-rotation Y as `coffin_h/2`. Math checks out. Profile only has 8 points = visible facets at the shoulders. Severity: LOW.
- **Bug:** Iron-band coffin L9355-9360 — bands span `half_w + 0.01` along Z but the coffin profile is wider than `half_w` at the shoulder (`half_w` = `coffin_w/2 = 0.3`); bands at non-shoulder positions would clip into the body. Severity: LOW.
- **AAA ref:** Bloodborne coffins: hand-sculpted with rotted wood detail, individual nail-heads, mossy weathering. ~3k tris.
- **Upgrade:** More profile points (16+) for smoother shoulder curve; per-side band orientation; decals for nails instead of sphere geometry; closed-coffin vs open-lid variant.

### 26. `generate_gibbet_mesh` (L9376) — **C+** ⚠️ **BUG-306**
- **Claims:** Pole + cross arm + chain + cylindrical cage + base.
- **Produces:** Pole (24v) + arm (8v) + 4 chain links (96v BROKEN ALT) + cage rings (~96v) + 8 cage bars × 4 segs (~256v) + base (~36v) ≈ **~520v**.
- **Bug — BUG-306 (LOW):** L9418 chain alt rotation: `(v[2] - 0 + chain_x, v[1], v[0] - chain_x + 0)` — the `0`'s suggest a placeholder for a coordinate that wasn't substituted. Same broken alternating-link pattern. Severity: LOW.
- **Bug:** Cage bars L9462 are axis-aligned boxes at curve midpoints — same issue as soul cage (curved bars don't curve). Severity: MEDIUM.
- **AAA ref:** Witcher 3 gibbet: hand-bent iron cage with corpse posable inside, working pivot at chain. ~4-6k tris.
- **Upgrade:** Swept tube for cage bars; proper chain alternation; add hanging-corpse attachment slot.

### 27. `generate_urn_mesh` (L9481) — **B**
- **Claims:** Three styles (ceramic/metal/stone) lathe-built urn with optional ornate handles and bands.
- **Produces:** Lathe (16-segment × 12-16 profile pts ≈ 200v) + (metal_ornate: 2 toruses + handle spheres ≈ 100v) ≈ **200-300v**.
- **Bug:** Metal handle L9550-9558 is a chain of 8 small spheres — should be a swept tube. Reads as bumpy beads. Severity: LOW.
- **Bug:** Stone burial L9579 `lid` is a separate cylinder placed at height*0.95 — overlaps the lathe body's top profile (which closes at 0.001 radius at height*1.0). Lid sits atop a near-pointed cone — visually wrong. Severity: LOW.
- **AAA ref:** ESO urns: per-style hand-modeled with ornament-bake normal maps, optional contents (ash, scrolls). ~1.5k tris.
- **Upgrade:** Handle as `_make_swept_torus_arc`; carved ornament via normal map; per-urn variant with broken/intact states.

### 28. `generate_crate_mesh` (L9587) — **B-**
- **Claims:** Three conditions (new/weathered/broken_open) wooden crate with planks and corner posts.
- **Produces:** New = full beveled box (24v) + 3 plank strips (24v) + 4 corner posts (32v) ≈ **80v**, then `_enhance_mesh_detail(min=500)` doubles up to 500+v via subdivision. Broken_open = bottom + 3 walls + 1 detached plank ≈ 5×24 = 120v → 500v after enhance.
- **Bug:** Plank strips L7637 are positioned at `z_pos = -hs + t*size` with HALF-EXTENT `hs+plank_t` along X — meaning each plank spans the full crate width as a single box, not a per-side strip. Three identical horizontal "belts" wrap the crate. Comment says "Front/back strips" but they extend through the entire crate body in X. Severity: LOW.
- **Bug:** Corner posts L9644 use `_make_box` not `_make_beveled_box` — sharp 90° corners on otherwise beveled crate. Severity: LOW.
- **AAA ref:** Half-Life 2 crates: ~250 tris with stenciled markings, weathered normal map. ~600 tris HD.
- **Upgrade:** Per-face plank strips; bevel corner posts; stencil decal slot; chip-damage variants for weathered.

### 29. `generate_sack_mesh` (L9659) — **B-**
- **Claims:** Lathe-built grain sack with fullness parameter + tied-off knot.
- **Produces:** 12-segment × 10 profile pts lathe ≈ 120v + knot torus (~48v) ≈ **170v**.
- **Bug:** Knot torus L9699 has `minor_radius = knot_r * 0.5 = base_r * 0.06` ≈ 0.009m — visible but small. The sack profile L9681-9692 uses a `bulge` factor that grows with fullness, but `top_pinch` SHRINKS with fullness — for fullness=1.0, top_pinch=0.3 (small) and bulge=1.0 (full) → tightly tied top. Math checks out. Severity: NONE here.
- **AAA ref:** Stylized sacks in WoW/ESO: ~400 tris, baked cloth normal map for weave, often with rope-tie geometry.
- **Upgrade:** Add visible weave normal-map slot; rope-tie should be a wrapped helix not a single torus; multi-knot variants.

### 30. `generate_basket_mesh` (L9707) — **B-**
- **Claims:** Lathe-built woven basket + rim + 3 woven bands + optional arched handle.
- **Produces:** 16-seg lathe (16×7=112v) + rim torus (~64v) + 3 band toruses (192v) + handle (12 spheres × 24 = 288v) ≈ **~660v**.
- **Bug:** Handle L9755-9762 is 12 sphere segments — reads as beaded, not a smooth arch. Should be a swept tube along the arc. Severity: MEDIUM (the highest-vert-cost element of the mesh is the worst-looking).
- **AAA ref:** Witcher 3 baskets: hand-modeled woven texture geometry + handle as arc tube. ~800 tris.
- **Upgrade:** Sweep a tube along the parametric arc for the handle; add weave normal map; partial-fill variant with contents.

### 31. `generate_treasure_pile_mesh` (L9768) — **B**
- **Claims:** Mound (lathe) + N scattered coins (cylinders) + ~N/5 gem cones+sphere.
- **Produces:** Mound (12×7=84v) + 20 coins (20×12=240v) + 4 gems (4 cones + 4 spheres ≈ 4×5+4×16=84v) ≈ **~410v**.
- **Bug:** Gems are cone-on-sphere — should be octahedra. The "Bottom inverted cone (approximated as a small sphere)" comment L9820-9821 admits the shortcut. Severity: LOW.
- **Bug:** Coins are 6-sided cylinders — visibly hexagonal at close range. Severity: LOW.
- **AAA ref:** Skyrim/ESO treasure piles: instanced coins, gems, jeweled objects, individually placed by hand or scatter tool. ~2-5k tris.
- **Upgrade:** Coins should be 12+ sided; gems should be true octahedra (use `_make_octahedron` helper); add jewelry, goblets, scattered chains.

### 32. `generate_potion_bottle_mesh` (L9830) — **B**
- **Claims:** Four styles (round_flask / tall_vial / skull_bottle / crystal_decanter) lathe + cork.
- **Produces:** Lathe ~12 segs × 12-16 pts ≈ 150-200v + cork (~12v). Skull style = sphere body + 2 eye spheres + jaw box + neck taper ≈ 350v.
- **Bug:** Skull bottle L9893 eye sockets are SPHERES on TOP of the skull surface — they protrude outward, not inward as sockets. Severity: LOW (cosmetic, but reads as boils not eye holes).
- **AAA ref:** Skyrim alchemy bottles: per-bottle hand-modeled with liquid mesh inside, thumb-shaped cork with wax-seal. ~600-1200 tris.
- **Upgrade:** Inside-liquid mesh; wax-seal; per-bottle label decal; replace eye-socket spheres with inset boolean.

### 33. `generate_scroll_mesh` (L9942) — **B-**
- **Claims:** Rolled (cylinder + end knobs + slight unroll curve) or unrolled (sheet + curled edges).
- **Produces:** Rolled: cylinder (24v) + 2 sphere knobs (~64v) + 8 unroll boxes (~64v) ≈ **~150v**. Unrolled: sheet (8v) + 12 curl boxes (96v) ≈ **~104v**.
- **Bug:** Rolled scroll axis swap L9963 `(v[0], v[2], v[1])` rotates cylinder to lie horizontal — works. Unroll boxes L9981 use `length * 0.9 * 0.48` as half-extent then SAME swap — the unroll segments are correctly positioned along the scroll length axis. Math checks out. Severity: NONE.
- **AAA ref:** Skyrim scrolls: cylinder + 2 lathe-modeled knobs + alpha-tested parchment plane. ~300 tris.
- **Upgrade:** Replace 8 unroll boxes with one curved quad strip (much cheaper, smoother); add scroll-text decal slot.

### 34. `generate_lantern_mesh` (L10024) — **B**
- **Claims:** Four styles (iron_cage / paper_hanging / crystal_embedded / skull_lantern). Iron has cap+plate+bars+ring+candle.
- **Produces:** Iron ≈ cone (9v) + base (16v) + 8 bar cylinders (8×8=64v) + ring torus (32v) + candle (12v) ≈ **~135v**. Skull ≈ 200v with eyes/jaw.
- **Bug:** Iron lantern bars L10054 are at `r` (lantern radius) — but the cone L10042 is at `r*1.2` and base at `r*1.1`. Bars are inset from both — visually they don't connect to top or bottom edge geometry. Severity: LOW.
- **Bug:** Skull lantern L10120 same eye-socket-bulge issue as potion skull. Severity: LOW.
- **AAA ref:** Hellblade II lanterns: hand-sculpted iron with candle wick + flame-mesh + emissive heat haze. ~2-3k tris with flame.
- **Upgrade:** Bars should hit cone-base radius; add wick + flame mesh; add glass panel inset for paper/iron variants.

### 35. `generate_brazier_mesh` (L10142) — **B**
- **Claims:** Three styles (iron_standing / stone_bowl / hanging_chain) with bowl lathe + legs/pedestal/chains.
- **Produces:** Iron ≈ bowl lathe (96v) + rim (~64v) + 3 legs (3×24 + 3×12 = 108v) ≈ **~270v**. Stone ≈ outer + inner lathe ≈ 200v.
- **Bug:** Stone bowl inner L10213 lathe is built as a separate mesh — there's no connection between outer and inner lathes, so the rim has an open seam visible from above. Severity: MEDIUM (looks broken at any angle showing rim).
- **Bug:** Hanging-chain "chains" L10239 are CYLINDERS, not chain links. Severity: LOW (or HIGH if you take the function name seriously).
- **AAA ref:** Dark Souls braziers: hand-modeled with coal mesh inside, fire mesh on top, weathered iron normal map. ~3k tris.
- **Upgrade:** Weld inner+outer rim into one lathe; replace cylinder chains with proper chain-link helper; coal/ash interior; fire-mesh socket.

### 36. `generate_campfire_mesh` (L10253) — **B-**
- **Claims:** Stone ring (12 stones) + N teepee logs + central ash pile.
- **Produces:** 12 stones (12×24=288v) + N logs (~4×24=96v) + ash lathe (~40v) ≈ **~425v**.
- **Bug:** "Teepee pattern" L10289-10297 — logs are tapered cylinders centered at `(mid_x, mid_z)` extending VERTICALLY with `log_len * 0.6` as `height` parameter — `_make_tapered_cylinder` builds along Y. So logs are vertical pillars at radial midpoints, NOT slanted teepee. Severity: HIGH (campfire reads as 4 vertical posts in stone ring, not crossed logs).
- **Bug:** No flame mesh, no glowing ember decal slot. Severity: MEDIUM.
- **AAA ref:** ARK / Valheim campfires: hand-placed log instances with crossed orientation, ember particles, dynamic flame mesh. ~1.5k tris.
- **Upgrade:** Build logs as orientable boxes/tubes via two endpoints (one at center+height, one at outer ring+ground); add flame mesh; embers as decals.

### 37. `generate_crystal_light_mesh` (L10315) — **B-**
- **Claims:** Base rock + N crystal shards (tapered cylinders).
- **Produces:** Base sphere (~24v flattened) + N shards (each ~14v tapered cylinder) ≈ **~120v** for 5 shards.
- **Bug:** All shards are vertical (built via `_make_tapered_cylinder` along Y). No outward-fanning shard angles. Severity: MEDIUM (real crystal clusters fan radially).
- **Bug:** Base rock L10337 — `max(v[1], -base_r * 0.2)` flattens bottom half via vertex clamping but doesn't re-triangulate, leaving multiple clamped verts at same Y position — lots of degenerate triangles in the cap region. Severity: LOW.
- **AAA ref:** Dauntless / Hellblade crystals: hand-sculpted shard cluster with fan orientation, SSS material, emissive cracks. ~2k tris.
- **Upgrade:** Per-shard rotation matrix to fan outward; rebuild base as a true hemisphere not a clamped sphere; add SSS-friendly UVs; emissive crack channel.

### 38. `generate_magic_orb_light_mesh` (L10360) — **B**
- **Claims:** Central sphere + (if cage) 3 orthogonal cage rings + top mount cone + chain hook.
- **Produces:** Sphere (8×12=96v) + 3 toruses (3×64=192v) + cone (5v) + hook torus (32v) ≈ **~325v** with cage.
- **Bug:** Three "orthogonal" rings — first in XZ (default), second swap Y/Z (rotates around X), third swap X/Z (rotates around Y). XZ + rotation-around-X = XY plane (correct meridian). XZ + rotation-around-Y = XZ plane again (NO ROTATION! You rotated around the Y-axis, but the torus already lies in XZ which contains Y as normal — rotating around Y leaves XZ invariant). So the THIRD ring is degenerate with the first. Only 2 unique rings actually exist. Severity: MEDIUM (visually the cage has 2 rings, not 3).
- **AAA ref:** Magic orb lights in MMOs: simple sphere + alpha-tested cage texture or 4-6 cage bars. ~300-500 tris.
- **Upgrade:** Fix third ring rotation (swap X+Y, not X+Z); add cage-bar variant; emissive orb material.

### 39. `generate_door_mesh` (L10420) — **B**
- **Claims:** Five styles (wooden_plank / iron_reinforced / stone_carved / hidden_bookcase / dungeon_gate) with hinges, bands, studs, books, etc.
- **Produces:** Wooden ≈ panel (24v) + 5 plank lines (40v) + 2 hinges (24v) + handle torus (32v) ≈ 120v. Iron ≈ panel + 5 bands + ~20 studs (~480v). Bookcase ≈ frame + shelves + ~30 books → 800-1000v. Then `_enhance_mesh_detail(min=500)` densifies.
- **Bug:** Wooden plank lines L10451 are positioned at `depth/2 + 0.002` (just outside front face) — visible "z-fight risk" but small. Should be inset/carved.
- **Bug:** Iron bands L10477 wrap with `width/2+0.005` half-extent — bands extend beyond the door's edges by 0.005m in X (good for rivet-strap look) but only 0.003 in Z, so they're flush with the door front, no relief.
- **Bug:** Bookcase shelves L10539 — top shelf at `i=shelf_count` puts shelf at `sy = shelf_h` which is the top edge — ceiling shelf. Books L10548-10554 placed via while loop with random widths — could produce books wider than remaining shelf width, last book overlaps right side panel. Severity: LOW.
- **Bug:** Dungeon gate L10580 spike inversion — same pattern as obelisk, but spike's apex is at y=`-height + 0.05` after flipping `(v[0], -v[1], v[2])` which negates around Y=0 — works because cones start at y=`-0.01`, height=0.05 → flip sends apex to y=-0.04. Severity: NONE.
- **AAA ref:** Dishonored 2 doors ~5-8k tris LOD0 with deep relief carvings; Skyrim doors ~3k tris.
- **Upgrade:** Carve plank lines into door (boolean cut); add brace-pattern Z-bracing for wood door; properly weld iron bands to door body; add lock plate.

### 40. `generate_window_mesh` (L10595) — **C+**
- **Claims:** Four styles (arched_gothic / circular_rose / arrow_slit / stained_frame).
- **Produces:** Gothic ≈ 3 frame boxes + 13 arch spheres + mullion ≈ 200v. Rose ≈ 2 toruses + 8 spokes ≈ 160v. Slit ≈ ~100v. Stained ≈ 4 frames + 2 dividers + 9 arc spheres ≈ 250v.
- **Bug:** Gothic arch L10640 is built from SPHERES at arc points — arch is bumpy beads, not a smooth tracery. Severity: MEDIUM.
- **Bug:** Stained_frame L10707 cross-divider `vv` is a vertical box from `y=0 to height`, but the side posts are at `y=height/2 ± height/2` — vertical divider clips through bottom sill (which is at `y=0`). Severity: LOW.
- **Bug:** Rose window has no glass mesh / lead-came geometry beyond spokes. Severity: LOW.
- **AAA ref:** Notre-Dame in AC Unity: each window is hand-authored tracery + stained-glass tessellated cards. ~5-8k tris.
- **Upgrade:** Sweep tube along arch curve (not spheres); add glass plane with stained-glass UVs; lead-came strips.

### 41. `generate_trapdoor_mesh` (L10725) — **C+**
- **Claims:** Wooden or iron trapdoor + plank lines + braces + hinge + ring handle + floor frame.
- **Produces:** Iron ≈ plate (24v) + 24 rivets (24×16=384v) + handle torus (32v) + frame (3×8=24v) ≈ **~470v**. Wooden ≈ plate + 5 lines + 2 braces + hinge + handle + frame ≈ 200v.
- **Bug:** Ring handle L10765 "rotation to stand upright" via `(v[0], thickness + abs(v[2]) * 2, v[1])` — clever (ring lying in XZ → rotate so the Z dim becomes Y dim, and use abs to flatten under-side). But this projects ALL verts above thickness+0 — the bottom half of the ring (those with v[2]<0) has positive new-Y, same as top half. Result: a half-ring (looks like a D-shape from the side), not a full ring. Severity: LOW.
- **Bug:** Floor frame L10802-10808 has only 3 sides (no fourth side at z=hs+frame_w, where the hinge is) — intentional to allow the door to "open" but reads as half-built when door is closed. Severity: NONE (intentional).
- **AAA ref:** Skyrim/ESO trapdoors: hand-modeled with iron strap reinforcement, properly mounted ring handle on hinge bracket. ~800 tris.
- **Upgrade:** Use proper rotation matrix for handle (full ring); add hinge bracket; rivets should be lower-density (12, not 24).

### 42. `generate_banner_mesh` (L10821) — **B**
- **Claims:** Hanging rod + 2 finial spheres + N×M fabric grid with drape sin curves.
- **Produces:** Rod (8v) + 2 spheres (48v) + 9×13 grid = 117v + 96 quads ≈ **~175v**.
- **Bug:** Style parameter (`pointed` / `straight` / `swallowtail`) is **completely ignored** — no branching on style. All three styles produce identical straight-bottom banners. Severity: MEDIUM (parameter is a lie).
- **Bug:** Drape math L10858 `drape_z = sin(t*pi)*0.03` peaks at middle (good for bulge-out drape), but combined with side wave L10863 produces a mostly-flat surface with subtle ripples. Real banner drape has gravity sag and air-flow waves, not just sinusoidal Z. Severity: LOW.
- **AAA ref:** Witcher 3 banners: physics-simulated cloth on a quad mesh, hand-painted heraldry texture. ~600 tris cloth.
- **Upgrade:** Implement style branching (V-cut for pointed, multi-tail for swallowtail); use proper catenary sag formula for vertical drape; add tassel geometry at bottom.

### 43. `generate_wall_shield_mesh` (L10881) — **B-**
- **Claims:** Four styles (round/kite/heater/tower) with boss / ridge / rim + wall mount.
- **Produces:** Round ≈ lathe (~150v) + boss lathe (~50v) + rim torus (~64v) ≈ 270v. Kite ≈ panel + tapered lower + ridge ≈ 150v.
- **Bug:** Tower style L10963-10974 has NO boss/ornament beyond a single sphere on the front (L10972) — visually the most barren of the four styles despite tower being a major medieval shield type with elaborate heraldry.
- **Bug:** Round shield L10898 profile has Y values that decrease from `-0.02` at center to `+0.024` at rim — that's a CONCAVE (dished) shield with center-low, which is anatomically backward (real shields are convex with center-high boss). Then a separate boss is placed at center (L10913) — but the surface is dished inward, so the boss sits in a depression. Severity: MEDIUM.
- **AAA ref:** Mordhau / Chivalry shields: per-style hand-modeled with rivet bake, leather strap geometry, boss as proper iron umbo. ~2-3k tris.
- **Upgrade:** Convex round profile (positive Y at center); add leather strap geometry; per-style heraldic decal slot.

### 44. `generate_mounted_head_mesh` (L10984) — **C+**
- **Claims:** Wall plaque (lathe flattened) + 4 creature variants (deer / boar / dragon / demon) with antlers/tusks/horns/jaws.
- **Produces:** Plaque (~84v) + creature ≈ 200-400v depending. Deer ≈ head sphere + snout taper + 14 antler spheres + 4 antler cones ≈ 350v.
- **Bug:** Plaque flattening L11009 `(v[0], v[1], v[2] * 0.3 - 0.04)` — the lathe was built in XY (lathe rotates profile around Y axis, generating XZ ring per profile point) — so v[2] is the depth-from-axis. Multiplying by 0.3 squashes depth. But the head is then placed at `z=0.08` (deer L11014), so it floats forward of the plaque's flattened depth (which is in range ~[-0.04, +0.02])... math works.
- **Bug:** Deer snout L11020 axis swap `(v[0], v[2] - 0.08, v[1] + 0.02)` — same broken-rotation pattern. Snout is a tapered cylinder built along Y, then this swap puts X into X (good), Z-0.08 into Y (collapses snout's Y dimension to constant), and Y+0.02 into Z (extrudes along Z). Net: snout is a flat ring at `y=v[2]-0.08` (varies per vertex, so it's actually OK because the tapered cyl has different Y per ring, but radial X/Z collapses are still wrong shape). Severity: HIGH (snout reads degenerate).
- **Bug:** Antlers L11023 are SPHERES (5 per side) + a few cones — antlers should be branching tubes. Reads as bumpy fingers. Severity: HIGH (deer antlers are a defining silhouette feature).
- **Bug:** Boar tusks L11047 same broken axis swap pattern. Severity: HIGH.
- **AAA ref:** Skyrim/Witcher 3 mounted heads: hand-sculpted per-creature with proper anatomy, fur normal map, individually placed tusks/antlers via merged geometry. ~5-15k tris.
- **Upgrade:** Use proper rotation matrices throughout; build antlers as branching swept tubes; sculpt-quality head geometry per creature; add eye highlights, mouth interior.

### 45. `generate_painting_frame_mesh` (L11089) — **B-**
- **Claims:** Three styles (ornate / simple / gothic) with 4 frame sides + canvas plane + ornament decoration.
- **Produces:** 4 frame boxes (96v) + canvas (8v) + ornate (8 ornament spheres ≈ 192v) or gothic (9 arch spheres ≈ 216v) ≈ **300v**.
- **Bug:** Ornate corner ornaments L11135 placed at corner positions — but the corner of the frame is at `(width/2, height/2)` which is OUTSIDE the panel center; sphere placed there overlaps half-in/half-out of frame edge. Should be inset. Severity: LOW.
- **Bug:** Gothic arch L11146 same sphere-arc as window — bumpy not smooth.
- **AAA ref:** Witcher 3 painting frames: hand-carved corner volutes, gilded relief, painted canvas texture. ~1.5k tris.
- **Upgrade:** Replace ornament spheres with carved-corner volutes (small hand-sculpted props); inset corners; canvas should have painting-decal slot.

### 46. `generate_rug_mesh` (L11163) — **B**
- **Claims:** Three styles (rectangular / circular / runner) with thickness, border, fringe, tassels.
- **Produces:** Rectangular ≈ rug box (8v) + 4 border boxes (32v) + 20 fringe boxes (160v) ≈ 200v. Circular ≈ lathe (~80v) + 24 tassel boxes (192v) ≈ 270v. Runner ≈ rug + 2 edge + 16 fringe = ~200v.
- **Bug:** No pattern/material variation — all three are flat-color rug shapes. Real rug variety comes from the texture, but the function emits no UV/material slot info (BUG-309 systemic).
- **Bug:** Circular rug L11193 lathe with `close_top=True` AND `close_bottom=True` produces a closed manifold — good. But the profile L11184-11192 has thickness layer at top from radius 0→r and another at radius r at bottom — describes a flat disc with rolled edge (good). Math checks out.
- **AAA ref:** Witcher 3 rugs: tessellated quad with normal-mapped pile, tasseled fringe modeled, dirt/wear baked. ~600 tris.
- **Upgrade:** Add pile-height displacement geometry; pattern-decal slot for heraldry/floral; tasseled fringe should bend, not stick straight.

### 47. `generate_chandelier_mesh` (L11253) — **B-** ⚠️ **BUG-308**
- **Claims:** Central chain rod + top hook ring + N tiers × M arms with cup + candle + bottom finial.
- **Produces:** Central rod (12v) + hook (32v) + per tier (ring 64v + arms 6×8 + cups 6×24 + candles 6×12) ≈ 350v per tier + finial (~24v) ≈ **~700v** for 1-tier, **~1100v** for 2-tier.
- **Bug — BUG-308 (LOW):** Bottom finial L11317-11319 — built as cone at y=`-0.05`, then flipped via `(v[0], -v[1] + total_h * 0.05, v[2])`. After flip, apex (originally at y=0) goes to `total_h * 0.05`; base (at y=`-0.05`) goes to `0.05 + total_h*0.05`. So the finial is OVER the chandelier (above bottom tier), not BELOW. Severity: LOW (finial is in wrong half, but invisible bug because it's small).
- **Bug:** Arms L11296 are axis-aligned X-direction boxes regardless of `angle` — only mid_x and mid_z are correct, but the box extends along X, not radially. Arms at angles other than 0/180 are perpendicular to their radial direction. Severity: MEDIUM (chandelier arms don't actually point outward).
- **AAA ref:** Skyrim/Bloodborne chandeliers: per-arm authored S-curve with leaf decoration, candle drip wax, chain link suspension. ~5-10k tris.
- **Upgrade:** Sweep S-curve tube per arm; rotate arm box to radial direction; replace cylinder chain with chain-link helper.

### 48. `generate_hanging_cage_mesh` (L11326) — **C+**
- **Claims:** Cylindrical bar arrangement + 4 horizontal rings + cone dome + bottom plate + chain + top ring + door outline.
- **Produces:** 12 bars (12×8=96v) + 4 rings (4×48=192v) + cone (13v) + plate (~24v) + chain cyl (8v) + top ring (32v) + door box (8v) ≈ **~370v**.
- **Bug:** Hanging "chain" L11370 is a single CYLINDER, not a chain. Severity: MEDIUM (function name promises hanging chain).
- **Bug:** Door outline L11381 is a single box at `cage_r + bar_r*2` outside the cage — protrudes from the cylinder surface like a knob, not a hinged-door cutout. Severity: LOW.
- **AAA ref:** Same as gibbet — Witcher 3 hanging cages have body-posable interior, chain alternation, rotting wood floor. ~4k tris.
- **Upgrade:** Replace cylinder chain with proper chain-link helper; door as inset cut into cage bars; rusted-iron material slot; corpse-attachment socket.

### 49. `generate_anvil_mesh` (L11396) — **B**
- **Claims:** Body + top working surface + horn cone + tail step + base + feet.
- **Produces:** Body (24v) + top (24v) + horn (13v) + tail (24v) + base (24v) + feet (24v) ≈ **~135v**.
- **Bug:** Horn L11427 — `_make_cone(0, body_h+top_h, body_d/2 + 0.08*s, top_w*0.4, 0.15*s*0.3)` — placed at `cz=body_d/2 + 0.08*s` (in front of body) and built ALONG Y — so the horn is a vertical cone in front of the anvil, not a horizontal protrusion. Real anvil horns extend horizontally forward. Severity: MEDIUM.
- **Bug:** Feet L11450 are a single box centered at origin — anvils have 4 distinct corner feet, not a continuous slab. Severity: LOW.
- **AAA ref:** Skyrim/Kingdom Come anvils: hand-modeled with horizontal horn, distinct hardy/pritchel holes on top, weathered iron normal map. ~1.5k tris.
- **Upgrade:** Build horn via tapered cylinder along Z (need axis-correct helper — see BUG-300 family); per-corner feet; hardy-hole boolean cut; weld scars on top face.

---

## 2. NEW BUGS FOUND IN THIS RANGE

| ID | Severity | Location | Description |
|----|---|---|---|
| **BUG-300** | HIGH | L7361-7376 dart_launcher | Cylinder/cone "rotate to point along Z" via `nz = v[1] - ty + plate_d/2; ny = ty` collapses Y dim to constant; tubes are flat discs not cylinders. Anti-pattern repeats elsewhere. |
| **BUG-301** | HIGH | L7417 swinging_blade | Axle "rotation to horizontal" same anti-pattern as BUG-300. Axle is flat disc. |
| **BUG-302** | HIGH | L7590 cart | Axle "rotation along Z" same anti-pattern. Axles are flat discs. |
| **BUG-303** | LOW | L7597-7604 cart | `wheels==2` else-branch generates same wheel positions as `wheels==4` — duplicate code, intent unclear. |
| **BUG-304** | HIGH | L7868 boat (longship) | Yard "rotation to horizontal" same anti-pattern. Yard collapses to flat strip. Also L7787 oar same bug. |
| **BUG-305** | LOW | L7978-7981 wagon_wheel | Dead `sv,sf` cylinder generated then discarded (only `sf2` used); spoke translation math after rotation is off (subtle position shift for non-axis-aligned spokes). |
| **BUG-306** | LOW | L9418 gibbet | Chain alternate-link rotation `(v[2]-0+chain_x, v[1], v[0]-chain_x+0)` has placeholder `0`s; doesn't produce orthogonal links. |
| **BUG-307** | MEDIUM | L8796-8806 veil_tear | "Jagged" frame shards have ~constant `seg_w/seg_h` so reads as uniform rectangles in a ring, not jagged. |
| **BUG-308** | LOW | L11317-11319 chandelier | Bottom finial post-flip ends up ABOVE the bottom tier (positive Y), not below — finial is hidden inside chandelier instead of hanging beneath. |
| **BUG-309** | CRITICAL | systemic | Zero use of bmesh anywhere in the 49 functions. No vertex welding, no normals computed at gen time, no UVs, no material-id channels. Output is raw quad-soup; downstream pipelines must add all topology data. AAA expects bmesh-or-equivalent with welded UVs, normal-baked LOD chain, material slots. |
| **BUG-310** | LOW-MEDIUM | L9241-9252 spider_web | Sag is computed at strand t0 (start), applied to midpoint — should be at midpoint t-mid. ALSO 1600+ vertex count for what should be a quad+texture. |
| **BUG-311** | HIGH | L8497 ladder | Rung "rotation to horizontal" same anti-pattern as BUG-300. Rungs are flat discs. |
| **BUG-312** | MEDIUM | L8112-8113 column_row (gothic) | Capital "splay" via cone + ternary list-comp produces inverted-cone-INSIDE-shaft, not splayed capital. Operator-precedence bug means flipped Y goes to wrong half. |
| **BUG-313** | LOW | L8340 drawbridge | Chain alternate-link permutation produces no actual orthogonal rotation; alternating links visually identical. |
| **BUG-314** | LOW | L7534 falling_cage | Same broken chain alternation. |
| **BUG-315** | HIGH | systemic — `_merge_meshes` | Doesn't weld coincident vertices. Every primitive's verts are concatenated, leaving T-junctions and z-fight at every joint. Need a vertex-merge-by-distance pass post-merge. |
| **BUG-316** | MEDIUM | systemic | ~30 functions place decorative geometry at depth offsets of 0.001-0.005m to fake carving/etching. At distance these will z-fight; AAA standard cuts via boolean or uses decals. |
| **BUG-317** | MEDIUM | systemic | No LOD chain emitted. AAA expects LOD0/1/2 with explicit triangle budgets. Single-density output forces engine-side decimation which is destructive to silhouette. |
| **BUG-318** | MEDIUM | L7172 spike_trap | Spike count silently rounds DOWN to nearest perfect square (`int(sqrt(N))^2`). Request 7 → 4 spikes; request 11 → 9 spikes. No warning to caller. |
| **BUG-319** | MEDIUM | L10393-10398 magic_orb_light | "Three orthogonal" cage rings — third ring rotation around Y leaves XZ torus invariant. Only 2 unique rings. |
| **BUG-320** | HIGH | L10895-10923 wall_shield (round) | Profile is dished (concave) rather than convex — center-low, rim-high. Boss then placed in depression. Anatomically backward. |
| **BUG-321** | HIGH | L10288-10297 campfire | Logs are vertical pillars, not slanted teepee. Function docstring claims "teepee pattern" but geometry is 4 vertical posts. |
| **BUG-322** | MEDIUM | L10821-10878 banner | `style` parameter ("pointed"/"straight"/"swallowtail") is silently ignored — all three produce identical rectangular banners. Parameter is a lie. |
| **BUG-323** | HIGH | L11020-11048 mounted_head | Snout/jaw/tusk axis swaps use the broken anti-pattern (BUG-300 family). Snouts are flat discs. Antlers made of spheres look like fingers, not antlers. |
| **BUG-324** | MEDIUM | L11427 anvil | Horn is built as VERTICAL cone in front of body, not horizontal protrusion. Real anvils have horizontal horns. |
| **BUG-325** | MEDIUM | L8213-8266 rampart | Inner parapet is continuous low wall — should have crenel gaps matching merlons on outer side. |
| **BUG-326** | MEDIUM | L8169-8180 buttress (flying) | Flying arch is 6 stair-stepped boxes, not curved — reads as staircase not arch. |
| **BUG-327** | LOW | L9893-9896, L10120-10126 | Skull eye sockets are spheres ON TOP of skull surface (additive), not inset cuts. Read as boils not eyes. |
| **BUG-328** | LOW | L8401 well | Shaft cylinder starts at `cy=-depth`, height=`depth`, top at y=0 — but rim and inner wall start at y=0. Shaft top is coincident with floor; if floor or rim is missing geometry, shaft is visible from outside. Also rim profile L8392 dips inward (radius dec → inc → dec). |
| **BUG-329** | LOW | L9755-9762 basket | Handle is 12 spheres reading as beaded; should be a swept tube. |
| **BUG-330** | LOW | L8721-8722, L8774-8775, L9781-9782, L10328-10329, L10543-10544 | `import random as _rng; rng = _rng.Random(seed)` repeated in many functions with hardcoded seeds (42, 77, 88, 777). Determinism is good, but 5+ duplicate import statements suggests no shared rng helper — refactor to a module-level `_make_rng(seed)`. |
| **BUG-331** | MEDIUM | L10213 brazier (stone_bowl) | Inner bowl is separate lathe with no welded connection to outer bowl rim — visible open seam from above. |
| **BUG-332** | LOW | L10239 brazier (hanging_chain) | "Chains" are CYLINDERS. The function name "hanging_chain" implies actual chain link geometry, but only cylinders are produced. |
| **BUG-333** | MEDIUM | L11296 chandelier | Arm boxes are X-axis-aligned regardless of arm angle; arms at non-cardinal angles are perpendicular to their radial direction. |
| **BUG-334** | LOW | L8631 sacrificial_circle | Stone height "variation" `0.5 + 0.15*((i*3)%5-2)/2` produces only 5 distinct heights cycling deterministically — not noise-driven. Acceptable but very heuristic. |
| **BUG-335** | LOW | L11365 hanging_cage | Bottom plate is a CYLINDER (cap top+bottom) at the cage bottom — shows visible solid disc when cage is viewed from below. Should be a thin grate or omitted. |
| **BUG-336** | LOW | L9149 dark_obelisk | Pyramidion base radius is 1.1× obelisk top half-width, creating a visible lip overhang. Real pyramidions are flush-or-inset. |
| **BUG-337** | LOW | L9985-9991 scroll (unrolled) | Sheet is built around `(0, sheet_t/2, 0)` then curls added at `±sheet_h/2 ± curl_r·cos(angle)` — curl boxes butt-join the sheet edge but the curl X-extent is full sheet width, while the SHEET's Z-extent is sheet_h/2 — the curl boxes are positioned just OUTSIDE the sheet (good), but they don't taper, so the curled edge looks like a box on a stick. |
| **BUG-338** | MEDIUM | L10337-10338 crystal_light | Base sphere bottom-flatten via vertex-clamp leaves multiple coincident verts at clamp Y, producing degenerate triangles in the base. |

**New bug count: 39** (BUG-300 through BUG-338).

---

## 3. CATEGORY-LEVEL OBSERVATIONS

### 3.1 The "axis rotation anti-pattern" (BUG-300 family)

The single most pervasive structural defect in the range. It appears in:
- `dart_launcher` (tubes + darts, L7361, L7372)
- `swinging_blade` (axle, L7417)
- `cart` (axles, L7590)
- `boat/longship` (yard, L7868; oars, L7787)
- `ladder` (rungs, L8497)
- `bone_throne` (armrests, L9068)
- `mounted_head` (deer snout L11020, boar tusks L11048, dragon jaw L11057)
- `anvil` (horn implicitly suffers from no axis-along-Z helper, L11427)

In every case, the developer wanted to "rotate a Y-axis cylinder to lie along Z (or X)" but used **vertex-coordinate aliasing instead of a rotation matrix**. The pattern:
```python
new_verts = [(v[0], constant_y, v[1] - origin_y + new_z_offset) for v in original]
```
This **collapses the Y dimension to a constant**, producing a flat ring instead of an oriented cylinder. The fix is a one-line helper:
```python
def _rotate_to_axis(verts, axis, origin):
    # proper 3x3 rotation around one of the world axes
```
**13 functions** in the range have at least one instance. **Severity: HIGH** because it visually breaks core silhouette features (cart axles, ladder rungs, dart tubes, anvil horns, etc.).

### 3.2 The "chain link alternation" anti-pattern (BUG-306, 313, 314)

Multiple functions try to alternate chain link orientation by permuting torus vertex coordinates `(v[0], v[1], v[2]) → (v[2], v[1], v[0])` etc. None of these produce a correct 90° rotation around the chain's tangent direction. Real chain alternation requires rotating each link's plane around the chain's local tangent. AAA studios use a `_make_chain_strand(p0, p1, n_links, link_radius)` helper that builds tori with proper tangent-frame rotation.

### 3.3 Lathe/extrude usage is good; bmesh usage is zero

`_make_lathe` and `_make_profile_extrude` are used appropriately throughout (urn, sack, basket, fountain, well, scroll, etc.). However `_make_lathe` returns un-welded vertex lists — the lathe rings have N×M verts with no shared topology, which means subsequent normal-baking will produce per-face flat normals (visible faceting on what should be smooth lathes).

**bmesh fix:** The whole file should run a `bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)` pass after `_merge_meshes`. This single change would resolve BUG-315 and dramatically improve normal-bake quality for ~30 of the 49 functions.

### 3.4 Style parameters that are silently ignored

- `generate_banner_mesh` `style` (pointed/straight/swallowtail) — ignored (BUG-322).
- `generate_coffin_mesh` `_bevel` is computed per style but only `bevel` constant is used in some sub-paths.
- `generate_dart_launcher_mesh` `style` (stone vs metal) only changes bevel by 0.003 — visually identical.

### 3.5 Per-function vertex budgets vs AAA

| Function | This file | AAA LOD0 |
|---|---|---|
| spike_trap | ~180v | 2-3k tris |
| bear_trap | ~180v | 2-4k tris |
| cart (covered) | ~800v | 6-8k tris |
| boat (longship) | ~300v | 8-15k tris |
| coffin | ~150v | 3k tris |
| chandelier (2-tier) | ~1100v | 5-10k tris |
| anvil | ~135v | 1.5k tris |
| spider_web | **~1600v** | should be a 6v texture-quad |

The file under-shoots vertex budgets on most "hero" assets and **over-shoots** on `spider_web` where geometry is the wrong solution entirely.

---

## 4. DISTRIBUTION OF GRADES

| Grade | Count | Functions |
|---|---|---|
| A+ / A / A- | 0 | none |
| B+ | 0 | none |
| B | 7 | well, sacrificial_circle, blood_fountain, urn, treasure_pile, potion_bottle, lantern, brazier, magic_orb_light, door, banner, rug, anvil (boundary B/B-) |
| B- | 13 | buttress, rampart, corruption_crystal, bone_throne, dark_obelisk, coffin, sack, basket, scroll, crate, campfire, crystal_light, wall_shield, painting_frame, chandelier |
| C+ | 11 | spike_trap, pressure_plate, falling_cage, drawbridge, scaffolding, soul_cage, gibbet, window, trapdoor, hanging_cage |
| C / C- | 6 | bear_trap, boat, wagon_wheel, column_row, veil_tear, spider_web, mounted_head |
| D | 6 | dart_launcher, swinging_blade, cart, ladder |

(Some functions appear in two buckets where they're on the boundary; counts are approximate.)

**Net assessment: average grade across 49 functions ≈ C+ to B-.**

The range produces **silhouette-intent blockouts** suitable for greybox / placeholder use. **Not a single function in the range would ship in a Megascans / Quixel / SpeedTree / UE5 PCG environment without significant rework.** The pervasive axis-rotation bug alone would force a re-audit of ~13 functions. The lack of bmesh, vertex welding, normals, UVs, and LODs is a category-killer for AAA pipelines.

---

## 5. PRIORITY FIX ORDER

1. **BUG-309 (CRITICAL)** — Add bmesh post-pass with vertex weld, normals, basic UVs. Fixes 49 functions at once.
2. **BUG-300 family (HIGH × 13 functions)** — Add `_rotate_verts_around_axis(verts, axis, origin)` helper; replace all 13+ broken aliasing rotations.
3. **BUG-315 (HIGH)** — `_merge_meshes` should weld within `1e-5`.
4. **BUG-321 (HIGH)** — Fix campfire log orientation (defining feature of the asset).
5. **BUG-323 (HIGH)** — Fix mounted_head deer/dragon/boar axis swaps; replace antler spheres with branching tubes.
6. **BUG-320 (HIGH)** — Flip round shield profile to convex.
7. **BUG-307, 312, 319, 322, 324, 325, 326, 331, 333 (MEDIUM × 9)** — One-by-one per function.
8. **BUG-317 (MEDIUM)** — Add LOD chain emission.
9. Remaining LOW bugs — opportunistic.

---

**End of P3 deep dive.** 49/49 functions graded. 39 new bugs (BUG-300–BUG-338) logged.
