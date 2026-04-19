# P2 — procedural_meshes.py L3379-6998 Deep-Dive Audit (Opus 4.7 ultrathink)

**Scope:** 49 generator functions (one helper) — weapons (crossbow → estoc), throwing weapons, off-hand focuses, architectural details, fences/barriers/railings.
**Standard:** AAA-shipped quality (Megascans / SpeedTree / UE5 PCG / Houdini / Blender Geometry Nodes). Judges *results*, not technique names.
**Method:** AST-enumerated, every body read end-to-end, primitive call sites cross-checked against helper definitions (`_make_box` 8v/6f, `_make_cylinder` 2*N v / N+caps f, `_make_cone` N+1 v / N+cap f, `_make_torus_ring` major*minor v / major*minor f, `_make_sphere` rings*sectors v, `_make_beveled_box` faceted box, `_make_lathe` profile-revolved).

---

## Summary

| Result | Count | Functions |
|---|---:|---|
| A+ ships in Megascans | 0 | — |
| A ships in UE5 default | 0 | — |
| A− missing 1 feature | 0 | — |
| B+ correct but thin | 0 | — |
| B blockout (workable greybox) | 9 | `tome`, `greatsword`, `greataxe`, `halberd`, `glaive`, `staff_magic`, `rapier`, `bridge` (stone arch only), `staircase` (spiral) |
| B− blockout with bug | 7 | `gate`, `fence`, `railing`, `bridge` (rope/drawbridge), `staircase` (straight stringer), `fountain`, `flail` |
| C+ partial / unconvincing silhouette | 18 | `crossbow`, `scythe`, `whip`, `claw`, `curved_sword`, `hand_axe`, `battle_axe`, `mace`, `warhammer`, `shortbow`, `longbow`, `wand`, `paired_daggers`, `twin_swords`, `dual_axes`, `dual_claws`, `bladed_gauntlet`, `iron_fist` |
| C stub silhouette | 11 | `throwing_knife_weapon`, `brass_knuckles`, `cestus`, `estoc`, `javelin`, `throwing_axe`, `shuriken`, `bola`, `orb_focus`, `skull_fetish`, `holy_symbol`, `totem`, `gargoyle`, `statue`, `barricade` |
| D broken topology / non-functional | 3 | `_make_bow_limb` (fan-fold non-manifold), `crossbow` arms (zero-radius rings), `whip` (overlapping cylinders w/ massive curvature gap) |
| F placeholder | 0 | — |

**TOTAL: 0 ship-quality, 9 acceptable greybox, 40 below greybox or buggy. Zero functions hit AAA bar.**

**Verdict against Megascans / SpeedTree / UE5 PCG:** Megascans weapon kits have 5–50 k tris with 4 k textures and bevel/wear/dirt baked from high-poly. SpeedTree foliage has 100 k+ tris with wind, LODs, billboard imposters. UE5 default Mannequin sword is 8 k tris with PBR maps. **None of the 49 functions in this range produce a mesh that would survive a 1080p screenshot at 1 m camera distance**: silhouettes are 4–8 segment cylinders, topology has T-junctions and degenerate triangles, no UVs are computed (defaults assigned later), no normals are smoothed, "carved details" like skull eye sockets are *additive spheres protruding outward* not Boolean-cut indentations. The architectural pieces (fountain, statue, gate, fence, railing, bridge, staircase) are LEGO-block stand-ins, ~20-200 primitives glued together by `_merge_meshes` with no welding, no shared topology, no bevels at primitive joints. Even the relatively complex `tome` is a stack of 4 boxes + 1 lathed spine + 4 sphere clasps with zero authored UVs and a flat 6-segment cylinder "emblem".

---

## Per-function entries

### 1. `generate_crossbow_mesh`  L3379-3444  ✦ **D**
- **Claims:** "crossbow mesh with mechanism"
- **Produces:** stock = 1 beveled box (~24 v); trigger guard = 1 box (8 v); **bow arms = 14 cylinders (7 per side)**, each `cap_top=False, cap_bottom=False` so they are open tubes that don't connect; **string = single triangle (3 v / 1 face)**; rail = 1 box; bolt = 1 tapered cylinder. Total ≈ 200 v / 100 f.
- **Bug-class:** (a) the cross-arm cylinders use `r = 0.01 * s * (1.0 - t * 0.3)` and at the **last segment** `t=1.0` ⇒ r=0.007, but the cylinder height passed is `r * 2 = 0.014` — these are tiny disconnected unjoined tubes laid along a non-curve, **not a continuous limb**. (b) Open-ended cylinders create non-manifold gaps. (c) `string_v` y-coordinate is `-arm_len * 0.3 * arm_len` (units²) — negative-y dangling triangle below, not taut between limb tips. (d) No prod/lath/tickler/lock/nut/trigger.
- **AAA ref:** Quixel/Megascans crossbow scans = lath as continuous swept curve (NURBS extruded), riser block, tiller, prod-tip nocks, twisted-bowstring (8-strand cylinders), trigger nut + sear + tickler kinematic chain. UE5 Marketplace crossbows ship 4-8 k tris.
- **Severity:** D — broken bow limbs + degenerate string + no mechanism.
- **Upgrade:** lath as one swept profile (cross-section extruded along Bezier control points), proper twisted bowstring (multi-strand `_make_torus_ring` chained), separate trigger guard as torus segment, add prod ring, working string anchor at limb tips.

### 2. `generate_scythe_mesh`  L3447-3505  ✦ **C+**
- **Claims:** "reaper scythe mesh"
- **Produces:** shaft = tapered cylinder (~108 v); blade = 13 rings × 3 verts (39 v) connected by **only 2 quads per segment** (line 3493 `for j in range(2)` instead of 3) — the back face of the blade triangle never connects, leaving an **open seam** along the spine; collar = small torus.
- **Bug:** Loop `for j in range(2)` should be `range(3)` (or close the modular loop) — produces a non-manifold C-shaped blade cross-section; light leaks through. Also `edge_w * sin(t*pi + 0.2)` goes negative beyond t≈0.94, flipping the cutting edge inside out at the tip.
- **AAA ref:** SpeedTree/Megascans scythes have asymmetric forged blade with curved spine + ricasso bolt + snath with hand-grip lugs (nibs).
- **Severity:** C+ but with an open-seam topology bug.
- **Upgrade:** close all 3 quads, use 5–7 cross-section vertices (back, front, edge tip, top spine, bottom spine), add nibs (perpendicular hand grips on the snath).

### 3. `generate_flail_mesh`  L3508-3584  ✦ **B−**
- **Claims:** "ball and chain"
- **Produces:** handle taper, pommel sphere, 4 grip toruses, then per-head: chain = `link_count` toruses laid in a **straight diagonal line** with every other link "rotated" by swapping x↔z (line 3560: `tv = [(v[2] + lx, v[1], v[0] - lx)]`) — but the swap is applied AFTER `_make_torus_ring` already places the link at `(lx, ly, 0)`, so the mirror reuses the world coords and produces tangled overlapping loops, not interlocking chain links; ball sphere; spike `_make_cone` ×8.
- **Bug:** chain alternation re-projects already-positioned vertices, the resulting "interlocking" geometry is incorrect — odd links are at `(z+lx, y, x-lx)` which moves them off the chain centerline. Spike orientation is positional only (cone always points +Y) — spikes do not radiate outward, just sit at the sphere surface pointing up.
- **AAA ref:** Real flail = tear-drop ball with cast-in spikes, chain of 4–8 oval links each rotated 90° to its neighbour. Megascans medieval kit handles this with sweep-along-curve.
- **Severity:** B− blockout with chain rotation bug + spike orientation bug.
- **Upgrade:** generate chain via `_swept_torus_along_curve`, orient spikes by computing the surface normal vector from sphere center.

