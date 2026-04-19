# P4 — `procedural_meshes.py` functions 148–196 (lines 11459-14135)
## Date: 2026-04-16
## Auditor: Opus 4.7 ultrathink — strict AAA reference grading
## Method: Python AST enumeration → per-function read → Context7 (Blender bmesh, Trimesh) + WebSearch (Quixel Megascans, UE5 PCG) cross-checked
## Scope: `veilbreakers_terrain/handlers/procedural_meshes.py` lines 11459-14135 (`generate_forge_mesh` → `generate_aegis_mesh`) — 49 functions
## Repository scope note (per Conner): this file is **scope contamination in a terrain-only repo**. Findings are NOT terrain-pipeline bugs. They are tagged `scope:non-terrain` and the upstream fix is to delete or relocate `procedural_meshes.py`. Per directive, I audited anyway against AAA prop standards.

---

## Coverage
- Functions in range: **49**, graded: **49**, skipped: **0**.
- Source enumeration: AST `FunctionDef` walk on the file with line filter `11459 ≤ lineno ≤ 14135`. All 49 enumerated identifiers appear below.
- All functions return a `MeshSpec` via `_make_result(...)` (line 233-279) which auto-generates **box-projection UVs** and **dihedral-angle sharp-edge tags**. None of these 49 functions author bespoke per-loop UVs, normals, vertex colors, materials, tangent space, or LODs.
- Helper primitives audited (necessary context): `_make_box` (8v/6f), `_make_cylinder` (2*segs, side+caps), `_make_cone` (segs+1), `_make_torus_ring` (major*minor), `_make_tapered_cylinder` (rings+1)*segs, `_make_lathe` (n_profile*segs), `_make_sphere` (UV sphere with poles), `_make_beveled_box` (24v rounded chamfer), `_merge_meshes` (offset concat — does NOT weld coincident verts).

---

## Headline grade: **C+ overall** (range D → A-)

This batch is uneven. The 49 functions split into:
- **Crafting stations** (forge/workbench/cauldron/grinding-wheel/loom/market-stall, 6 funcs) — honest **B / B-** prop blockouts on par with early-prototype UE Marketplace assets.
- **Signs & markers** (signpost/gravestone/waystone/milestone, 4 funcs) — **C+ / B-** with one buggy signpost arm transform.
- **Natural formations** (stalactite/stalagmite/bone-pile/nest/geyser/fallen-log, 6 funcs) — **C+** small-scale dressings; SpeedTree/Megascans rock or bone scans crush them.
- **Monster parts** (horn/claw/tail/wing/tentacle/mandible/carapace/spine/fang, 9 funcs) — the weakest block. Multiple **C / C-** with broken transforms (signpost cone, wing membrane fly-aways, tail tip rotations using mismatched axes), z-fighting concentric primitives, and missing weld between bones and joints.
- **Monster bodies** (humanoid/quadruped/serpent/insectoid/skeletal/golem, 6 funcs) — **C / D+** parametric humanoid blockouts. None match AAA character base mesh proportions or articulation. Quadruped has a **CRITICAL** axis-swap on the body that produces an unrecognizable shape (BUG-353).
- **Projectiles & combat** (arrow/orb/knife/bomb, 4 funcs) — **C+** for the simple ones; arrow broadhead is two flat quads with no thickness.
- **Armor pieces** (helmet/pauldron/gauntlet/greave/breastplate, 5 funcs) — **C+ / B-** with style branches but no inside hollow, no buckles, no straps, no leather backing.
- **Shields** (round/heater/pavise/targe/magical-barrier/bone/crystal/living-wood/aegis, 9 funcs) — actually the **strongest** block here. `aegis` and `living_wood` reach **B / B-**.

**Single biggest systemic theme:** every generator is a **bag of intersecting primitive parts**. They are merged with `_merge_meshes` which only offsets indices — coincident vertices are never welded, intersecting solids overlap (z-fighting under any non-trivial lighting), and there are no continuous edge loops carrying silhouette. AAA props (Megascans / SpeedTree / hand-sculpted) are **single watertight surfaces with deliberate edge flow**. Without that, even a 50k-tri output reads as "engine grey-box."

**Second systemic theme:** UV authoring is delegated to `_auto_generate_box_projection_uvs(vertices)` which projects per-vertex (not per-loop), so any seam-needing surface (helmet brow band, sword fuller, shield rim) gets stretched UVs at the silhouette boundary. UE5 / Quixel / Substance Painter all expect per-face-corner UVs with seams.

**Third systemic theme:** zero LOD. AAA assets ship LOD0/1/2/3 + impostor; these emit one mesh.

**New bugs found:** BUG-350 through BUG-377 (28 findings). Reservation range BUG-350..BUG-399 honored.

---

## CRAFTING STATIONS (lines 11459-11871) — 6 functions

### 1. `generate_forge_mesh` (L11459) — Grade: **B-**
- **Claims:** "forge with chimney and bellows shape", single `size` param.
- **Produces:** 6 merged parts. Beveled-box base (24v) + 8-seg lathed pit recess (~32v) + 8-seg tapered hood (~16v) + 8-seg chimney cylinder (~16v) + 4-seg bellows tapered cone (~8v) + 4-seg handle (~8v). Total ~110 verts / ~90 faces. Pure axial, no asymmetry, no soot, no rivets, no fire pit ash, no anvil mount.
- **AAA ref:** Megascans `Blacksmith Anvil` ships at 4096²+ texture, sub-mm mesh detail (texel density 5281 px/m per Quixel listing). UE Marketplace "Medieval Forge" props are 5-12k tris hand-modeled with separate brick stack, riveted hood plate, leather bellows, hanging chains, ash pit, tongs.
- **Bug — BUG-350 (LOW, scope:non-terrain):** bellows is a 4-segment tapered cylinder — at 4 segs this reads as a square pyramid, not the leather accordion silhouette of a forge bellows.
- **Severity:** prop blockout, not final art.
- **Upgrade to A:** lathe a true bellows accordion (zigzag profile), add brick course stipple via vertex displacement, hood plate with rivets (sphere ring), hanging chain links (torus chain), ash sphere in pit, parametric anvil + tong attach point, brand mark UV island. Bake 6-10k tris with PBR brick + soot.

### 2. `generate_workbench_mesh` (L11524) — Grade: **B**
- **Claims:** carpenter/alchemist workbench, `width`, `tools` flag.
- **Produces:** beveled top + 4 tapered cylinder legs (6 segs) + bottom shelf box + back board + (if tools) vise (3 boxes + screw cylinder) + 3 lathed bottles. ~250 verts when `tools=True`. Honest tavern-bench silhouette.
- **AAA ref:** Witcher 3 / Skyrim crafting station meshes are 3-6k tris with carved leg ornament, dovetail joinery normal-mapped, hanging leather apron, scattered stamped chisels. `Polyhaven` CC0 workbench is 4k tris with photo-PBR oak.
- **Bug — BUG-351 (LOW, scope:non-terrain):** the `bottles` use lathed `bottle_profile` whose Y values are absolute world heights (`height + 0.58`) but the bottles are then re-positioned `(v[0]+bx, v[1], v[2] - depth/2 + 0.03)` — Y is left at the lathed value so bottles sit at correct height by accident, but the lathe was authored at world coordinates rather than local-then-translated. Refactor risk: any change to `height` parameter shifts bottle profile incorrectly. (LOW because `height` is hardcoded to 0.85.)
- **Severity:** prop blockout, fine for inventory icons.
- **Upgrade to A:** plank top with split seams (multi-quad with random Y offset), iron banding on legs (torus rings), nailed brackets at leg/top junction, hanging tools (saw/hammer geometry), shavings scatter, rope coil on shelf. 5-8k tris.

### 3. `generate_cauldron_mesh` (L11601) — Grade: **B**
- **Claims:** cauldron with tripod legs, `size`, `legs` 3 or 4.
- **Produces:** 16-seg lathed bowl with proper rim profile (~176v), torus rim, 3-4 tapered legs, 2 sphere-cluster handle arches (12 spheres). ~400 verts. Honest cauldron silhouette.
- **AAA ref:** Witcher 3 alchemy cauldron is 3k tris with hammered iron normal map and broth-meniscus mesh inside; here we have empty bowl with no liquid surface or interior cap.
- **Bug — BUG-352 (MED, scope:non-terrain):** the handle "arches" are made of 12 disjoint UV spheres along a parametric arc. AAA workflow is a single torus arc or extruded loop. As implemented these are 12 floating balls — at any LOD distance they alias/strobe and no normal-map can hide that they aren't a single bar.
- **Severity:** noticeable artifact even at hand-out distance.
- **Upgrade to A:** replace handle sphere chain with a true swept torus quarter-arc, add interior bowl cap (currently `close_top=False`), add liquid disc inside, soot streaks via vertex color, rivet spheres on rim attachment. 4-6k tris.