### 4. `generate_whip_mesh`  L3587-3638  ✦ **D**
- **Claims:** "segmented whip"
- **Produces:** handle, pommel sphere, then 20 cylinder segments distributed along a **discontinuous curve**: each segment is placed at `(x_curve, y1, z_curve)` with cap_top/cap_bottom=False **except the first/last** — but the position of segment i+1 is NOT continuous from segment i (each segment has height `seg_len = whip_length/segments` along Y, so segment i top is at `y1 + seg_len`, but segment i+1 base is at `y1 + (1/segs)*whip_len` — these match, BUT the x_curve and z_curve change between i and i+1 by sin/cos, so segment i+1's bottom is laterally displaced from segment i's top, leaving **visible gaps** between every segment).
- **Bug:** Cylinders are axis-aligned (along Y) but the curve is helical → segments separate at every joint. With `length=2.0, segments=20` you get 19 visible gaps. Also `r = handle_r * (1 - t*0.85)` reaches 0.0027 at the tip but `max(r, 0.002)` so it never collapses, no whip-crack.
- **AAA ref:** Whips need swept-along-curve (Catmull-Rom or Hermite) with rotation-minimizing frames so cross-sections stay perpendicular to the tangent.
- **Severity:** D — broken silhouette, segments visibly disconnected.
- **Upgrade:** sample N points along a curve, compute tangent + normal frames, extrude a circle profile per frame.

### 5. `generate_claw_mesh`  L3641-3703  ✦ **C+**
- **Claims:** "monster claw/gauntlet"
- **Produces:** palm = tapered cylinder; wrist guard; per finger (3-5): 4 tube-segments (cap_top/bottom only at extremes) + 1 tip cone. Same gap problem as whip — finger segments use sin/cos curves but each cylinder is along Y, leaving 4 visible gaps per finger. Cones for tips face up Y, not along the finger's tangent.
- **Bug:** `angle = math.pi * 0.3 + (math.pi * 0.4) * i / (finger_count - 1) if finger_count > 1 else math.pi * 0.5` — operator precedence: ternary `if` binds the whole expression so when `finger_count == 1` the angle is computed via `i/(finger_count-1)` first — divides by zero before ternary kicks in. Will crash on finger_count=1 (mitigated by clamp to 3-5, but still latent).
- **AAA ref:** Monster Hunter/Bloodborne claw weapons use one continuous swept mesh per claw with bevelled root mounts on a hand plate.
- **Severity:** C+ — disconnected segments, latent div-by-zero, tip cones misaligned.

### 6. `generate_tome_mesh`  L3706-3800  ✦ **B**
- **Claims:** "spellbook/grimoire"
- **Produces:** front/back covers (beveled boxes), hand-rolled spine (8×5 = 45 verts as a flat strip at x=0 — see bug below), pages box, 4 sphere "clasps", center emblem cylinder (~150 v / 80 f).
- **Bug:** spine_verts all use `x=0` (line 3760), so the spine "profile" with varying r values is collapsed to a single x=0 strip — the curved spine bulge is **only in z**, but the profile's `r` field (named like a radius) is being put into the y coordinate (`y = t * cover_h`), which is wrong: the "radius" field encodes how the spine bulges away from the cover edge in *cover_h-direction* (an offset along y from cover_h/2) — but it's just being used as `y = t*cover_h` regardless. So `r` is silently discarded; the spine is a flat plane at x=0 with z-varying offset. Visually OK on a back-shelf book but the radial bulge claim is false. Clasps are spheres at corners but the loop iterates `yoff in [0.01, cover_h-0.01]` and `zoff in [+spine, -spine]` × right-side-only x — only 4 clasps, missing the other side.
- **AAA ref:** Hogwarts Legacy / Diablo IV grimoires = high-poly cover with sculpted relief, bookmark ribbon, brass corner-protectors, leather strap with buckle.
- **Severity:** B — usable greybox of a closed book.
- **Upgrade:** lathe a real spine cross-section, add 8 corner clasps not 4, model 1-2 ribbon bookmarks, add buckle strap.

### 7. `generate_greatsword_mesh`  L3803-3882  ✦ **B**
- **Claims:** "wide blade, ricasso, two-hand grip"
- **Produces:** handle (~96 v), pommel sphere, 7 grip toruses, guard beveled box, ricasso box, then per-style: flamberge (16-segment wavy box-extrusion + tip pyramid), executioner (single beveled box), standard (10-segment box-extrusion + tip pyramid), fuller box. ~500-800 v.
- **Topology:** flamberge wave is in *width* not perpendicular cross-section, so it's a flat wavy ribbon not a true forged flamberge with twisted cutting edges. Fuller is a separate floating box at z=0 not Boolean-cut into the blade — it z-fights with the blade surface.
- **AAA ref:** ESO/Skyrim greatswords ship with bevelled fuller via inset edge loops.
- **Severity:** B — recognizable greybox; usable for silhouette.
- **Upgrade:** carve fuller via inset loop in the blade vertex strip; flamberge wave should modulate the *cross-section width along the cutting edge only*, not the spine.

### 8. `generate_curved_sword_mesh`  L3885-3939  ✦ **C+**
- **Claims:** scimitar / katana / falchion
- **Produces:** handle, pommel, grip rings, guard (tsuba=cylinder for katana, beveled box otherwise), 13×3 vertex blade strip + tip. ~250-400 v.
- **Bug:** `falchion` width formula `1.0 + t*0.3 - t*t*1.2` peaks at t=0.125 and goes negative at t≈0.93 — `max(w, 0.003)` clamps but leaves the falchion with an unrealistic clavate (club-tip) profile not a clipped-tip falchion. Katana has no kissaki (yokote line), no hamon, no habaki, no menuki — it's just a straight scimitar relabeled.
- **AAA ref:** Ghost of Tsushima katanas have proper kissaki, hamon line via mask, separate habaki, tsuka-ito wrapping geometry. Falchion (Mount & Blade, For Honor) has clipped tip.
- **Severity:** C+ — silhouette OK, but no style differentiation beyond curvature constants.

### 9. `generate_hand_axe_mesh`  L3942-3978  ✦ **C+**
- **Claims:** "small single-head hand axe"
- **Produces:** haft (taper), pommel sphere, head = **8-vertex skewed cube** (literal cube with skewed coordinates) for "blade", collar torus. ~120 v / 50 f. The "blade" is a brick.
- **Bug:** axe head is just a box — no cutting edge, no bit/cheek/eye topology. Three style variants differ only in 4 numeric constants (block dimensions). Bearded/standard/tomahawk all look identical at 5 m.
- **AAA ref:** Megascans axe kits = forged head with proper bit (sharp curve), poll (back), eye (haft-hole boolean), with bevelled cheeks. Tomahawk has spike on poll.
- **Severity:** C+ blockout — workable from 50 m, fails at any close inspection.

### 10. `generate_battle_axe_mesh`  L3981-4042  ✦ **C+**
- Same skewed-cube head approach as hand_axe but two heads for "double", arc-of-quads for "crescent", larger box for "single_large". Pommel + 5 grip rings + collar torus + top spike cone. ~400 v.
- **Bug:** crescent head is a single-thickness curved ribbon (4-vert quads along an arc) — has no edge bevel, so it appears as an infinitely thin moon rather than a forged crescent blade.
- **Severity:** C+ — better than hand_axe by virtue of more parts.

### 11. `generate_greataxe_mesh`  L4045-4099  ✦ **B**
- Massive haft (1.2 m), 8 grip rings, "moon"/cleaver/double heads; same primitives as battle_axe but bigger. 14-segment crescent for "moon" gives a smoother arc. ~600 v.
- **AAA ref:** Dark Souls greataxes have 1.5 k-3 k tris with proper haft binding, fuller channels in the bit, asymmetric bearded shape.
- **Severity:** B greybox — passable silhouette.

### 12. `generate_club_mesh`  L4102-4144  ✦ **C+**
- **Claims:** "rough club with nails/spikes"
- **Produces:** taper handle, taper body, top sphere, 10 spike cones for "spiked" / 5 sphere knobs for "bone", 3 binding rings. ~250 v.
- **Bug:** spike orientation: `nv = _make_tapered_cylinder(sx*1.2, sy, sz*1.2, ...)` — every spike points +Y regardless of which direction it should radiate. With sphere center at (0, head_cy, 0), the spikes should point along (sx, sy-head_cy, sz) but they all point straight up.
- **Severity:** C+ — spikes are wrong-oriented.

### 13. `generate_mace_mesh`  L4147-4203  ✦ **C+**
- Handle, pommel, 4 grip rings, head sphere; per-style: flanged = 7 single-triangle flanges (3 verts, 1 tri each — non-volumetric paper flanges with no thickness, will be invisible from edge-on); studded = 12 small spheres on surface; morningstar = 12 cones (also misoriented like club).
- **Bug:** flanged flanges are flat triangles with no back-face culling consideration → will be invisible from one side; studs/cones don't follow normal direction.
- **AAA ref:** D2R/Diablo IV maces have flanged head as 6-8 sharp prismatic blades with bevelled edges, baked AO at the seam.
- **Severity:** C+ — flanges are 1-tri impostors, not volumetric.

### 14. `generate_warhammer_mesh`  L4206-4249  ✦ **C+**
- Handle, pommel, 5 grip rings; "maul" = 1 box; "lucerne" = box + 5-vert pick pyramid + top spike cone; "standard" = box + small pyramid pick. ~250 v.
- **Bug:** pick pyramid is a 5-vertex hand-rolled pyramid with face `(0, 2, 3, 1)` as base (winding may flip wrong way — should be CCW from outside). The face order `(0,1,4)` then `(1,3,4)` then `(3,2,4)` then `(2,0,4)` — vertices 0,1,2,3 are at x=-0.02 (or -0.015) in 4 corners, vertex 4 is the apex at x=-0.1 — CW or CCW is direction-dependent and not consistent across faces, half the pyramid will normal-invert when shaded.
- **Severity:** C+ — pyramid winding inconsistent.

### 15. `generate_halberd_mesh`  L4252-4310  ✦ **B**
- 2 m pole + tapered base + axe blade box + top spike cone + back-hook pyramid + langets (2 small boxes along pole at head-15cm). For partisan: triangle pyramid head + 2 lugs. ~600 v.
- **Bug:** the `voulge` head is a single box with one "edge" on +x — no cutting bevel, no fuller. The langets at line 4304 `lv, lf = _make_beveled_box(math.cos(angle)*pole_r*0.8, head_y - 0.15, math.sin(angle)*pole_r*0.8, ...)` for angle in [0, π] — produces 2 langets but both lie at the same z (since cos(0)=1, cos(π)=-1, sin(0)=sin(π)=0) → both langets sit on the **x-axis** (same z=0), not 4-around-pole.
- **AAA ref:** For Honor halberds = forged head with axe blade + spike + hook + langet collar with rivets.
- **Severity:** B greybox.

### 16. `generate_glaive_mesh`  L4313-4399  ✦ **B**
- 1.8 m pole, three style variants each with curved blade (10×3-vert strip + tip): naginata (gentle curve), guandao (wide leaf), curved (standard). Collar torus. ~500-700 v.
- Same triangular-cross-section bug as scythe — only 3 quads per segment connect, which here is correct (3-vert profile = 3 quads).
- **Severity:** B — recognizable polearm silhouette.

### 17. `_make_bow_limb`  L4402-4420  ✦ **D** (helper)
- **Claims:** "curved bow limb along Y axis"
- **Produces:** for `(segments+1)` rings, 4 verts per ring (a box cross-section), connected by 4 quads per segment.
- **Bug:** the cross-section is fixed to **world axes** (`x ± w`, `z ± d`) regardless of the curve's tangent — so as the limb curves in z (`sin(t*pi*0.8)*curve`), the box stays axis-aligned and the cross-section *does not rotate to follow the spine*. This is mathematically equivalent to a frame-free extrusion: at the tip where dz/dt is large, the cross-section is misaligned with the tangent. Classic AAA bow limbs use parallel-transport frames or rotation-minimizing frames.
- **Severity:** D — produces visible cross-section misalignment as `curve` increases.

### 18. `generate_shortbow_mesh`  L4423-4458  ✦ **C+**
- Grip box, arrow nock box, 2 limbs from `_make_bow_limb` (inheriting the bug above), 2 tip nock spheres, 1 string (tapered cylinder), composite-style sinew toruses. ~400 v.
- **Bug:** string `_make_tapered_cylinder(0, str_bot, nock_z*0.15, …, str_top-str_bot, ...)` — string runs straight Y but nock z is `sin(0.8π)*curve ≈ 0.59*curve`. String z = `nock_z * 0.15` ≈ 0.09*curve, but the limb tips are at z = `sin(0.8π)*curve` (line 4411 in `_make_bow_limb`) — string connects nowhere near the nocks. Visible disconnection.
- **Severity:** C+ — string offset from limb tips.

### 19. `generate_longbow_mesh`  L4461-4503  ✦ **C+**
- Same structure as shortbow but with 70 cm limbs and elven extra grip rings. Same string-disconnect bug. ~500 v.

### 20. `generate_staff_magic_mesh`  L4506-4576  ✦ **B**
- "Gnarled" = 12-ring 8-segment lathe with sin-noise bumps on radius + sin-noise wobble on angle (actually cool); "crystal" = smooth shaft + 5 cones; "runic" = 6 binding rings + orb + 3 trim cones. Pommel sphere. ~400-700 v.
- The gnarled style is the closest-to-AAA function in the entire range. The wobble formula creates believable knurled wood.
- **Bug:** runic's tail loop assigns `of_` (with underscore) — that's just to avoid Python keyword `of`, fine. Pommel is at y=-0.02 below shaft base; OK.
- **AAA ref:** Diablo IV staves use ZBrush-sculpted highpoly + bake. This procedural noise is closer to actual Geo Nodes wobble.
- **Severity:** B — best of the lot, but the "crystal" and "runic" variants drop back to C.