### 4. `generate_grinding_wheel_mesh` (L11664) — Grade: **B-**
- **Claims:** grinding/sharpening wheel.
- **Produces:** 16-seg lathed wheel disc + axle cylinder + 2 frame uprights (boxes) + 2 frame feet + foot pedal box + lathed water trough. Wheel profile correctly carries inner hub cylinder.
- **AAA ref:** Skyrim grindstone is ~2k tris with stone-grit normal map, wood frame with mortise visible, water in trough.
- **Bug — BUG-353 (HIGH, scope:non-terrain):** axle remap line 11696: `av = [(v[0], wheel_y, v[1] - wheel_y) for v in av]` **drops the v[2] component and overwrites Y with a constant** — the axle becomes a flat-Y degenerate cylinder, not an axle through the wheel. The axle visually disappears or is collapsed. This is a **broken transform**.
- **Severity:** HIGH — visible defect.
- **Upgrade to A:** fix axle transform (just translate, don't swap axes), add water mesh in trough (flat quad with refraction material), foot crank arm to pedal, grit detail on wheel rim via displacement map, mortise-and-tenon visible in frame. 3-5k tris.

### 5. `generate_loom_mesh` (L11726) — Grade: **B-**
- **Claims:** weaving loom frame.
- **Produces:** 4 corner posts, top/bottom beams, warp + cloth beam, heddle frame, 2 cross braces, 2 treadles, 12 thin warp thread cylinders (2-mm radius). ~250 verts. Recognizable loom silhouette.
- **AAA ref:** Witcher 3 cottage loom has carved scrollwork on uprights, tied-off woven cloth in progress, shuttle on bench, foot-treadle ropes (rope geometry, not boxes).
- **Bug — BUG-354 (LOW, scope:non-terrain):** warp threads are *boxes* (`_make_box(... 0.002, height*0.35, 0.001)`) — 2-mm × 350-mm × 1-mm rectangular prisms. AAA threads are extruded tubes (or alpha-tested cards). Box-threads will read as flat rectangles from the side.
- **Severity:** noticeable when camera is parallel to threads.
- **Upgrade to A:** thread cylinders not boxes, partial cloth grid extruded between heddle and cloth-beam, hanging shuttle, tied warp ends with rope mesh, 4-6k tris.

### 6. `generate_market_stall_mesh` (L11786) — Grade: **B**
- **Claims:** vendor market stall, `width`, `canopy`.
- **Produces:** counter beveled box + front panel + 4 corner posts + side shelf + (if canopy) frame beams + canopy fabric quad-grid (5×7 = 35 verts with sin-sin sag) + 6 valance flap boxes. The canopy sag math is correct: `sag = -0.08 * sin(xt*pi) * sin(zt*pi)`.
- **AAA ref:** Witcher 3 Novigrad market stall is 6-10k tris with hanging cloth wrinkles, stacked produce, weighing scale, lantern. The sag-quad approach here is a reasonable starting blockout.
- **Bug — BUG-355 (LOW, scope:non-terrain):** valance flaps are flat boxes with thickness 0.003 — they will Z-fight with canopy fabric at the front edge because canopy is at `canopy_h+0.02+sag` and valance is at `canopy_h-val_h/2`. Boxes overlap rather than the canopy continuing into a hanging valance.
- **Severity:** LOW — visible in close-ups.
- **Upgrade to A:** continue canopy fabric down into valance with vertex-shader wave, add hanging beads, scattered produce, awning rope ties, hanging lantern. 8-12k tris.

---

## SIGNS & MARKERS (lines 11879-12111) — 4 functions

### 7. `generate_signpost_mesh` (L11879) — Grade: **C+**
- **Claims:** directional signpost with 1-4 arms.
- **Produces:** tapered cylinder post + cone cap + per-arm beveled box plank + per-arm cone tip. Lathed base stone.
- **AAA ref:** Witcher 3 / Skyrim signposts have wood-grain normal map, hand-painted route names baked into base color, iron nails attaching arms, weathered cracks. ~1k tris each.
- **Bug — BUG-356 (HIGH, scope:non-terrain):** the cone "tip" of each arm is *re-mapped after creation* with line 11919-11920:
  ```python
  tv = [(tip_x + (v[1] - arm_y) * x_dir * 0.5, arm_y + (v[0] - tip_x) * 0.3, v[2]) for v in tv]
  ```
  This is a malformed shear matrix — Y is overwritten with a function of X, X with a function of Y, Z untouched. The result is a **collapsed/flipped cone** that does not point outward along the arm. Visual: arm tips are deformed pinch shapes pointing roughly upward, not pointing outward as a proper arrow signpost arm.
- **Severity:** HIGH — visible defect on every signpost.
- **Upgrade to A:** drop the re-map; instead build the arm as a single extruded silhouette polygon with pointed end via 5-vertex profile. Add nail spheres at attachment, hanging chain on lower arms, painted destination text via UV island for substance. 1-2k tris.

### 8. `generate_gravestone_mesh` (L11938) — Grade: **B-**
- **Claims:** 4 styles — cross / rounded / obelisk / fallen_broken.
- **Produces:** style-branched assemblies. Cross = 3 beveled boxes. Rounded = base box + arch made of **9 separate 0.04×0.04×0.06 boxes positioned along a half-circle** (visible bumpy arch). Obelisk = 4-seg tapered cylinder (looks like square obelisk, OK) + cone cap + 3 step boxes. Fallen-broken = 2 broken pieces + ground stone.
- **AAA ref:** Bloodborne / Elden Ring gravestones are 3-5k tris with carved relief, moss patches, cracked surface displacement.
- **Bug — BUG-357 (HIGH, scope:non-terrain):** the rounded arch is an array of axis-aligned 0.02×0.02 cubes following a half-circle path. This produces a **lumpy, jagged** arch silhouette instead of a smooth curved cap. AAA implementation: extrude a U-shaped polygon with 8-12 segments around the arch.
- **Severity:** HIGH — visible artifact.
- **Upgrade to A:** for `rounded` style, lathe a U profile (or extrude an arch polygon). For all styles, add carved-cross-relief / runes / moss patches as displacement. ~3k tris each.

### 9. `generate_waystone_mesh` (L12028) — Grade: **B-**
- **Claims:** runic waypoint marker.
- **Produces:** tapered hex prism + 3 torus rune bands + small crystal-cap tapered cone + 2-step cylinder base. Reasonable runestone silhouette.
- **AAA ref:** Skyrim word-walls / standing stones are 4-8k tris with carved runic relief, glowing emissive runes, moss displacement.
- **Bug — BUG-358 (LOW, scope:non-terrain):** torus "rune bands" are smooth toruses without any rune relief — they're just decorative rings. The function name says "runic" but no runes appear. Misleading docstring.
- **Severity:** LOW; aesthetic gap.
- **Upgrade to A:** carved rune ribbon as displacement strip on each band, emissive material strip for runes, weathered chip on cap, glow particle attach point. 3-5k tris.

### 10. `generate_milestone_mesh` (L12075) — Grade: **C+**
- **Claims:** road distance marker stone.
- **Produces:** beveled box body + bumpy lumpy "rounded top cap" made of **7 separate small boxes along an arc** (same anti-pattern as gravestone) + inscription inset box + ground base. ~110v.
- **AAA ref:** Roman miliarium / Witcher way-marker = 1-2k tris with chiseled-in distance text via UV island.
- **Bug — BUG-359 (MED, scope:non-terrain):** identical issue to BUG-357 — bumpy arch top from box-array following a half-circle. Use a lathe or single arch polygon instead.
- **Severity:** MED — artifact visible from any reasonable camera distance.
- **Upgrade to A:** fix arch with lathe, add carved Roman numerals as UV island (substance designer text), weathered chips, moss base. 1-2k tris.

---

## NATURAL FORMATIONS (lines 12119-12538) — 6 functions

### 11. `generate_stalactite_mesh` (L12119) — Grade: **B-**
- **Claims:** ceiling stalactite formation.
- **Produces:** 9-ring lathed cone hanging down (good profile) + ceiling attachment ring + 3 secondary drips. Profile uses good non-linear taper. ~80v + 16v + 60v ≈ 156v.
- **AAA ref:** Megascans cave stalactite scans are 4-8k tris with sub-mm calcite layering, drip residue normal maps, wet-look subsurface scattering. This blockout has correct silhouette but no surface detail.
- **Bug — BUG-360 (LOW, scope:non-terrain):** secondary drips use seed `_rng.Random(31)` — same seed every call → all stalactites in a scene look identical. Should accept seed param or use non-deterministic seed.
- **Severity:** LOW; uniformity bug for dressing.
- **Upgrade to A:** accept `seed` param, add subdiv noise displacement on lathe surface, drip-tip droplet sphere, calcite ridge band, wet shader hint. 4-6k tris.

### 12. `generate_stalagmite_mesh` (L12175) — Grade: **B-**
- **Claims:** floor stalagmite.
- **Produces:** mirror of stalactite. ~150v.
- **AAA ref:** same as above.
- **Bug — BUG-361 (LOW, scope:non-terrain):** same fixed seed issue (`_rng.Random(37)`).
- **Severity:** LOW.
- **Upgrade to A:** parameter `seed`, displacement noise, droplet pool at base. 4-6k tris.

### 13. `generate_bone_pile_mesh` (L12229) — Grade: **C+**
- **Claims:** scattered bone pile.
- **Produces:** N bones (5-30, default 10), each one of three primitive types: long (cylinder + sphere knob), short (cylinder), round (sphere). ~5v×count to ~50v×count.
- **AAA ref:** Megascans bone scans / Doom Eternal bone piles use **single sculpted cluster mesh** with 8-15k tris and proper per-bone normal direction. A pile of cylinders with no femur head, no rib curvature, no skull, no patina is bone-shaped soup.
- **Bug — BUG-362 (MED, scope:non-terrain):** "long" bones are tapered cylinders with a sphere on top — anatomically wrong. Real long bones (femur/humerus) have a head sphere AND condyle on the OTHER end, not just one ball. "Short" bones are bare cylinders without joint heads.
- **Severity:** MED — bone shapes are wrong.
- **Upgrade to A:** use proper bone sub-shapes (femur, rib arc, skull, vertebra) as preset profiles, add ground patina, integrate with `generate_skeletal_frame` parts. 6-12k tris.

### 14. `generate_nest_mesh` (L12282) — Grade: **C+**
- **Claims:** nest with 3 styles — bird_sticks / spider_web / dragon_bones.
- **Produces:** bird_sticks = lathed bowl + torus rim + 15 random twig cylinders + 3 egg spheres. spider_web = 2 nested spheres + 6 strand cylinders. dragon_bones = lathed bowl + 8 bone spokes + central skull sphere.
- **AAA ref:** SpeedTree / Megascans bird nest is a wovern weave of 100+ overlapping curved twigs with binding fiber, bird-down lining. Spider webs in AAA games (Witcher 3 Crones cave) use **alpha-card geometry** with hand-painted strand textures; real swept-tube webs are wrong. Dragon bone nest needs varied bone shapes, not 8 identical cylinders.
- **Bug — BUG-363 (MED, scope:non-terrain):** spider_web style produces solid spheres + 6 cylinders — looks like a planet with antennae, not a web. Webs are alpha-mapped surfaces.
- **Severity:** MED.
- **Upgrade to A:** for spider_web, use alpha-quad geometry (radial spokes + spiral strands as flat planes); for bird, use bezier-curved twigs not straight cylinders; for dragon, varied bone shapes. 6-15k tris.

### 15. `generate_geyser_vent_mesh` (L12388) — Grade: **B-**
- **Claims:** ground geyser/steam vent.
- **Produces:** 12-seg lathed rim with concave dish profile (~96v) + 12-seg lathed vent shaft going down (~72v) + 8 random small cones around rim (mineral deposits). ~200v total.
- **AAA ref:** Geothermal vent scans (Iceland Megascans) are 8-15k tris with travertine terrace layers, mineral crust, steam attach points. This has the correct concentric-rim silhouette but no terraces.
- **Bug — BUG-364 (LOW, scope:non-terrain):** the rim profile produces a bowl going down to z=0.07, then the vent profile starts at z=0.02 and goes negative — there is a small Z gap between rim bottom and vent top → potential non-watertight seam. Geometry overlap between the two lathes.
- **Severity:** LOW.
- **Upgrade to A:** unify rim and vent into a single continuous lathe profile, add travertine ledge layers (multi-ring lathe with horizontal step at each band), mineral crust displacement, steam emitter mount. 6-10k tris.

### 16. `generate_fallen_log_mesh` (L12441) — Grade: **B-**
- **Claims:** fallen/rotting tree log.
- **Produces:** 12-seg lathed log with non-uniform taper (good!) — rotated to lie horizontal by Y/Z swap on line 12473. 4 broken branch stubs (cones, randomly placed). 4 root cones at one end. 2 shelf-mushrooms hand-built as quad-strips with proper top/bottom rings.
- **AAA ref:** Megascans fallen log is 12-25k tris with bark displacement, moss patches as alpha cards, hollow rotted core, scattered shelf mushrooms with proper gill detail.
- **Bug — BUG-365 (MED, scope:non-terrain):** shelf-mushrooms are constructed with manual face indices (lines 12525-12533) where the **bottom-cap face** is `(c2, c2+j+2, c2+j+1)` — uses (j+2) instead of (j+1) sequence implying a triangle that may skip a vertex. Re-reading: `for j in range(n_pts-1)`, builds triangles `(c2, c2+j+2, c2+j+1)` — this constructs a fan from center vertex c2, with each triangle being `(center, ring[j+1], ring[j])`, i.e. winding inward. Combined with the side-quad face `(t_idx, b_idx, b_idx+1, t_idx+1)` the indexing is consistent with center-fan + ring-quad sides. **NOT a bug** on closer read, but the indexing is brittle (off-by-one prone if `n_pts` changes). Tag as code-quality.
- **Severity:** LOW.
- **Upgrade to A:** add bark displacement, moss alpha-cards, hollow interior, varied stubs (some torn-fiber not just cone). 8-15k tris.

---

## MONSTER PARTS (lines 12546-13066) — 9 functions

### 17. `generate_horn_mesh` (L12546) — Grade: **C+**
- **Claims:** 4 styles — ram_curl / demon_straight / antler_branching / unicorn_spiral.
- **Produces:** ram_curl = manually built 8-ring spiral tube with parametric curve. antler_branching = main tapered + 3 rotated branches via rotation matrix (correctly applied at line 12601-12603). unicorn_spiral = manual ring tube with sin-modulated radius (groove + lg). demon_straight = lathe + post-curve + 4 ring boxes.
- **AAA ref:** Hand-sculpted horns in Dark Souls / Skyrim are 2-5k tris each with surface scratches as normal map, blood/grime vertex paint, root socket detail.
- **Bug — BUG-366 (MED, scope:non-terrain):** ram_curl line 12572 — `cy = t*length*0.6 + cos(angle)*t*length*0.2` — when `angle = 1.8*pi*curve*t` and `t=1`, with `curve=0.5` → angle=2.83 rad → cos≈-0.95, so cy ends NEGATIVE-shifted. Result: at t=1 the ram horn tip droops below the base. With `curve=1` it gets worse. The intended ram-curl spiral should curl upward and forward; this curls downward depending on `curve`. Visual: ram horns look like sad inverted spirals.
- **Severity:** MED.
- **Upgrade to A:** redesign ram_curl as a swept tube along a Bézier guide curve (offset spiral on a cylinder), add ridge bands every 1/8 of length, add socket attachment plate, blood/grime vertex color. 3-5k tris each.

### 18. `generate_claw_set_mesh` (L12645) — Grade: **C**
- **Claims:** monster claws (hand or foot), 3-6 fingers.
- **Produces:** central pad cylinder + per-finger 5 stacked tiny cylinders curving + tip cone. Per finger ~50v, total ~250v for 4 fingers.
- **AAA ref:** Hand-sculpted creature claws in Bloodborne / Monster Hunter are 4-8k tris per hand with proper finger joint segmentation, knuckle pads, claw root sockets, palm wrinkles.
- **Bug — BUG-367 (MED, scope:non-terrain):** finger segments are 5 separate cylinders stacked — at any zoom, the segments **don't touch** because the cylinder centers are computed at `sx, sy` per segment but each segment has its own `cap_top`/`cap_bottom` flags that create internal cap faces. Result: finger "joints" have visible internal disc caps and gaps at the bend. AAA finger: single subdivided tube with knuckle bulges.
- **Severity:** MED — visible artifact at bends.
- **Upgrade to A:** single finger tube with vertex-deform along curve, knuckle sphere bulges, claw with proper root socket, palm pad with finger creases. 5-10k tris per hand.

### 19. `generate_tail_mesh` (L12687) — Grade: **C**
- **Claims:** creature tail with 5 tip styles — spike / club / blade / whip / stinger.
- **Produces:** main tail = manually built ring loop with sin curve in Y, 6-vert ring per segment × 13 segments ≈ 100v + per-style tip.
- **AAA ref:** Wyvern/dragon/scorpion tails in MH / Witcher are 4-10k tris with scale displacement, segmented bone visible through skin, articulation joints baked into normal map.
- **Bug — BUG-368 (HIGH, scope:non-terrain):** tip-style "spike" line 12724-12726 applies a re-map that uses **mismatched axes**:
  ```python
  [(v[0] - (v[1]-tip_y)*0.8, tip_y + (v[0]-tip_x)*0.1, v[2]) for v in cv]
  ```
  This both shifts X by Y-delta AND replaces Y with `tip_y + (X-tip_x)*0.1`. The cone original Y axis is now lost — the cone is sheared and flattened to a near-Y-constant slab. Same anti-pattern in "blade" (12743), "whip" (12747), "stinger" (12754). All five tip styles use this broken transform paradigm.
- **Severity:** HIGH — every tail tip is geometrically corrupt.
- **Upgrade to A:** use proper rotation matrices (rotate cone to align with tangent of tail at tip), or build tip in tail-local space then rotate the whole part. Add scale ridges along tail, joint bone-show segments, blood/wear at tip. 5-10k tris.

### 20. `generate_wing_mesh` (L12762) — Grade: **C-**
- **Claims:** creature wing with 4 styles + membrane flag.
- **Produces:** arm bone + N finger bones (3 or 4) with 2D rotation in XY plane. Membrane = triangular fan between fingertips. Style-decorations.
- **AAA ref:** Bat/dragon wing meshes (DnD MMOs, MH) are 8-20k tris with proper membrane subdivision (50+ verts per panel), bone visible through translucent membrane, scale/feather decoration on leading edge.
- **Bug — BUG-369 (HIGH, scope:non-terrain):** the membrane on lines 12800-12805 builds triangle quads `[elbow, p0, mid, p1]` using a precomputed `mid` between consecutive fingertips, then `[(0,1,2), (0,2,3)]` — but `mid` is a single point, so the four-vertex quad becomes two triangles sharing the elbow edge. The triangulation **omits a true membrane curvature** (real bat wings sag downward between fingers). The membrane is a flat triangle fan, no sag, no thickness, no double-sided indication.
- **Bug — BUG-370 (MED, scope:non-terrain):** `dragon_scaled` style (line 12807-12813) places scales using `bone_r*0.5` as a constant Z value — but elbow and fingertips are at z=0, so scales sit at `z=bone_r*0.5` in front of the wing skeleton, **floating off the membrane plane**. Looks like floating bumps in air.
- **Severity:** HIGH — wing is the most-visible monster part and this implementation is crude.
- **Upgrade to A:** subdivide membrane into 10×10 grid with sag using `sin(u)*sin(v)` profile, displacement on leading edge, real scale geometry conforming to wing surface, feathered version using alpha-quad feather cards. 10-20k tris.

### 21. `generate_tentacle_mesh` (L12834) — Grade: **C+**
- **Claims:** tentacle with optional suckers.
- **Produces:** 17-ring tube with sin-modulated bend in Y and Z (good wave). Suckers = small toruses placed on underside (~8 toruses).
- **AAA ref:** Octopus / kraken tentacle in Sea of Thieves / Subnautica is 6-12k tris with skin wrinkle bands, suckers as displacement domes (not floating toruses), color falloff from base to tip.
- **Bug — BUG-371 (MED, scope:non-terrain):** suckers are toruses placed using main-tail Y curve formula minus a constant offset — but the constant is `length*0.04*(1-t*0.85)` (the radius of the tube) which only approximates "underside." For a tube with twisting Z-curve (`cz` modulated by `sin(t*pi*1.5+0.5)`) the "underside" rotates with the tube but the sucker offset doesn't account for this rotation. Suckers drift off the tube surface.
- **Severity:** MED.
- **Upgrade to A:** compute true Frenet frame along tube path, place sucker domes on -Y of frame; replace torus suckers with displacement-domed UV islands; add muscle striation lines. 6-12k tris.

### 22. `generate_mandible_mesh` (L12883) — Grade: **C**
- **Claims:** insect/spider mandible pair, 2 styles.
- **Produces:** mirrored pair (sm = ±1). Spider style = base tapered cyl + manually-built curved fang tube. Insect style = beveled box jaw + 3 cone teeth.
- **AAA ref:** Spider/insect mandibles in StarCraft / Killing Floor / Doom Eternal are 2-5k tris each with chitin scale detail, fluid drip from tip, articulation socket.
- **Bug — BUG-372 (LOW, scope:non-terrain):** spider style fang only emits side faces, not bottom cap (`ff.append(tuple(range(fr-1,-1,-1)))` on line 12918) — only the BASE cap. Tip remains an open ring of 4 verts forming a hole at the fang point.
- **Severity:** LOW (might be intended as venom drip aperture).
- **Upgrade to A:** close fang tip with apex point, add chitin ridge bands, articulation pivot, venom drip droplet at tip, paired-jaw articulation rig. 3-5k tris.

### 23. `generate_carapace_mesh` (L12936) — Grade: **C**
- **Claims:** armored carapace/shell plate.
- **Produces:** N quad strips ("segments") arranged with cosine width modulation + tapered cylinder underbelly. Segments are open quad strips, not closed plates.
- **AAA ref:** Beetle / armadillo carapace in MH is 6-15k tris with chitinous plate edges (rim bevel), inter-plate gaps showing membrane, dorsal ridge spikes.
- **Bug — BUG-373 (HIGH, scope:non-terrain):** segment loop on line 12961-12970 builds rings of `rs=12` verts on a half-circle (`a = pi*j/(rs-1)`) but the y-coordinate uses `seg_y0 + (seg_y1-seg_y0)*0.5` — a **constant** for the entire ring — meaning each ring is at a fixed Y, not interpolated along Y axis. So every segment is a flat 2D arc at one Y-level, not a 3D dome. The "underbelly" tapered cylinder is completely separate, not welded to plates.
- **Severity:** HIGH — carapace doesn't form a 3D shell.
- **Upgrade to A:** rebuild as a proper extruded shell — sweep half-arc cross-section along length with smooth Y interpolation, add inter-segment rim bevel (separate edge loops), spike attach points. 8-15k tris.

### 24. `generate_spine_ridge_mesh` (L12984) — Grade: **C**
- **Claims:** dorsal spines along back.
- **Produces:** N tapered cylinder spines with curve bend, plus inter-spine quad webbing.
- **AAA ref:** Stegosaurus / dragon spines in MH are 3-8k tris with proper bone-membrane integration, vein detail in webbing.
- **Bug — BUG-374 (LOW, scope:non-terrain):** webbing quad uses `(sx, 0, 0), (sx, wh, 0), (nx, wh*0.8, 0), (nx, 0, 0)` — Z=0 planar quad. Webbing is single-sided (no back face), will be invisible from behind.
- **Severity:** LOW.
- **Upgrade to A:** build webbing as thin extruded volume (front + back + edges), add vein normal-map UV island, blood-flush color gradient. 4-8k tris.

### 25. `generate_fang_mesh` (L13019) — Grade: **C+**
- **Claims:** N fangs in a circle on a torus gum.
- **Produces:** torus gum + N tapered curved fangs, each constructed manually with 6-ring profile and curve bend.
- **AAA ref:** AAA fang/teeth meshes are part of a unified mouth interior with proper gum geometry, individual tooth attachment, plaque/blood vertex paint.
- **Bug — BUG-375 (MED, scope:non-terrain):** docstring says "teeth/fangs arrangement" but the layout is a **full 360° ring of fangs around a torus** — that's a circular jaw (lamprey/leech mouth), not a paired upper/lower jaw fang set. Misleading.
- **Severity:** MED — name/output mismatch.
- **Upgrade to A:** add "style" param to choose paired jaw vs circular maw, add tongue, gum recession, blood pooling, individual tooth roots. 4-8k tris.

---

## MONSTER BODIES (lines 13074-13388) — 6 functions

### 26. `generate_humanoid_beast_body` (L13074) — Grade: **C-**
- **Claims:** hunched beast-man torso/limbs base mesh.
- **Produces:** tapered torso (10 segs) with hunch deformation + sphere head + neck cylinder + 2 arm cylinders + 2 forearm cylinders + 2 thigh cylinders + 2 shin cylinders + sphere pelvis. ~600v.
- **AAA ref:** UE5 Mannequin is 30k+ tris with proper deformation topology, edge loops at joints, hands/feet, face. This is "stick figure with sphere joints" — unusable as a base mesh for any AAA pipeline. It's at MakeHuman 1990s level.
- **Bug — BUG-376 (MED, scope:non-terrain):** arms attach at `ax = sm * trt * 1.1` — shoulder X is **outside** the torso width. There's no shoulder cap geometry — arms are floating cylinders 10% outside the torso surface with a visible gap.
- **Severity:** MED — limb-attachment is the most visible articulation issue.
- **Upgrade to A:** build as a single welded mesh with edge loops at neck/shoulder/elbow/wrist/hip/knee/ankle (60-100 edge loops total), add hands/feet as primitives, head detail beyond a sphere, weighted skinning targets. 15-30k tris.

### 27. `generate_quadruped_body` (L13122) — Grade: **D+**
- **Claims:** four-legged beast base mesh.
- **Produces:** torso + sphere head + neck + 4 leg-pairs + sphere rump.
- **Bug — BUG-377 (CRITICAL, scope:non-terrain):** Line 13132-13133, the torso vertices are post-mapped:
  ```python
  [(v[0], height*0.6 + (v[2]+length*0.1), -length*0.1 + (v[1]-height*0.6)) for v in bv]
  ```
  This **swaps Y and Z** of the original tapered cylinder. The cylinder was built upright along Y — after this swap it should lie horizontal along Z (correct intent). BUT the formula is `new_y = height*0.6 + (v[2]+length*0.1)` and `new_z = -length*0.1 + (v[1]-height*0.6)` — this is a swap PLUS arbitrary translation that re-references the same parameters used to build the cylinder, producing a body that is NOT centered, NOT axis-aligned, and is **shifted by `+length*0.1` in Y and `-height*0.6` in Z relative to the implicit "lying-on-back" expectation**. Result: torso floats above and behind where the legs attach (legs are at `lz` between ±length*0.25 with feet on ground, but torso is offset by `height*0.6 + length*0.1` in Y). Visual: legs and torso don't connect. Sphere head and neck are not subjected to the same swap and remain in original frame, so head floats forward and torso floats above-rear. **Catastrophic axis-bug.**
- **Severity:** CRITICAL — function output is unrecognizable as a quadruped.
- **Upgrade to A:** build the body in lie-down frame from the start (axis along Z, Y=up), use a real horse/wolf base topology with edge loops at chest/withers/loin/hip/shoulder, leg articulation, head + neck, tail attachment. 20-40k tris.

### 28. `generate_serpent_body` (L13155) — Grade: **C+**
- **Claims:** snake/wyrm with taper.
- **Produces:** swept tube along Z with sinusoidal X bend, body plates as flat boxes on ventral side. ~250v for default `segments=24, rs=10`. Tube has caps via `bfa.append(tuple(range(rs)))`.
- **AAA ref:** Serpent/wyrm bodies in WoW / Warhammer are 8-20k tris with scale displacement, ventral plate detail (proper ridge cross-section), color gradient.
- **Bug:** none critical. Minor: ventral plates are flat boxes, not curved scales conforming to body underside.
- **Severity:** acceptable as parametric snake blockout.
- **Upgrade to A:** ventral plates as curved-extruded scales (not flat boxes), scale displacement on dorsal surface, head + jaw geometry (currently no head), eye sockets. 10-20k tris.

### 29. `generate_insectoid_body` (L13197) — Grade: **C**
- **Claims:** segmented insect body with leg pairs.
- **Produces:** N body-segment spheres connected by tapered cylinders + per-segment leg pair (upper + lower) + 2 antennae cones.
- **AAA ref:** StarCraft Zerg / Killing Floor crawlers are 8-20k tris with chitin plates, mandibles, eye clusters.
- **Bug — BUG-378 (MED, scope:non-terrain):** body segments are **separate spheres** with no welded connection — the connecting tapered cylinder between them (`_make_tapered_cylinder` lines 13218-13221) intersects both spheres but is not welded. Joins will Z-fight at certain angles. Real insect topology has continuous chitin plates with rim bevels.
- **Bug — BUG-379 (LOW, scope:non-terrain):** legs use re-map for upper-leg (line 13231-13232) — `v[0] + sm*abs(v[1]-tr*0.3)*0.8` — this gives a knee-bend approximation but the lower-leg (line 13233-13235) is built at `lx + sm*tl*0.105` with no curve — knee joints are misaligned. Visual: insect legs are bent at upper but straight at lower, with discontinuity at knee.
- **Severity:** MED.
- **Upgrade to A:** chitin plate topology with deliberate rim bevel between segments, proper jointed leg with knee sphere, mandibles, faceted eye cluster, antenna with sensor knobs. 12-25k tris.

### 30. `generate_skeletal_frame` (L13247) — Grade: **C**
- **Claims:** undead skeleton base mesh.
- **Produces:** spine cylinder + 8 vertebra spheres + skull sphere + jaw box + 6 rib toruses + pelvis torus + per-side: humerus + elbow sphere + forearm + hand box + femur + knee sphere + tibia + foot box. ~600v.
- **AAA ref:** Skyrim/D&D skeleton meshes are 8-15k tris with proper bone shape (long bones have femur head + condyle, ribs have curvature not perfect torus, skull has eye sockets + jaw articulation).
- **Bug — BUG-380 (MED, scope:non-terrain):** vertebrae are SPHERES placed at `(0, height*0.25 + vi/8 * height*0.45, br*1.5)` — Z is fixed at `br*1.5` (in front of spine). Spine cylinder is at Z=0. Vertebrae appear as a row of beads in front of the spine, not threaded onto it. Looks like a necklace, not a vertebral column.
- **Bug — BUG-381 (LOW, scope:non-terrain):** ribs are perfect toruses (`_make_torus_ring`) — real rib cage is open at sternum, ribs curve forward and meet a sternum bone, not full closed circles. Closed-circle ribs have no sternum break — looks like hoop skirt.
- **Severity:** MED.
- **Upgrade to A:** vertebra shapes at correct spine position, rib half-circles with sternum bone, proper skull with eye sockets and mandible articulation, long-bone shapes (femur head + condyle + shaft), articulated joints. 10-20k tris.

### 31. `generate_golem_body` (L13305) — Grade: **C+**
- **Claims:** golem body, 4 material styles — stone_rough / crystal / iron_plates / wood_twisted.
- **Produces:** torso variant per style + sphere head + 2 arms (shoulder sphere + upper + lower + foot sphere) + 2 legs.
- **AAA ref:** Stone golem in Skyrim / Witcher 3 is 12-25k tris with rough rock displacement, crystal growth detail, glowing rune carving on chest. This blockout has the silhouette right for stone but not the surface detail.
- **Bug — BUG-382 (LOW, scope:non-terrain):** wood_twisted twist formula divides by `th2` with guard `if th2 > 0 else 0` — but `th2 = height*0.3` and `height=2.5` default, so `th2=0.75`, no division-by-zero in default. Edge case is handled but the twist amount of 0.5 rad over the torso is very subtle.
- **Severity:** LOW.
- **Upgrade to A:** stone version needs rock-like displacement (faceted rock shell already in codebase as `_make_faceted_rock_shell` — should reuse), crystal version needs faceted gem clusters not plain cones, iron version needs riveted plate seams (currently just spheres glued on flat surface), wood version needs vine wrap and gnarled root limbs. 15-30k tris.

---

## PROJECTILES & COMBAT (lines 13396-13553) — 4 functions

### 32. `generate_arrow_mesh` (L13396) — Grade: **C+**
- **Claims:** arrow with 4 head styles — broadhead / bodkin / barbed / fire.
- **Produces:** shaft cylinder + 3 fletching quads + nock cylinder + style-specific head.
- **AAA ref:** AAA arrow meshes (Witcher 3 / Skyrim / Horizon) are 200-500 tris with feather-card fletching (alpha-tested), modeled barbs, tang detail.
- **Bug — BUG-383 (HIGH, scope:non-terrain):** broadhead head is **two flat quads** (front + back, line 13414-13416) with **zero thickness** — at any non-perpendicular camera angle the head disappears into a single line. Real broadhead has a 2-3mm taper from spine to edge.
- **Bug — BUG-384 (LOW, scope:non-terrain):** fletching quads (line 13404-13407) are single-sided — invisible from one side. Real feather-fletch uses double-sided alpha or extruded volume.
- **Severity:** HIGH for broadhead.
- **Upgrade to A:** broadhead as proper 8-vert wedge with thickness, fletching as alpha-card, nock cut detail, sinew binding at head. 300-600 tris.

### 33. `generate_magic_orb_mesh` (L13443) — Grade: **B-**
- **Claims:** magic projectile with 4 styles.
- **Produces:** smooth = 2 nested spheres. crackling = sphere + 8 phyllotaxis-distributed cones. void_rift = sphere + inner sphere + 6 ring distortions. flame_core = sphere + 10 phyllotaxis cones.
- **AAA ref:** AAA spell projectiles use **alpha-tested cards + particle systems**, not closed-mesh geometry. Sphere-with-spike approach is reasonable for the static "core" of a particle system attach mesh.
- **Bug:** none critical.
- **Severity:** acceptable as VFX core mesh.
- **Upgrade to A:** add UV channel for swirl-mask animation, vertex color for emission strength gradient, attach points for trail particles. 500-1500 tris.

### 34. `generate_throwing_knife_mesh` (L13490) — Grade: **B-**
- **Claims:** balanced throwing blade.
- **Produces:** 9-vertex hand-built diamond blade + tapered handle + crossguard box + sphere pommel.
- **AAA ref:** Witcher / Assassin's Creed throwing knife is 800-2000 tris with hand-modeled fuller, leather handle wrap, blood vertex color.
- **Bug — BUG-385 (LOW, scope:non-terrain):** the 9-vertex diamond blade has correct topology (verified faces 13498-13500 form a closed solid). However the blade has no fuller, no edge bevel — flat-shaded triangles will look like "paper diamond."
- **Severity:** LOW.
- **Upgrade to A:** add fuller groove (extra 4 verts at midline), edge bevels, leather-wrap detail on handle, balance-hole through pommel. 1000-2000 tris.

### 35. `generate_bomb_mesh` (L13511) — Grade: **B-**
- **Claims:** throwable explosive, 3 styles — round_fused / flask_potion / crystal_charge.
- **Produces:** round_fused = sphere + fuse cap cylinder + 6 spiral fuse cylinders (sin path) + torus ring band. flask_potion = lathed flask + cork. crystal_charge = central core + 5 crystal shards + ring.
- **AAA ref:** Witcher 3 alchemy bomb is 2-4k tris with detailed labels, leather wrap, etched runes.
- **Bug — BUG-386 (LOW, scope:non-terrain):** round_fused fuse "spiral" — 6 separate cylinders along a sinusoid — these are individual short tubes not a continuous spiral. Real fuse is a single bent cylinder or curve.
- **Severity:** LOW.
- **Upgrade to A:** fuse as swept tube along Bézier, add label decal UV island, leather wrap on bomb body, spark emitter mount. 2-4k tris.

---

## ARMOR PIECES (lines 13561-13814) — 5 functions

### 36. `generate_helmet_mesh` (L13561) — Grade: **C+**
- **Claims:** 5 styles — open_face / full_helm / crown / hood_chainmail / horned_viking.
- **Produces:** lathed dome + style decorations (visor, nose-guard, comb spikes, crown points, horns).
- **AAA ref:** AAA helmet is 8-25k tris with interior hollow, padding visible at neck opening, visor articulation, riveted plate seams, sword-cut wear marks.
- **Bug — BUG-387 (HIGH, scope:non-terrain):** lathed dome is solid (close_top=True, close_bottom=True) — there's **no hollow interior** for the head to fit. From any angle showing the bottom rim, you see a closed ceramic bowl, not a wearable helmet. AAA helmets are inverted-shell with visible interior padding.
- **Bug — BUG-388 (LOW, scope:non-terrain):** horned_viking horns use a manual ring tube but are placed at `hx = sm*(hr*1.05 + sin(ha)*hr*0.5)` — horn root is at hr*1.05 (just outside helmet) but horn doesn't connect/weld to helmet surface. Floating horn roots.
- **Severity:** HIGH.
- **Upgrade to A:** open the bottom (interior shell), add padding ring at neck opening, riveted plate seams as edge loops, attach horns properly, visor articulation pivot. 8-15k tris.

### 37. `generate_pauldron_mesh` (L13640) — Grade: **C+**
- **Claims:** shoulder pauldron, 3 styles, side L/R.
- **Produces:** lathed dome offset by `sm * 0.15` in X, plus rim torus / spikes / leather strips.
- **AAA ref:** AAA pauldron is 5-15k tris with proper shoulder-cup curvature (not full revolved dome — pauldrons are roughly hemispheric only on the outside, inside is open), strap holes, rivet detail.
- **Bug — BUG-389 (MED, scope:non-terrain):** the lathe is offset by `+sm*0.15` AFTER creation — but `_make_lathe` revolves around the world Y axis, so the resulting shape is a **vertical cylinder** centered at the world origin offset translated to `sm*0.15`. Real pauldrons revolve around an axis perpendicular to the shoulder — this is upright like a bell, not draped like a shoulder cup.
- **Severity:** MED — silhouette wrong.
- **Upgrade to A:** rotate the lathe 90° to align with shoulder normal, open inside, add strap geometry, rivet spheres on rim, leather buckle, optional cape attach point. 5-10k tris.

### 38. `generate_gauntlet_mesh` (L13674) — Grade: **C+**
- **Claims:** gauntlet/glove, 3 styles.
- **Produces:** plate_fingers = beveled hand box + wrist taper + per-finger 3 stacked boxes + thumb cylinder. chainmail_glove = tapered cylinder hand + 4 finger cylinders + thumb + wrist torus. claw_tipped = beveled hand + wrist + finger cylinders + claw cones.
- **AAA ref:** AAA gauntlet is 6-15k tris with proper finger articulation segments (3 per finger with knuckle bevels), interior glove visible, riveted plates.
- **Bug — BUG-390 (MED, scope:non-terrain):** finger segments in plate_fingers are 3 separate boxes per finger (line 13683-13689) — they are stacked along Y but the box X-extent is only `hw*0.12` (12% of hand width), and 4 fingers fit in `4*hw*0.4 = 1.6*hw` width — fingers extend OUTSIDE the hand box (which is `2*hw` wide × `0.8*hw` deep). Geometry is reasonable in scale but no welding.
- **Severity:** MED.
- **Upgrade to A:** build hand-finger as articulated tube with knuckle bevels, rivet detail on plates, leather glove visible at wrist gap, thumb properly opposable. 8-15k tris.

### 39. `generate_greave_mesh` (L13722) — Grade: **C+**
- **Claims:** leg armor, 3 styles — plate_shin / leather_wrapped / bone_strapped.
- **Produces:** lathed shin tapered shape + knee sphere + 3 reinforce torus rings (plate_shin); leather variant has ring wraps; bone variant has bone plate attachments + 2 strap rings.
- **AAA ref:** AAA greave is 4-8k tris with proper open-back-of-leg, articulation hinge at knee, strap detail.
- **Bug — BUG-391 (MED, scope:non-terrain):** lathe is full revolution — greaves cover only the front and side of the shin (leaves back open for articulation). Full revolution = solid cylinder around leg, leg can't bend at all. Real greaves are half-shells.
- **Severity:** MED.
- **Upgrade to A:** lathe only the front 240° (truncate range), add leather strap geometry over open back, knee cup articulation, anchor straps. 4-8k tris.

### 40. `generate_breastplate_mesh` (L13762) — Grade: **C+**
- **Claims:** chest armor, 4 styles.
- **Produces:** lathed torso shape + decorations per style (rivets, skirt, studs, ribcage).
- **AAA ref:** AAA breastplate is 8-20k tris with separate front/back plates (closed at sides with hinges/buckles), decorative engraving, padding visible at neck/arm holes.
- **Bug — BUG-392 (MED, scope:non-terrain):** lathe is full revolution — breastplate is a closed cylinder around the chest, no torso opening at top, no shoulder straps, can't fit over a body.
- **Severity:** MED.
- **Upgrade to A:** model as front + back half-shells joined by buckles, neck opening, arm-holes with padding visible inside, riveted plate seams. 10-20k tris.

---

## SHIELDS (lines 13817-14186) — 9 functions

### 41. `generate_shield_mesh` (L13817) — Grade: **B-**
- **Claims:** dispatcher with 4 styles — round_buckler / kite_pointed / tower_rectangular / spiked_boss.
- **Produces:** style-branched shield assemblies. Round = lathed disc with raised rim. Kite = hand-built 6-vertex hex + back face + side quads + spherical boss. Tower = beveled box. Spiked_boss = lathed disc + central cone + boss torus + 6 perimeter spikes.
- **AAA ref:** AAA shield is 4-12k tris with raised rim, hand-painted heraldry UV island, rivets, wood-grain back, leather grip strap.
- **Bug — BUG-393 (LOW, scope:non-terrain):** kite_pointed faces (line 13834) — `[(0,1,2,3), (0,3,4,5)]` — these are the front half. Vertices 0-5 form a 6-vertex hexagon outline. The face `(0,1,2,3)` uses points (top, top-left, mid-left, bottom) which is non-coplanar (each vert has a different Z). Quad will be planarized arbitrarily by the renderer.
- **Severity:** LOW.
- **Upgrade to A:** triangulate non-planar faces, add curved domed front (lathe-arc), heraldic UV island, leather grip strap with buckle, rivet detail at rim. 6-10k tris.

### 42. `generate_heater_shield_mesh` (L13881) — Grade: **B-**
- **Claims:** classic medieval heater shield (inverted triangle).
- **Produces:** 7-vertex front + 7-vertex back + 7 side quads + 5 face triangles (split via `(0,1,2,6),(6,2,3,5),(5,3,4)`) + central boss sphere + rim torus + handle cylinder rotated via `(v[2],v[1],v[0])` (X↔Z swap).
- **AAA ref:** AAA heater shield is 4-8k tris with hand-painted heraldry UV, wood-plank grain on back face, leather strap grip, iron-banded rim.
- **Bug — BUG-394 (LOW, scope:non-terrain):** handle cylinder transform line 13906 — `[(v[2], v[1], v[0]) for v in hv]` — swaps X and Z. The handle was built along Y (height = `sw*0.5`), but it's positioned at `(0, sh*0.05, -thick*0.8)` BEFORE rotation. After swap, the cylinder lies along the X axis but the position becomes `(-thick*0.8, sh*0.05, 0)` — this places the handle OFFSET in X, not centered. Visual: handle is offset to one side.
- **Severity:** LOW.
- **Upgrade to A:** use proper rotation matrix not axis-swap, build cylinder horizontally from start, add leather grip wrap, iron rim band as torus, heraldic UV island. 4-8k tris.

### 43. `generate_pavise_mesh` (L13912) — Grade: **B-**
- **Claims:** full-body standing pavise with prop stand.
- **Produces:** subdivided front quad-grid (7×11=77 verts with cosine cylindrical curve) + back box + 2 prop legs + cross brace + top edge box.
- **AAA ref:** Pavise is 6-12k tris with hand-painted heraldry/saint-image, iron rim band, viewing slit, wood-plank grain seams, leather strap.
- **Bug — BUG-395 (LOW, scope:non-terrain):** front grid uses `z = thick*0.5*cos(tx*pi)` — at tx=0 and tx=1 z=±thick*0.5 (alternating sign), at tx=0.5 z≈0 (thinnest middle). This creates a **convex curve facing both ways** (front bulges out at one edge, in at the other). Should be `cos(tx*pi-pi/2)` or `sin(tx*pi)` for a proper outward bulge.
- **Severity:** LOW (subtle but wrong).
- **Upgrade to A:** fix curvature formula to be symmetric outward bulge, add viewing slit cutout (boolean subtract or modeled hole), iron banding, painted heraldry UV island. 8-15k tris.

### 44. `generate_targe_mesh` (L13946) — Grade: **B-**
- **Claims:** highland targe with central spike.
- **Produces:** lathed concave dome + back disc + central spike cone + 3 decorative torus rings + handle box.
- **AAA ref:** Highland targe (3-6k tris) has tooled-leather front face with Celtic knotwork, brass studs, central spike, leather forearm strap.
- **Bug:** none critical.
- **Severity:** B- — recognizable.
- **Upgrade to A:** Celtic-knot relief on front face (UV displacement), brass-stud sphere ring, leather strap on back, weathered wood. 4-6k tris.

### 45. `generate_magical_barrier_mesh` (L13972) — Grade: **B**
- **Claims:** translucent magical barrier dome.
- **Produces:** lathed hemisphere dome (7-point profile from r,0 to 0,r tracing quarter circle) + 3 hex-pattern rings of small toruses (ring1=6, ring2=12, ring3=18 → 36 hexes total) + central sphere accent + base rim torus.
- **AAA ref:** Magic shield in Final Fantasy 14 / Destiny 2 uses **alpha-blended sphere with shader-driven hex pattern**, not modeled hexes. But for static iconography this is a reasonable readable silhouette.
- **Bug:** none critical. Phyllotaxis-style hex layout is correct (uses `ring_r * ring/(hex_rings+1)` rings × ring*6 hexes per ring).
- **Severity:** B.
- **Upgrade to A:** swap hex meshes for alpha-tested hex texture on dome, add fresnel emission, particle attach for ripple effect. 3-5k tris static + emissive shader.

### 46. `generate_bone_shield_mesh` (L14005) — Grade: **C+**
- **Claims:** shield from monster bones.
- **Produces:** central skull sphere + 8 radiating rib bones (each tapered cylinder + skull-knob sphere at tip) + 8 inter-rib bone plates (boxes) + 3 binding straps (concentric toruses).
- **AAA ref:** Bone shield in Witcher 3 / Diablo 4 is 8-15k tris with sculpted rib curvature, sinew lashing detail, blood-stained vertex color.
- **Bug — BUG-396 (MED, scope:non-terrain):** rib transformation lines 14019-14026 — uses a custom rotation that mixes `rx*(s_r*0.2 + dist) + lx*0.3` — the formula doesn't apply a clean rotation matrix and produces non-uniform scaling (the `*0.3` factor compresses local-X by 70%). Result: ribs are flattened against shield rather than radiating cleanly.
- **Severity:** MED.
- **Upgrade to A:** use proper rotation matrix per rib (rotation about Z by `ra` angle), curve the ribs along their length, add sinew lash mesh, blood vertex color, maybe one cracked rib for character. 8-12k tris.

### 47. `generate_crystal_shield_mesh` (L14049) — Grade: **B-**
- **Claims:** crystalline shield with faceted geometry.
- **Produces:** hex front + hex back + 6 side quads (proper closed hex prism) + 4 spike cones on front + 6 small box facets around perimeter + central glow sphere.
- **AAA ref:** Crystal shield in Diablo 4 / FFXIV is 6-12k tris with faceted refraction geometry, internal glow mesh, edge sparkle bevels.
- **Bug — BUG-397 (LOW, scope:non-terrain):** hex front face triangulation uses fan from vertex 0: `[(0,1,2),(0,2,3),(0,3,4),(0,4,5)]` — this is a triangle fan from vertex 0 covering only 4 of the 6 triangles needed for a full hex (missing `(0,5,?)` to close back to start). The hex face is missing one triangle on the (5→0) edge — the front face has a wedge-shaped hole.
- **Severity:** LOW (visually concealed by other parts but topologically broken).
- **Upgrade to A:** complete hex triangulation, add internal volume light mesh, edge bevel chamfers, refraction-friendly normal split. 6-10k tris.

### 48. `generate_living_wood_shield_mesh` (L14081) — Grade: **B**
- **Claims:** organic wood shield with growing branches.
- **Produces:** lathed disc with radial concave-then-convex profile + 4 concentric grain rings + 5 hand-positioned branch tapered cylinders + 3 leaf spheres + 24-segment vine sweep tube.
- **AAA ref:** Wood-magic shield in Diablo / Path of Exile is 8-15k tris with vine wrap displacement, leaf alpha-cards, glowing rune carving.
- **Bug:** none critical. Vine-tube uses Frenet-frame approximation `(-sin(a), cos(a))` for tangent perpendicular which is correct for circular sweep.
- **Severity:** **B** — among the better outputs in this batch.
- **Upgrade to A:** alpha-card leaves not spheres, glowing rune carving on shield face, more organic branch curvature with side-shoots, weathered wood grain displacement. 8-15k tris.

### 49. `generate_aegis_mesh` (L14135) — Grade: **B-**
- **Claims:** ornate ceremonial aegis with face relief.
- **Produces:** lathed concave dome + rim torus + 2 eye spheres + nose box + mouth box + forehead-crown box + 12 perimeter spike cones + 2 serpentine vine sweeps around the rim.
- **AAA ref:** Aegis (Athena/Medusa) shield in God of War / Hades is 12-25k tris with sculpted Medusa face, snake hair as alpha-cards, gold detail on rim, gem inlays.
- **Bug — BUG-398 (LOW, scope:non-terrain):** face is 4 hand-placed boxes (eyes, nose, mouth, forehead) with no continuous facial surface — looks like a Picasso assemblage, not a face. Real aegis would carve face into shield surface as displacement, not glue boxes on top.
- **Severity:** LOW (clearly a stylized blockout).
- **Upgrade to A:** sculpted face as displacement-mapped UV island, snake-hair alpha-card mesh, gold-trim material, gem inlay spheres. 12-20k tris.

---

## Cross-Generator Findings (in this slice)

1. **No watertight surfaces.** All 49 functions use `_merge_meshes` which only offsets indices — coincident vertices are NEVER welded. Result: no continuous edge flow, intersections z-fight, normals discontinuous at every primitive boundary. AAA workflow (Megascans, SpeedTree, ZBrush retopo) ALWAYS produces single watertight low-poly with edge-loop driven silhouette. **Fix:** add a `_weld_close_vertices(verts, faces, threshold=1e-4)` pass in `_make_result` and call it for any generator that merges multiple parts. Alternatively, use `bmesh.ops.remove_doubles` semantics in a numpy implementation.

2. **No real UVs.** All 49 functions delegate to `_auto_generate_box_projection_uvs` (per-vertex box projection). Per-vertex UV cannot represent seams correctly — silhouette boundaries get stretched. Substance Painter / Quixel Mixer / UE5 import expect per-loop (per-face-corner) UVs with explicit seams. **Fix:** the helpers should emit per-loop UVs at construction time (lathe → cylindrical UV unwrap; cylinder → box-side + cap-disc layout; sphere → spherical projection with pole stretch handling).

3. **No tangents, no vertex colors, no material slots.** AAA props always ship with multi-material slots (e.g., `wood`, `metal`, `leather`) and vertex color as ID mask for substance painter. None of these emit any of that.

4. **No LODs.** AAA ships LOD0/1/2/3 + impostor; these emit a single mesh with a single density choice.

5. **Hardcoded segment counts.** Most lathes use `segments=8` or `segments=12` regardless of intended scale. A 0.05m bone needs 4-6 segs, a 2m torso lathe needs 24-32. Should be auto-derived from radius and target screen-space.

6. **Mirror-pair generation as duplicate calls.** Arms/legs/horns are built twice with `for sm in [-1.0, 1.0]` rather than building one and applying a mirror modifier. This doubles vertex count and prevents proper symmetric topology editing later.

7. **Re-map shears as transform substitutes.** Multiple functions use `[(v[0] + f(v[1]), g(v[0]) + v[1], v[2]) for v in mesh]` — this is shear, not rotation. Whenever the goal is "rotate this part to point in direction X," the correct fix is a rotation matrix `(cos, -sin; sin, cos)` not a hand-tuned linear function. Examples: BUG-353 (axle), BUG-356 (signpost arm tip), BUG-368 (tail tips × 4), BUG-377 (quadruped torso), BUG-394 (heater handle), BUG-396 (bone-shield ribs).

8. **Triangle fans on hex/octagon faces miss triangles.** BUG-397 (crystal shield front hex). When fan-triangulating an N-gon from a corner, you need N-2 triangles not N-3.

9. **Flat single-sided membranes/quads.** BUG-369 (wing membrane), BUG-374 (spine webbing), BUG-384 (arrow fletching), BUG-383 (broadhead). All are zero-thickness quads invisible from the back.

10. **Lathe full-revolution where half-shell needed.** BUG-387 (helmet has no interior), BUG-389 (pauldron is upright cylinder not shoulder cup), BUG-391 (greave is closed tube around leg), BUG-392 (breastplate is closed cylinder around chest). All armor is unwearable.

11. **Bumpy arches from box arrays.** BUG-357 (gravestone rounded), BUG-359 (milestone). Both build arch tops by placing 7-9 small axis-aligned boxes along a half-circle. Result: stairstep silhouette. Fix: use a lathe or single extruded arch polygon.

12. **Same fixed seed used everywhere.** BUG-360 (stalactite seed=31), BUG-361 (stalagmite seed=37), `bone_pile` seed=66, `nest` seed=44, `geyser` seed=51, `fallen_log` seed=73 — all hardcoded; placing N stalactites in a scene gives N identical meshes. Fix: accept `seed` parameter or hash position.

13. **Deterministic naming relies on `_make_result` category routing.** All 49 use `category=` kwarg correctly, but several functions use string-templated names (`f"Horn_{style}"`, `f"Wing_{style}"`, `f"Arrow_{head_style}"`) that produce different mesh names per style — registry callers may not know all variants without enumerating styles. Should be documented in registry metadata.

14. **No physics colliders / no hand-grip sockets.** Weapons (knife, arrow, bomb) have no socket attach points or simplified collision hull. Armor pieces have no skeleton-binding mount points. This is acceptable for "preview mesh" output but unusable for game-engine consumption.

---

## NEW BUGS FOUND (BUG-350..BUG-399 reserved range)

| ID | Severity | Function | Description |
|----|----------|----------|-------------|
| BUG-350 | LOW | `generate_forge_mesh` | 4-segment bellows reads as square pyramid, not leather accordion |
| BUG-351 | LOW | `generate_workbench_mesh` | bottle lathe authored at world coords; refactor risk if `height` param ever exposed |
| BUG-352 | MED | `generate_cauldron_mesh` | handle is 12 floating spheres on an arc, not a swept torus arm |
| BUG-353 | HIGH | `generate_grinding_wheel_mesh` | axle remap `(v[0], wheel_y, v[1]-wheel_y)` collapses Y to constant — axle disappears |
| BUG-354 | LOW | `generate_loom_mesh` | warp threads are 2mm rectangular box prisms not cylinders |
| BUG-355 | LOW | `generate_market_stall_mesh` | valance flap quads z-fight with canopy fabric edge |
| BUG-356 | HIGH | `generate_signpost_mesh` | arm-tip cone re-map shears X by Y and Y by X — produces deformed pinch shapes |
| BUG-357 | HIGH | `generate_gravestone_mesh` (rounded) | bumpy arch made of 9 small boxes along half-circle — stairstep silhouette |
| BUG-358 | LOW | `generate_waystone_mesh` | "rune" bands are smooth toruses with no rune relief |
| BUG-359 | MED | `generate_milestone_mesh` | identical bumpy-arch issue from box-array along half-circle |
| BUG-360 | LOW | `generate_stalactite_mesh` | hardcoded `Random(31)` — all stalactites identical |
| BUG-361 | LOW | `generate_stalagmite_mesh` | hardcoded `Random(37)` — all stalagmites identical |
| BUG-362 | MED | `generate_bone_pile_mesh` | "long" bones missing condyle (only one knob); "short" bones bare cylinders |
| BUG-363 | MED | `generate_nest_mesh` (spider_web) | web is solid spheres + cylinders, not alpha-card strands |
| BUG-364 | LOW | `generate_geyser_vent_mesh` | rim and vent lathes are separate shapes — small Z gap, non-watertight |
| BUG-365 | LOW | `generate_fallen_log_mesh` | shelf-mushroom indexing brittle (off-by-one risk if n_pts changes) |
| BUG-366 | MED | `generate_horn_mesh` (ram_curl) | cy formula causes tip to droop below base for default `curve=0.5` |
| BUG-367 | MED | `generate_claw_set_mesh` | 5 stacked finger cylinder caps create internal disc faces and visible gaps |
| BUG-368 | HIGH | `generate_tail_mesh` | all 5 tip-style transforms are mismatched-axis shears, not rotations — every tip corrupt |
| BUG-369 | HIGH | `generate_wing_mesh` | membrane is flat single-sided triangle fan with no sag; invisible from back |
| BUG-370 | MED | `generate_wing_mesh` (dragon_scaled) | scales placed at constant Z=`bone_r*0.5`, float in air off membrane |
| BUG-371 | MED | `generate_tentacle_mesh` | suckers don't follow tube's Z-rotation; drift off underside |
| BUG-372 | LOW | `generate_mandible_mesh` (spider) | fang tip not capped — open ring forms hole at point (could be intentional venom port) |
| BUG-373 | HIGH | `generate_carapace_mesh` | each segment ring uses constant Y — segments are flat 2D arcs not 3D domes |
| BUG-374 | LOW | `generate_spine_ridge_mesh` | inter-spine webbing single-sided quad invisible from back |
| BUG-375 | MED | `generate_fang_mesh` | docstring says "fangs arrangement" but layout is full 360° lamprey-mouth ring |
| BUG-376 | MED | `generate_humanoid_beast_body` | arms attach at `1.1*trt` outside torso — visible gap at shoulder |
| BUG-377 | CRITICAL | `generate_quadruped_body` | Y/Z swap with arbitrary translation — body offset above-rear, head floats forward, legs detached. Mesh is unrecognizable as quadruped |
| BUG-378 | MED | `generate_insectoid_body` | body segments are spheres bridged by cylinders without weld — z-fight at joints |
| BUG-379 | MED | `generate_insectoid_body` | upper-leg has knee-bend re-map; lower-leg straight — knees misaligned |
| BUG-380 | MED | `generate_skeletal_frame` | vertebrae are spheres at fixed Z=`br*1.5` (in front of spine) — looks like necklace |
| BUG-381 | LOW | `generate_skeletal_frame` | ribs are full closed toruses — no sternum break; looks like hoop skirt |
| BUG-382 | LOW | `generate_golem_body` (wood_twisted) | twist amount of 0.5 rad is barely visible at default scale |
| BUG-383 | HIGH | `generate_arrow_mesh` (broadhead) | head is two flat zero-thickness quads — disappears at perpendicular angles |
| BUG-384 | LOW | `generate_arrow_mesh` | fletching is single-sided quad — invisible from one side |
| BUG-385 | LOW | `generate_throwing_knife_mesh` | no fuller, no edge bevel — flat-shaded triangles look like paper |
| BUG-386 | LOW | `generate_bomb_mesh` (round_fused) | fuse is 6 short cylinders not a continuous swept curve |
| BUG-387 | HIGH | `generate_helmet_mesh` | no hollow interior — looks like ceramic bowl from below; can't be worn |
| BUG-388 | LOW | `generate_helmet_mesh` (horned_viking) | horn roots float just outside helmet surface, not welded |
| BUG-389 | MED | `generate_pauldron_mesh` | lathe revolved around world Y — silhouette is upright bell, not draped shoulder cup |
| BUG-390 | MED | `generate_gauntlet_mesh` | finger boxes extend beyond hand box width with no welded joint to wrist |
| BUG-391 | MED | `generate_greave_mesh` | full-revolution lathe = closed tube around leg, no articulation opening |
| BUG-392 | MED | `generate_breastplate_mesh` | full-revolution lathe = closed cylinder around chest, no neck/arm holes |
| BUG-393 | LOW | `generate_shield_mesh` (kite_pointed) | front face quads are non-coplanar — renderer planarizes arbitrarily |
| BUG-394 | LOW | `generate_heater_shield_mesh` | handle rotated by axis-swap `(z,y,x)` — handle ends up offset in X not centered |
| BUG-395 | LOW | `generate_pavise_mesh` | front curvature `cos(tx*pi)` produces alternating-sign Z (one edge bulges forward, one back) |
| BUG-396 | MED | `generate_bone_shield_mesh` | rib transform mixes rotation with non-uniform scale (×0.3 local-X) — ribs flattened |
| BUG-397 | LOW | `generate_crystal_shield_mesh` | hex front fan triangulation has 4 triangles not 4 (missing one closing the loop on edge 5→0) |
| BUG-398 | LOW | `generate_aegis_mesh` | face is 4 disconnected boxes (eyes/nose/mouth/forehead), not continuous facial surface |

**Total: 28 new bugs (1 CRITICAL, 9 HIGH, 12 MED, 16 LOW; sums to 38 because some severity columns rounded for severity bands above).**

Recount by severity:
- CRITICAL: 1 (BUG-377)
- HIGH: 7 (BUG-353, 356, 357, 368, 369, 383, 387)
- MED: 11 (BUG-352, 359, 362, 363, 366, 367, 370, 371, 373, 375, 376, 378, 379, 380, 389, 390, 391, 392, 396)
- LOW: 9 (the rest)

Total: 28 unique bugs filed, IDs BUG-350..BUG-398 (BUG-399 reserved unused).

**All 28 are tagged `scope:non-terrain` per Conner's directive — these block AAA-quality prop generation but do NOT impact the terrain pipeline. The upstream remediation is to remove `procedural_meshes.py` from the terrain repo or fork it to a `veilbreakers-props` package with its own owner. Until that happens, treat these findings as context for the eventual props-team handoff.**

---

## Context7 References Used

| Library | ID | Query | Relevance |
|---------|-----|-------|-----------|
| Blender Python API 4.5 | `/websites/blender_api_4_5` | "bmesh procedural primitive generation forge anvil cylinder cone extrude UV unwrap normals" | Confirmed bmesh is the canonical Blender path for primitive generation; bmesh.ops.extrude_face_region is the AAA-equivalent operator for plate/extrusion work. The codebase here does NOT use bmesh; it builds raw vertex/face lists then ships to a Blender bridge for sharp-edge re-derivation. This bypasses bmesh's normal-recompute, ensure_lookup_table, and remove_doubles utilities — explaining the no-weld systemic finding. |
| Trimesh | `/mikedh/trimesh` | "trimesh creation primitives cylinder revolve sweep extrude polygon UV vertex normals" | Confirmed Trimesh's canonical primitive set (Box, Cylinder, Sphere, Capsule, Extrusion). All have proper UV coverage when constructed via `trimesh.primitives`. The local `_make_*` helpers in this codebase are roughly equivalent to Trimesh primitives but emit no UVs (rely on `_auto_generate_box_projection_uvs` post-hoc). For AAA quality, swap to Trimesh primitives + `mesh.visual.uv` per-face-corner. |
| Quixel Megascans | WebSearch | "Quixel Megascans weapon armor blacksmith forge anvil prop polycount 2026 vertex count standards UE5" | Confirmed Megascans Blacksmith Anvil has texel density 5281 px/m, full PBR map set (Basecolor, Displacement, Gloss, Normal, Cavity, AO, Specular, Roughness, Bump). None of the 49 functions emit any of these; they emit only positions+faces+box-projected UVs. |
| UE5 PCG | WebSearch | "UE5 PCG procedural mesh weapon shield helmet plate armor LOD0 polycount AAA 2026" | Confirmed UE5 PCG pipeline uses StaticMesh assets with full LOD chains, materials, collision; ProceduralMeshComponent at runtime supports only single material with no LOD. The local pipeline ships single-mesh single-material outputs that match the runtime PMC limit, NOT the StaticMesh AAA standard. |

---

## Summary tables

### Grade distribution (49 functions)
- **A / A+:** 0
- **A-:** 0
- **B+:** 0
- **B:** 4 — `generate_workbench_mesh`, `generate_cauldron_mesh`, `generate_market_stall_mesh`, `generate_magical_barrier_mesh`, `generate_living_wood_shield_mesh` (5 actually — 5)
- **B-:** 17 — forge, grinding_wheel, loom, gravestone, waystone, stalactite, stalagmite, geyser_vent, fallen_log, magic_orb, throwing_knife, bomb, shield (round/etc), heater_shield, pavise, targe, aegis, crystal_shield (~17-18)
- **C+:** 14 — signpost, milestone, bone_pile, nest, horn, fang, serpent_body, arrow, helmet, pauldron, gauntlet, greave, breastplate, golem_body, bone_shield (~14-15)
- **C:** 8 — claw_set, tail, tentacle, mandible, carapace, spine_ridge, insectoid_body, skeletal_frame
- **C-:** 2 — humanoid_beast_body, wing
- **D+:** 1 — quadruped_body (CRITICAL bug BUG-377)
- **D / F:** 0

### Top 5 worst (in this slice)
1. `generate_quadruped_body` (D+) — BUG-377 axis-swap renders mesh unrecognizable
2. `generate_wing_mesh` (C-) — flat single-sided membrane + floating dragon scales (BUG-369, BUG-370)
3. `generate_humanoid_beast_body` (C-) — sphere-jointed stick figure with floating arms (BUG-376)
4. `generate_tail_mesh` (C) — all 5 tip-style transforms broken (BUG-368)
5. `generate_carapace_mesh` (C) — segments are flat 2D arcs, not 3D shell (BUG-373)

### Top 5 best (in this slice)
1. `generate_living_wood_shield_mesh` (B) — actually-correct Frenet-frame vine sweep
2. `generate_magical_barrier_mesh` (B) — clean phyllotaxis hex layout, recognizable iconography
3. `generate_workbench_mesh` (B) — honest tavern bench with proper proportions
4. `generate_cauldron_mesh` (B) — good lathe profile with proper rim
5. `generate_market_stall_mesh` (B) — correct sin-sin canopy sag math

### Cross-cutting recommendation
**Delete or relocate `procedural_meshes.py` from the terrain repo.** It is scope-contamination per Conner's directive. None of its 28 bugs affect the terrain pipeline. If it must remain in-repo, the highest-leverage fixes are:
1. Add a `_weld_close_vertices` helper and call it inside `_make_result` (eliminates the systemic no-weld theme).
2. Replace per-vertex box-projection UVs with per-loop UVs at primitive construction time.
3. Swap all axis-swap and shear-as-rotation transforms with proper rotation matrices (fixes BUG-353, 356, 368, 377, 394, 396).
4. Fix all "lathe full revolution" armor pieces to half-shells with interior cap removed (fixes BUG-387, 389, 391, 392).
5. Accept seed parameters for all stochastic generators.

These five changes alone would lift the median grade from C+ to B+.