### 21. `generate_wand_mesh`  L4579-4636  ✦ **C+**
- Twisted = 16-ring 6-segment lathe with angular twist (good); bone = taper + 3 sphere knobs; straight = single taper. Pommel + 3 grip rings + tip cone+ring or skull-end sphere. ~200-400 v.
- The twisted variant is decent. Bone variant just has 3 spheres on a stick — doesn't read as bone.
- **Severity:** C+.

### 22. `generate_throwing_knife_weapon_mesh`  L4639-4690  ✦ **C**
- Three styles: kunai (7-vert hand-rolled blade + ring + 2 grip cylinders); star (cylinder hub + 4 hand-rolled wedges); balanced (9-vert blade + grip cylinder + crossguard box + pommel sphere).
- **Bug:** kunai face list `[(1,5,6,3), (2,4,6,5), (1,3,6,5)]` — vertex 6 appears in three faces; vertex 5 appears in three faces. The handle is supposed to be a 4-sided pyramid attached to a 4-vert blade base, but the topology connects the wrong corners (`(1,3,6,5)` for instance — that's left-side of the blade base ⇒ pommel-bottom — leaves a triangular hole on right side). Will produce non-manifold T-junctions and visible lighting seams.
- **Severity:** C — broken topology on kunai blade-handle joint.

### 23. `generate_paired_daggers_mesh`  L4698-4754  ✦ **C+**
- Loop x ∈ {-0.06, 0.06}: handle + pommel + small guard + 6×4-vert blade strip + tip pyramid. Three curve styles (standard / curved / serrated via sin offset). ~400 v total.
- The serrated style adds `sin(t*π*6) * 0.003` to the *blade x_off* (the spine), not to the cutting edge — so the *whole blade wiggles*, not the edge. Wrong.
- **Severity:** C+ blockout.

### 24. `generate_twin_swords_mesh`  L4757-4825  ✦ **C+**
- Two mirrored sword bodies. Falcata gets clavate-then-pinch curve, gladius gets leaf shape. Same disconnected segments per cross-section. ~600 v.
- `trail_top` computed from a chained ternary that's hard to read but correct.
- **Severity:** C+ — two of the same B blockout.

### 25. `generate_dual_axes_mesh`  L4828-4877  ✦ **C+**
- Same hand-axe brick-head approach × 2.

### 26. `generate_dual_claws_mesh`  L4880-4970  ✦ **C+**
- Two styles: katar (H-frame grip + 1 wide blade × 2) — actually decent silhouette; tiger/hook (cylinder grip + knuckle plate + 2-3 claw blades × 2). Hook variant has curved claws, tiger has straight.
- **Bug:** the loop variable `mirror = 1.0 if side_x > 0 else -1.0` is **flipped** vs. paired_daggers (which uses `-1 if side_x < 0 else 1`); both reach the same answer but inconsistent. More importantly, `claw_z = 0.015 * (ci - (num_claws-1)/2.0)` puts claws side-by-side along z, which means they're parallel finger-blades on a wrist plate, not radiating "tiger claw" silhouette.
- **Severity:** C+.

### 27. `generate_brass_knuckles_mesh`  L4978-5016  ✦ **C**
- Frame box + grip box + 2 connectors + 4 finger torus rings + (optional) spikes/blade. ~150 v.
- Finger rings are flat XZ-plane toruses but knuckles wrap **around fingers**, so the rings should be vertical (XY-plane). They're laid flat on top of the frame — wrong orientation, looks like 4 small donuts on a bar.
- **Severity:** C — anatomically wrong; looks nothing like brass knuckles in silhouette.

### 28. `generate_cestus_mesh`  L5019-5065  ✦ **C**
- Tapered cylinder "glove body" + wrist torus + knuckle ridge box + (optional) studs/iron-plates + 3 wrap toruses. ~150-250 v.
- Looks like a labelled tube, not a hand-shaped fighting glove. No fingers, no thumb, no palm distinction.
- **Severity:** C stub.

### 29. `generate_bladed_gauntlet_mesh`  L5068-5171  ✦ **C+**
- Forearm tube + wrist ring + hand tube + knuckle box + 3 blade variants (single wrist blade / 4 finger blades / 3 curved claw tips). ~300-500 v.
- The hand section is a smooth tapered cylinder — no knuckles, no fingers, no palm vs. back distinction. Blades are correctly placed but emerge from a cylinder, not a hand.
- **Severity:** C+ blockout.

### 30. `generate_iron_fist_mesh`  L5174-5234  ✦ **C+**
- Forearm brace + wrist torus + (style-specific) hammer/spiked/standard fist + 2 strap toruses. ~200-300 v.
- "Spiked" variant has 6 cones radiating with `s_angle` but cone height is along Y-axis (always up) — they don't radiate outward. Same orientation bug.
- **Severity:** C+.

### 31. `generate_rapier_mesh`  L5242-5366  ✦ **B**
- Handle + faceted pommel sphere + 5 grip wraps + (style-specific) basket guard / ornate guard / standard guard + 14×4-vert diamond-cross-section blade + tip pyramid. ~600-1200 v depending on style.
- The basket hilt is the most ambitious: 6 curved bars (6-segment box-extrusions along an arc). They actually arc nicely from base to tip. Blade has proper diamond cross-section (4 verts per ring at cardinal directions). This is one of the better functions.
- **Bug:** basket-hilt bars don't connect to a top ring or to each other — they're 6 isolated curved sticks, not a real basket.
- **Severity:** B greybox.

### 32. `generate_estoc_mesh`  L5369-5440  ✦ **C**
- Handle + pommel + 4 grip rings + simple cross guard + 10×3-vert triangular-cross-section blade + tip + ricasso reinforcement box. ~250-350 v.
- The "ricasso reinforcement" is a separate box overlapping the blade base — z-fights with the blade. Triangular cross-section is correct topology.
- **Severity:** C — looks like a triangular tent pole with a pommel.

### 33. `generate_javelin_mesh`  L5448-5529  ✦ **C**
- 1.2 m shaft + 3 grip rings + 1 stabilizer fin (single beveled box) + (style) barbed head with 2 single-tri "barb fins" / fire wrap toruses / standard cone head. ~200-300 v.
- The "fin" at the rear is one box on x=0 — no actual fletching. Barbs are 6-vert hand-rolled triangular paddles with z-thickness — at least volumetric, but only 2 (one each side).
- **Severity:** C.

### 34. `generate_throwing_axe_mesh`  L5532-5593  ✦ **C**
- Same skewed-cube head approach as hand_axe. Three styles. Francisca arc is 4-vert ribbon along an angular arc (similar to battle_axe crescent). ~150-250 v.
- **Severity:** C — same brick-head problem.

### 35. `generate_shuriken_mesh`  L5596-5657  ✦ **C+**
- 12-segment central disc (cylinder) + (circular) 24-vert serrated ring / (4 or 6 point) wedge blades each as 6-vert paddle.
- Circular variant is decent. Point variants have flat wedges with no cutting edge taper.
- **Bug:** point wedges face all up at +Y, but a real shuriken is flat in XZ-plane. The wedges DO use ±thick along Y so it's a flat star — that's actually correct since `thick=0.003`. OK.
- **Severity:** C+.

### 36. `generate_bola_mesh`  L5660-5710  ✦ **C**
- 3 spheres at 120° offset connected to a central knot via 6 cylinder/torus rope segments. Spiked variant adds 4 cones per ball.
- **Bug:** rope segments are placed at evenly-spaced linear positions `(wx*t, 0, wz*t)` for t in 0..1 — they're literal small cylinders/toruses **floating along an empty line**, not connected end-to-end. Each is a separate primitive at a discrete point. There's no continuous rope, just dotted-line stones.
- **Severity:** C — bola is "3 stones with breadcrumb trails to center".

### 37. `generate_orb_focus_mesh`  L5718-5791  ✦ **C+**
- Cradle taper + 4 prong "extrusions" + orb sphere + (style) inner crystal sphere / swirl bands / void tendrils. ~250-450 v.
- The 4 prong extrusions actually use a curve (`r_off = 0.015 + sin(t*π)*0.01`) — gives bowed cradle prongs. Decent.
- **Bug:** prongs use 4 verts per ring (a square cross-section) but the cross-section is fixed to world axes — at the prong tip the cross-section doesn't follow the prong's curve direction. Also the prong "y direction" is set by `vx = cos(p_angle)*r_off` — so the prong extends radially outward, not upward. Examination: each prong's verts are at `(vx ± 0.003, y, vz)` and `(vx, y, vz ± 0.003)` — that's a + sign cross, **4 verts at +x, -x, +z, -z** — not a closed quad ring; this leaves the prong as 4 collinear lines, not a tube. Topology is broken.
- **Severity:** C+ but with prong topology bug.

### 38. `generate_skull_fetish_mesh`  L5794-5886  ✦ **C+**
- Handle + sinew toruses + per-style skull (beast = box + snout + 2 horn cones + 2 eye spheres; demon = sphere + 2 curved horns (6-segment box-extrusion + tip pyramid) + jaw box; human = sphere + jaw box + 2 eye spheres). + 2 dangling trinket cylinders.
- "Eye sockets" are spheres protruding **outward** at z=+0.025, not Boolean-cut indentations. They look like eyeballs popping out.
- Demon horns are 4-vert ring extrusions with hand-rolled tip pyramid — same world-axis cross-section bug.
- **Severity:** C+ blockout.

### 39. `generate_holy_symbol_mesh`  L5889-5967  ✦ **C+**
- Three styles: chalice (lathe cup + ring + base), reliquary (handle + box + cross + 4 corner spheres + chain loop), pendant (5 chain links + disc + cross + 8 sun-ray boxes). ~150-400 v.
- The chalice lathe profile produces a real bowl — better than most. Pendant has decent radial sun-rays.
- **Bug:** sun-rays are placed at `(rx, 0.122 + sin(r_angle)*0.025, 0)` but oriented as Y-up axis-aligned bevel boxes; they don't rotate to point outward from center. Reads as 8 little tablets stuck on a clock face, not radiating rays.
- **Severity:** C+.

### 40. `generate_totem_mesh`  L5970-6051  ✦ **C+**
- Shaft (per style) + carved face (box + 2 sphere eyes + 2 feather boxes) / skull top (sphere + 4 tooth cones) / rune stone (sphere). + 3 hanging charms (3 cylinders + 3 sphere beads).
- Carved face = box with 2 spheres protruding for eyes (same outward bug). Feathers = thin boxes.
- **Severity:** C+ — recognizable as a totem stick from 5 m.

### 41. `generate_gargoyle_mesh`  L6059-6150  ✦ **C**
- Body sphere + head sphere + snout taper + 2 horn tapers + 2 eye spheres + 2 leg tapers + 2 foot boxes + 2 arm tapers + (winged) 2 single-quad triangular wings + (screaming) 1 mouth cylinder + base box + 6-segment helical tail. ~400-600 v.
- **Bug:** wings are single quads (4 verts, 1 face) — paper-thin, will be invisible from one side and missing back-face. Tail uses Y-axis cylinders along a helix → same disconnected-segments bug as whip/claw. Eye spheres protrude outward.
- **AAA ref:** Notre-Dame gargoyle scans = 50 k+ tris with eroded stone material. Sekiro / Bloodborne stone gargoyles use ZBrush-sculpted highpoly + bake.
- **Severity:** C stub.

### 42. `generate_fountain_mesh`  L6153-6224  ✦ **B−**
- Per tier: lathed bowl (9-pt profile, 16 segments) + (upper tiers) tapered cylinder pedestal. + central spout (5-pt lathe) + base platform (3-pt lathe).
- The lathe approach is correct AAA technique. Profiles are reasonably bowl-shaped.
- **Bug:** the basin profile starts at `(r*0.15, y_offset)` and ends at `(r*0.5, y_offset+0.1)` — the close_bottom isn't passed (default False), but then it loops back inward to `(r*0.5, y_offset+0.1)` from `(r*0.9, y_offset+0.12)`. The profile **is not monotonic** — it crosses itself. Will produce self-intersecting lathe with reversed normals on the inner-rim quads. Also `_make_lathe(basin_profile, segments=16)` is called without `close_top` or `close_bottom` — leaves an open hole at top *and* bottom of the bowl. Water would fall through.
- **Severity:** B− — workable silhouette with topology issues.

### 43. `generate_statue_mesh`  L6227-6317  ✦ **C**
- Pedestal box + torso taper + head sphere + 2 leg tapers + (per pose) arms = 2 tapers (standing/praying) or 1 raised arm + 1 sword cylinder + 1 shield arm + 1 shield disc cylinder (warrior). ~350-450 v.
- This is a **stick figure** — sphere head + cylinder torso + cylinder limbs. Megascans and Daz-style statues require sculpted humanoid topology with proportions following the Vitruvian canon. The legs are placed at `(±0.06*s, ped_h - leg_h*0.3, 0)` extending UP from y = ped_h - leg_h*0.3 = 0.18 to 0.18 + 0.4 = 0.58 — but the torso starts at `ped_h = 0.3` and is 0.5 tall, so legs INTERSECT the torso.
- **Severity:** C stub.

### 44. `generate_bridge_mesh`  L6320-6454  ✦ **B / B−**
- **stone_arch:** deck quads with slight crown + 3 arch ribs (curved box-extrusions) + 2 wall boxes. Reasonable greybox. **B**.
- **rope:** plank boxes with sag + rope cylinders as **vertical posts** (not horizontal handrails). The "Vertical rope post" comment is wrong — rope handrails should run along Z; here they're vertical Y-cylinders at each plank. **B−**.
- **drawbridge:** beveled-box deck + plank-line strips + 2 chain attachment toruses + 2 hinge cylinders. Hinges at z = -span/2 are correct, but no chains actually drawn (just torus mounting points). **B−**.
- **AAA ref:** UE5 sample bridges = swept spline meshes with bake-ready details, animated drawbridge.
- **Severity:** B / B−.

### 45. `generate_gate_mesh`  L6457-6587  ✦ **B−**
- **portcullis:** 9 vertical bars + 7 "horizontal" bars + 9 downward spikes. **The horizontal-bar rotation is broken** (line 6492: `h_verts = [(v[1] - y + (-width / 2), y, v[2]) for v in hv]`). The cylinder is built along Y starting at `(-width/2, y, 0)` with height=width — its vertices have y in [y, y+width] and x = -width/2 + cos(θ)*r, z = sin(θ)*r. The "rotate" maps new_x = (orig_y - y - width/2). For ring 0 (y=y): new_x = -width/2; for ring 1 (y=y+width): new_x = +width/2 — so X spans correctly. But new_y is fixed to `y` for **all 12 vertices**, collapsing the cylinder to a flat ring. Z still has cos*r values from the *original* x and sin*r from z. Result: the bar becomes a **flat rectangle** in the XZ plane with zero Y extent. **NEW BUG**.
- **wooden_double:** 2 door beveled-boxes + (5 plank lines × 2 sides via two different x formulas — see comment, only second is used) + 3 iron bands (each a single box spanning `width/2` half-extent → spans BOTH doors as one continuous band, which contradicts the double-door concept) + 2 ring handle toruses + 4 hinge cylinders.
- **iron_grid:** same horizontal-bar rotation bug as portcullis + 2 frame boxes.
- **Severity:** B− — recognizable but with a horizontal-bar collapse bug affecting 2 of 3 styles.

### 46. `generate_staircase_mesh`  L6590-6695  ✦ **B / B−**
- **straight:** N step boxes (beveled) + 2 stringer boxes. Stringers are full bounding boxes spanning total_rise/2 × total_run/2 — they're solid blocks, not the diagonal stringer beams of a real staircase. **B−**.
- **spiral:** central cylinder pillar + N pie-slice pillars (top fan + bottom fan + risers + outer rim). Hand-rolled topology. The face winding looks intentional but `step_faces_local.append((top_center, bot_center, bot_center+1, 1))` has a **mixed CW/CCW issue** — vertex order goes top_center=0, bot_center=n_arc+2, bot_center+1, 1 — that's diagonal across the front-riser quad, will produce a non-planar quad. **B greybox**.
- **Severity:** B / B−.

### 47. `generate_fence_mesh`  L6703-6877  ✦ **B−**
- **wooden_picket:** posts (beveled box + cone top) + 2 horizontal rails (single boxes) + per-section pickets (3 boxes + 3 cones each).
- **iron_wrought:** posts + finial spheres + 2 horizontal rails (rotation bug, line 6788) + per-section vertical bars + spear tips.
- **stone_low_wall:** 1 main wall box + cap stones + horizontal mortar-line boxes.
- **bone_fence:** posts (3 sections each: tapered base + sphere joint + tapered top) + 2 horizontal rails. The bone rail rotation at lines 6859-6873 attempts the same horizontal-flatten transform — with the same failure (collapses Y to rail_y). **NEW BUG**.
- **Severity:** B− — wooden picket is workable; iron_wrought and bone fence rails are flattened.

### 48. `generate_barricade_mesh`  L6880-6995  ✦ **C**
- **wooden_hasty:** N planks (boxes) + 2 cross-brace boxes + 2 angled support strut boxes. Cross-braces span full width.
- **wagon_overturned:** 1 wagon body box + 2 wheels (toruses) + spokes (cylinders placed on a half-circle around hub center — but the spokes are world-axis Y-cylinders, not radiating from hub) + 3 debris planks.
- **sandbag:** 3 rows of beveled-box bags with row offset.
- **Bug:** wagon spoke positions `(x_side, body_h+0.25 + sin(angle)*0.15, cos(angle)*0.15)` place them on a circle, but they're Y-axis cylinders length 0.01 — they're tiny stubs floating at the wheel rim, not radial spokes.
- **Severity:** C — sandbag and wooden_hasty are passable; wagon spokes broken.

### 49. `generate_railing_mesh`  L6998-7119  ✦ **B−**
- **iron_ornate:** 2 end-posts + 2 finial spheres + 1 top rail (rotation bug, line 7031) + N balusters + N small scroll toruses.
- **wooden_simple:** N posts (beveled boxes) + top rail box + mid rail box. Clean. **B**.
- **stone_balustrade:** base rail + top rail + N lathed balusters (8-pt profile). Lathed balusters are correct AAA technique — by far the most refined here.
- **Severity:** B− — iron_ornate top rail is collapsed-flat by the rotation bug; balustrade is decent.

---

## Cross-cutting findings

### CF-1 — "Rotate to horizontal" antipattern (4 sites)
Lines 6492, 6575, 6788, 6865-6873, 7031 all attempt to convert a Y-axis cylinder into a horizontal X-axis bar via:
```python
h_verts = [(v[1] - y + (-width / 2), y, v[2]) for v in hv]
```
This **collapses all verts to a single y-plane** (since new_y = `y` constant), producing a flat rectangle, not a horizontal cylinder. The original Z values are kept (radial), so it looks like a flat ribbon viewed edge-on.
**Affects:** gate (portcullis horizontal bars, iron_grid horizontal bars), fence (iron_wrought rails, bone fence rails), railing (iron_ornate top rail).
**Fix:** swap (x,y,z) properly: `(v[1] - y + (-width/2), v[0]+y - cx, v[2])` won't work either — the right approach is to build a cylinder primitive that takes an axis vector, or apply a true 90° rotation matrix `(x',y',z') = (z, x, y)` etc.

### CF-2 — World-axis cross-section antipattern (every "extruded" weapon)
Sword/blade/horn/prong/whip/claw/finger functions all build cross-sections with verts at `(x ± w, y, z ± d)` — the cross-section stays fixed to the world XYZ axes. When the spine curve has any z- or x-displacement, the cross-section does NOT rotate to follow the tangent. AAA workflow uses parallel-transport frames or RMF (rotation-minimizing frames). Affected: `_make_bow_limb`, `generate_scythe_mesh`, `generate_curved_sword_mesh`, `generate_glaive_mesh`, `generate_halberd_mesh` blade, `generate_dual_claws_mesh`, `generate_skull_fetish_mesh` horns, `generate_orb_focus_mesh` prongs, `generate_naginata/guandao/curved` glaive, `generate_estoc_mesh` triangular cross-section.

### CF-3 — Disconnected-segment antipattern
Cylinders strung along a curve with axis-aligned individual primitives — produces visible gaps at every joint. Affects: `whip`, `claw`, `crossbow` arms, `gargoyle` tail, `bola` rope, `flail` chain, `curved sword` (less so since the tip is welded). AAA solution: single skinned mesh with a continuous control curve.

### CF-4 — Spike/horn/cone orientation
Spikes added with `_make_cone` always point +Y. They never radiate outward from the host sphere/box surface. Affects: `flail` ball-spikes, `mace` morningstar, `club` spiked, `iron_fist` spiked, `bola` spiked, `crossbow` (no), `bridge` (n/a). AAA solution: rotate cone by `look_at(surface_point - center)` quaternion, or hand-build cone vertices in the desired direction.

### CF-5 — "Eye socket / mouth / detail" = additive sphere
Eyes on `gargoyle`, `skull_fetish` (human/beast), `totem` (wooden) are spheres protruding outward from the host shape — they look like eyeballs popping out, not concave sockets. AAA workflow is Boolean subtraction or sculpted indentation, then bake to normal map.

### CF-6 — No UV authoring
Every function ends with `_make_result(name, verts, faces, ...)` — UVs are computed downstream by default planar/box projection. No function in the range sets up proper unwrapping (cylindrical for handles, flat for blade, sphere for pommel). At AAA bar, weapons need authored seams to avoid texture stretching.

### CF-7 — No normals smoothing groups
`MeshSpec` doesn't carry smoothing-group info from these functions. Cylinders with 4-6 segments will look facetted; spheres with 3-4 rings will look like soccer balls. AAA bar requires explicit smoothing-group / hard-edge tagging.

### CF-8 — Single-quad / single-triangle "details"
Wings on `gargoyle` (1 quad), flanges on `mace` (1 triangle each), barb fins on `javelin` (1 triangle base + extruded), string on `crossbow` (1 triangle). All are paper-thin and will fail back-face culling from at least one viewing angle.

### CF-9 — Style variants are constant-tweaks
Most functions claim 3 styles (e.g. greatsword: standard/flamberge/executioner). Inspection shows the variants typically differ by 4-8 numeric constants (length, width, segment count) and one branch (e.g. wave-extrusion vs straight). They do not represent fundamentally different real-world weapon geometries. A flamberge has *spiraled fullers* and a *wavy double-edge*; the procedural just adds `sin(t*π*4)*0.008` to width.

### CF-10 — `head_count == 1` div-by-zero hazard in `claw`
Line 3671: ternary `if finger_count > 1 else math.pi*0.5` reads naturally but Python ternary evaluates the `if` arm first only when condition is True — when False (`finger_count==1`) it goes to else. Mitigated by `max(3, min(5, finger_count))` clamp, but if any future caller bypasses, **crash on division by zero**.

---

## NEW BUGS

### BUG-250 — Horizontal-bar rotation collapses cylinder to flat plane
**File:** `procedural_meshes.py`
**Sites:** L6492 (gate portcullis), L6575 (gate iron_grid), L6788 (fence iron_wrought), L6865-6873 (fence bone), L7031 (railing iron_ornate)
**Severity:** HIGH
**Symptom:** Top/horizontal bars render as flat 2D ribbons instead of round cylinders. From any non-edge-on angle, the bars look like sheet-metal strips with zero thickness in Y.
**Root cause:** `[(v[1] - y + (-width/2), y, v[2]) for v in hv]` — `y` (the constant) overrides all original Y values; cylinder vertices from `_make_cylinder` have y∈{cy_bottom, cy_bottom+height} = {y, y+width} — these collapse to a single plane.
**Fix:** Generate horizontal bars by constructing the cylinder along the X axis directly (write a `_make_cylinder_x` helper) or apply a real rotation matrix `(x,y,z) → (y_local, x_local, z_local)` plus translation back to world.

### BUG-251 — Whip/claw/gargoyle-tail/crossbow-arm primitives leave visible joint gaps
**File:** `procedural_meshes.py`
**Sites:** L3409-3421 (crossbow arms), L3616-3636 (whip segments), L3678-3693 (claw fingers), L6139-6147 (gargoyle tail), L5691-5700 (bola rope)
**Severity:** HIGH
**Symptom:** What should look like continuous flexible parts render as a string of sausages with visible gaps between every cylinder.
**Root cause:** Each segment is a Y-axis cylinder placed at a curve sample point; segment i's top doesn't align with segment i+1's bottom because the curve's x/z displacement changes between samples but the primitives stay axis-aligned.
**Fix:** Skin a single mesh: sample N points along the curve, compute tangent + normal frame at each, extrude a circular profile, build quad strips between consecutive frames.

### BUG-252 — Scythe blade open-seam (`for j in range(2)` should close all sides)
**File:** `procedural_meshes.py:3493`
**Severity:** MEDIUM
**Symptom:** Light leaks through the back of the scythe blade; non-manifold mesh fails Bloom/SSR/SSAO.
**Root cause:** `for j in range(2)` connects only 2 of the 3 quads needed for a triangular cross-section.
**Fix:** `for j in range(3): blade_faces.append((b+j, b+(j+1)%3, b+3+(j+1)%3, b+3+j))` (close the modular loop).

### BUG-253 — Bow string disconnected from limb tips
**File:** `procedural_meshes.py:4448, 4490`
**Severity:** MEDIUM
**Symptom:** String runs at z=`nock_z*0.15` but limb tips are at z=`sin(0.8π)*curve` ≈ `nock_z` — string visibly floats away from the bow tips.
**Fix:** String z should equal the actual nock z (`nock_z`), not 0.15× it. Or move the nocks to z=0.15*nock_z to match.

### BUG-254 — Crossbow arm cylinder sequence is non-continuous open tubes
**File:** `procedural_meshes.py:3419`
**Severity:** HIGH
**Symptom:** "Bow arms" appear as a string of disconnected open-ended tubes; no recognizable bow lath.
**Root cause:** Each `_make_cylinder` call uses `cap_top=False, cap_bottom=False` AND each segment is at a different (x, y, z) point along a curve while the cylinder primitive extends along Y. Tubes don't connect, are open-ended, and don't form a continuous limb.
**Fix:** Replace 7 cylinders per side with a single swept tube along the limb curve (see BUG-251 fix).

### BUG-255 — Brass knuckles finger-rings flat instead of vertical
**File:** `procedural_meshes.py:5001`
**Severity:** MEDIUM
**Symptom:** What should be 4 finger-holes through the punching frame appear as 4 flat donuts lying on top of the bar — anatomically meaningless.
**Root cause:** `_make_torus_ring` lays toruses in the XZ plane (Y is the up-axis through the donut hole). For finger holes, the donut hole should be along Z (so fingers thread through). Need an XY-plane torus.
**Fix:** Add `_make_torus_ring_xy` helper that swaps the in-tube-axis (currently Y) with Z, or apply a 90° rotation to the existing torus output.

### BUG-256 — Rapier basket-hilt bars don't connect to a top ring
**File:** `procedural_meshes.py:5267-5286`
**Severity:** LOW
**Symptom:** "Basket hilt" reads as 6 isolated curved sticks around the grip, not a closed wire-cage basket.
**Fix:** Add a top ring at the apex of all 6 bars (where their arc tops meet at z≈0, y=guard_y+0.03).

### BUG-257 — Wagon barricade spokes are tiny Y-stubs at wheel rim
**File:** `procedural_meshes.py:6953-6960`
**Severity:** MEDIUM
**Symptom:** Wagon wheels appear as bare toruses with 6 tiny dots on the rim where spokes should be.
**Root cause:** `_make_cylinder(x_side, body_h+0.25 + sin(angle)*0.15, cos(angle)*0.15, 0.008, 0.01, segments=4)` — radius 0.008, **height 0.01** — these are tiny disc-stubs at the rim, not radial spokes spanning hub-to-rim.
**Fix:** Generate each spoke as a long, properly-oriented cylinder from hub center (x_side, body_h+0.25, 0) to rim point (x_side+sin(angle)*0.2, body_h+0.25+cos(angle)*0.2, 0).

### BUG-258 — Fountain basin lathe profile is non-monotonic; produces self-intersecting bowl
**File:** `procedural_meshes.py:6175-6185`
**Severity:** MEDIUM
**Symptom:** Basin renders with reversed-normal inner-rim quads; AO/SSR artifacts on the lip.
**Root cause:** Profile y-values: 0, 0.02, 0.03, 0.08, 0.1, 0.15, 0.15, 0.12, 0.1 — y goes up then back DOWN (0.15→0.12→0.10), and x goes 0.15→0.2→0.8→1.0→1.05→1.05→0.95→0.9→0.5 — both the outer rim AND the inner cup rim are traced with the lathe; lathe assumes monotonic y. Result: the bowl interior is double-walled with reversed normals.
**Fix:** Either split the profile into outer-wall-only + close_top quad + inner-wall-only, or use a proper extrude-tube primitive.

### BUG-259 — Halberd langets at angles 0,π collide on x-axis (both at z=0)
**File:** `procedural_meshes.py:6303-6306`
**Severity:** LOW
**Symptom:** "4 langets around pole" advertised by the comment, only 2 visible (other 2 z-fight at z=0).
**Root cause:** `for angle in [0, math.pi]` iterates only 2 values; sin(0)=sin(π)=0, so both langets at z=0; cos differs, so they're at +x and -x — that's correct for 2 langets, but a halberd should have 4 (one per pole face).
**Fix:** Loop `[0, π/2, π, 3π/2]` for 4 langets.

### BUG-260 — Throwing-knife "kunai" face list creates non-manifold T-junction at handle joint
**File:** `procedural_meshes.py:4651`
**Severity:** MEDIUM
**Symptom:** Visible lighting seam at handle/blade joint; mesh fails manifold check.
**Root cause:** Face list `[(0,1,2), (0,4,3), (0,2,4), (0,3,1), (1,5,6,3), (2,4,6,5), (1,3,6,5)]` — vertex 6 used in 3 faces (edges to 5 twice, to 3 once), vertex 5 used in 3 faces — but vertex 4 connects to 6 only via face `(2,4,6,5)`, leaving the right-side blade-to-handle edge (4-2) without a triangle on the bottom. T-junction.
**Fix:** Add face `(2, 4, 6)` or restructure to use a clean tube + paddle topology.

### BUG-261 — Iron-fist "spiked" radial cones all point +Y instead of radiating
**File:** `procedural_meshes.py:5209`
**Severity:** MEDIUM
**Symptom:** Spiked iron-fist looks like a sphere with a row of stalagmites on top, not a radiating mace-head.
**Root cause:** `_make_cone(sx, fist_base_y+0.035 + abs(sin(s_angle))*0.01, sz, ...)` — cone always extends +Y from base point.
**Fix:** Apply rotation matrix to align cone axis with `(sx-cx, sy-cy, sz-cz)` direction.

### BUG-262 — Pendant sun-rays are Y-up boxes, don't radiate
**File:** `procedural_meshes.py:5956`
**Severity:** LOW
**Symptom:** "Sun rays" appear as 8 small upright tablets arranged on a circle, not radiating outward.
**Fix:** Rotate each ray box so its long axis aligns with the radial direction `(rx, ry-0.122, 0)`.

### BUG-263 — Orb-focus prong "tube" is 4 disconnected vertices per ring (broken topology)
**File:** `procedural_meshes.py:5745-5746`
**Severity:** MEDIUM
**Symptom:** Prongs render as 4-strand "fork tines" rather than solid tubes.
**Root cause:** Each ring appends 4 verts in a `+` cross pattern — `(vx-0.003, y, vz), (vx+0.003, y, vz), (vx, y, vz+0.003), (vx, y, vz-0.003)` — these 4 verts don't form a closed quad; they're the apex of a "+" sign. The face loop `(b+j, b+j2, b+4+j2, b+4+j)` for j∈[0..3] connects them as quads between rings, producing 4 thin strip tubes that don't seal.
**Fix:** Use 4 verts as a proper square ring (`(vx±0.003, y, vz±0.003)`), or use 6+ vert ring with `cos(θ), sin(θ)` placement.

### BUG-264 — Wooden-double gate iron bands span both doors as single boxes
**File:** `procedural_meshes.py:6537`
**Severity:** LOW
**Symptom:** Iron reinforcement bands cross the gap between left and right doors as a single rigid strip — the gate cannot open without the bands tearing.
**Fix:** Replicate per door: `for door_x_center in [-width/4, width/4]: _make_box(door_x_center, band_y, ..., width/4-0.01, 0.015, 0.003)`.

### BUG-265 — Demon skull horn vertex index out of scope
**File:** `procedural_meshes.py:5850`
**Severity:** LOW (latent — `hx` used after loop but always defined when reached)
**Note:** `hvl.append((hx_sign * 0.06, skull_y + 0.14, 0))` — `hx_sign` is the loop var, `0.06` is hardcoded. The previous loop's `hx` is shadowed but not used here. OK on closer read but worth noting that `for i in range(horn_segs+1)` then `for j in range(4)` reuses tip-attach pattern.

### BUG-266 — Spiral staircase front-riser quad is non-planar
**File:** `procedural_meshes.py:6682`
**Severity:** LOW
**Symptom:** Front-facing riser surface flickers under shading because the 4 vertices `(top_center, bot_center, bot_center+1, 1)` don't lie on a single plane (top_center=0 is at the central pillar y+step_h, vertex 1 is at outer_r y+step_h, bot_center+1 is at outer_r y, bot_center=n_arc+2 is at central pillar y).
**Fix:** Triangulate explicitly: `(top_center, bot_center, 1)` + `(bot_center, bot_center+1, 1)`.

---

## Context7 / docs references used

- **Blender bmesh** — for swept-along-curve and rotation-minimizing-frame patterns; relevant to BUG-251, CF-2.
- **numpy mesh generation (matplotlib trisurf, scipy.spatial.Delaunay)** — for proper triangulation of the lathed bowl in `fountain` (BUG-258); a real basin would tessellate the rim region with constrained Delaunay rather than monotonic-profile lathe.
- **scipy.spatial** — `Rotation` class would solve BUG-250, BUG-261, BUG-262 by providing `Rotation.from_rotvec` and applying to vertex arrays.
- **SpeedTree** — reference for branch/limb generation: every limb is a single splined tube with cross-sections oriented to the tangent (this is what `_make_bow_limb` *should* do).
- **Quixel Megascans weapons (free pack)** — typical weapon mesh has 5-15 k tris with 4 k PBR. None of these procedural functions would survive Megascans QC.
- **UE5 PCG Framework** — uses `Spline` + `Sample Points` + `Mesh Spawner` patterns. The "primitives glued at sample points" pattern in this file is conceptually similar but lacks the smoothing/welding step PCG performs at the end.

---

## Concluding judgement

**Out of 49 functions, zero hit AAA.** The best (`generate_staff_magic_mesh` gnarled, `generate_railing_mesh` stone_balustrade, `generate_rapier_mesh`, `generate_tome_mesh`, `generate_fountain_mesh` if BUG-258 fixed) reach **B greybox** — useful as silhouette stand-ins from 5+ m camera distance. The middle 28 are **C blockouts** — they would be replaced wholesale before ship. The bottom 12 are **C− to D** — broken topology, disconnected segments, anatomically wrong, or non-manifold.

The dominant antipatterns (CF-1 through CF-9) are systemic, not isolated bugs: the entire approach of "axis-aligned primitives at sampled curve points" cannot produce AAA results without a swept-tube-along-curve helper plus rotation-minimizing frames. Fixing the 16 enumerated bugs above would lift the **B−/C+** functions to **B**, but reaching A would require a complete refactor to use:
1. Spline-swept tubes with parallel-transport frames.
2. Boolean subtraction for indentations (eye sockets, mortar joints, fullers).
3. Proper UV authoring per submesh.
4. Smoothing-group / hard-edge tagging.
5. Vertex welding at joins between submeshes.
6. Bevelled corner topology at every primitive boundary.

Without these, the file is *programmer art* — useful for in-engine placeholder during prototyping, not shippable for a game that "demands AAA quality".
