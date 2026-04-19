# P5 — `procedural_meshes.py` Lines 14194–17802 Function-by-Function Grades

## Date: 2026-04-16
## Auditor: Opus 4.7 ultrathink (max reasoning) — strict AAA reference grading
## Scope: 49 generators from `generate_spell_scroll_mesh` (line 14194) through `generate_lookout_post_mesh` (line 17802)
## Reference benchmarks
- **Hand props (scrolls/arrows/keys/coins/food):** Megascans Imperfections + Quixel asset library, Witcher 3 / Skyrim AE / BG3 hero‑grade hand props (8–25K tris, baked normal+AO+roughness from a 1–4M sculpt, hand‑weighted UVs).
- **Furniture (bed/wardrobe/cabinet/curtain/mirror/bathtub/fireplace):** Skyrim AE & RDR2 interior dressing kits (2–15K tris, modular pieces with kitbash bevels, planar UVs for wood grain, cloth via APEX/Marvelous bake).
- **Cloth (curtain/tent fabric):** Marvelous Designer simulated drape baked to LP, spec demands ≥48 spans across width with anisotropic weft/warp, pinned top, gravity‑sagged hem.
- **Outdoor structures (palisade/watchtower/battlement/moat/windmill/dock/bridges/tent):** UE5 PCG building blocks, Ghost of Tsushima village kit, Witcher 3 wooden towers (modular logs with end‑cap rings, decals for cracks/moss, vertex paint masks for snow/blood, RVT terrain blend).
- **Camp props (hitching post/trough/barricade/lookout):** RDR2 camp kit, Mount & Blade Bannerlord siege kit.
- **Geometric standard:** Quad‑dominant flow, no n‑gons on visible silhouette, dihedral ≥35° = hard edge, watertight where appropriate (props/furniture), open one‑sided where intended (curtains, tent fabric, sails) — and BACKFACE problems flagged when single‑sided.

## Summary

This range is the **hand‑prop and outdoor‑fortification belt** of the procedural mesh library. Net call: **C+/B-** as a band, with a long tail down to **D** for several outright‑broken pieces. It is closer to a Roblox Studio kitbash than to a Skyrim AE kit, much less BG3.

Three classes of failure dominate:

1. **Rotation/orientation bugs from "swap Y and Z" hacks.** Whenever the author wanted a horizontal cylinder (rolled scroll, hay bale, wine‑rack bottle hole, dock post lay‑down), they wrote `[(v[0], v[2], v[1]) for v in cv]` instead of building a real rotation matrix. Many cases re‑orient correctly; many do not. **BUG-401 (HIGH)** — `wine_rack(style="barrel")` line 15329 has `(v[0], v[2] + cy, v[1] - cy + cy)` which is algebraic nonsense (the Y term cancels itself), so the bottle holes collapse to a flat disc instead of cylindrical wells. **BUG-402 (HIGH)** — `mirror(style="hand")` at lines 15092‑15101 builds a handle, throws it away with `_hv_rot` prefix (unused — flagged by the dummy underscore), then builds a **second** handle below; the dead code path is shipped. **BUG-403 (MED)** — `hay_bale(style="round")` line 15217 re‑centers along X by subtracting `length / 2` after the swap, but the swap puts the cylinder length along Y, not X — the bale ends up axial mis‑aligned with the strap rings (which use the original cylinder's local X).

2. **No real cloth.** `curtain` builds a 17×13 = 221‑vert plane with a single sine wave amplitude 0.03 m (≈3 cm). Marvelous Designer drape is 3‑frequency (warp/weft + gravity + pinching), 60×80 spans minimum, 2‑sided, pinned at the rod with a gather pinch. Tent walls are flat boxes. **BUG-404 (MED)** — `curtain` ships single‑sided geometry but never sets `auto_uv=False` or any double‑side hint, so backface culling will look wrong from one side. **BUG-405 (HIGH)** — `curtain` `gathered` mode pinches X but doesn't preserve arc length, so the cloth is *stretched* by `(1‑gather*0.5)` at the bottom rather than crinkled — it's a trapezoid, not a gather.

3. **Outdoor structures are blockout‑grade.** Palisade is straight cylinder + cone — no log end‑caps, no crossbeam lashings, no moss/wear on alternating logs, no top‑rail. Watchtower wooden style is 4 cylinders + 3 boxes + ladder rungs — no roof, no joinery, no parapet wall infill, no thatch shingling. Stone watchtower has no arrow slits, no door, no joint lines. Dock has no rope wrap on bollards, no buoys, no fendering, no wave‑splash decals. Windmill blades are 3D box arms + 5 mm thick boxes for sails — no sailcloth panels, no shutters, no wind cap rotation rig.

4. **Repeated copy‑paste arrow sub‑mesh** — `fire/ice/poison/explosive/silver/barbed_arrow` all use the same 4‑vert quad fletching ribbon (`for fi in range(3)` block), which is **non‑planar** in many seeds (the 4 corner verts are not co‑planar by construction), and Blender's tessellator will arbitrarily split the n‑gon. AAA arrow fletching is 6–10 spans of paired triangles per fletch with a real curve. **BUG-406 (LOW)** — fletching quads can self‑intersect when `sr * 4` overlaps adjacent fletch's `sr * 3` term (3 fletches at 120° spacing with width up to 4*sr — touching neighbours).

5. **Catacomb of `category="furniture"` mis‑labels.** `hay_bale` returns category `"furniture"` (it's vegetation/farming), `wine_rack` is `"furniture"` (correct), but `bathtub`/`fireplace` should be `"interior"` or `"appliance"`, not `"furniture"` — registry buckets won't separate them. `tent`/`hitching_post`/`feeding_trough`/`barricade_outdoor`/`lookout_post` all `category="camp"` is reasonable but `windmill`/`dock`/`bridge_stone`/`rope_bridge` are `"infrastructure"`, while `palisade`/`watchtower`/`battlement`/`moat_edge` are `"fortification"` — close enough.

6. **No call to `_enhance_mesh_detail` anywhere except `bed`.** `bed` calls it with `min_vertex_count=500`. Every other prop in this 49‑function range skips the detail enhancement pass entirely. So the 49 functions ship **at native blockout density** with no edge‑loop refinement, no support‑loop creasing for smooth shading, no chamfer‑subdivide to soften silhouette under SSAO. This is a global gap, not per‑function.

Strengths (rare):

- `coin_mesh` is correctly minimal — 4 cylinders for face/rim/embossed obverse/reverse, lathe‑topology, would bake to a believable normal map. **B+**.
- `gem_mesh` is the only function in range that builds true brilliant‑cut geometry (table + pavilion + culet, crown facets) from scratch; topology is correct, faces wind correctly, A‑grade for what it is. **A-**.
- `bridge_stone(arch)` actually builds an extruded arch underneath with proper cross‑section, crown camber on the deck, and railings — the only outdoor structure in range that goes past blockout. **B+**.
- `tent` "command" multi‑pole layout with ridge beam + double slope roof is correct topology for a Mongol/cavalry pavilion. **B-**.

Weaknesses worth naming globally:

- Every `_make_box` based prop is a 6‑face hex, not even chamfered (only `_make_beveled_box` chamfers; many call sites use plain `_make_box` instead). Look at `meat`/`fish`/`bread`/`cheese` — they ship with hard 90° silhouettes that will read as Lego under SSR/SSAO.
- Zero use of vertex color, vertex paint masks, second UV channel, or material slot assignment in the 49 functions. AAA props ship with at minimum a 2‑material assignment (e.g. body + metal) and vertex color for AO‑bake mask.
- Zero attention to scale realism: `gem_mesh` `r=0.012` (12 mm) is correct, but `coin r=0.016` (16 mm) is bigger than real currency at all three tiers (real silver dirham ≈ 24 mm, gold ducat ≈ 21 mm, copper farthing ≈ 22 mm). Sub‑inch coins won't read at gameplay distance.

NEW BUGS in this range start at **BUG-400** and go through **BUG-432** (33 new findings).

---

## `generate_spell_scroll_mesh` (line 14194) — Grade: C

**Claims:** Spell scroll with distinct seal motif per element (fire/ice/lightning/teleport/protection/identify).
**Produces:** ~150–250 verts depending on style. Topology = central cylinder lathe + 2 sphere knobs + per‑style seal cluster (cone+sphere / sphere+6 boxes / sphere+3 boxes / torus+sphere / box+sphere / sphere+sphere) + ribbon back‑plate (`_make_box`) + 2 ribbon tails.
**Params:** `style` only (no length/radius — fixed at 0.22 m).
**AAA ref:** Skyrim's spell tomes + Diablo 4 scroll inventory icons. AAA target: rolled parchment with Marvelous‑sim drape, separate seal disc with sub‑D crease, 8K tex with engraved sigil.
**Bug:** Cylinder is built along Y with `_make_cylinder(0,0,0,scroll_r,scroll_len,segments=10)` then swapped `(v[0], v[2], v[1])`, which puts length along Z. Sphere knobs at `z_end=±scroll_len*0.5` are placed at *original* Z, but then the `parts.append((sv,sf))` adds them **without** the same swap, so knobs sit at wrong axis. **BUG-407 (HIGH)** — knob spheres at lines 14211‑14213 are placed at `z=±scroll_len*0.5` but the cylinder was rotated so its length is now along Z; the knobs should be at `y=±scroll_len*0.5` after swap. Result: knobs float free of scroll ends.
**Severity:** HIGH (visible artifact — floating spheres).
**Upgrade to A:** Real lathe scroll with 32‑seg radius and Marvelous drape; sigil seal as separate disc with depth‑embossed runic text via boolean‑subtract; ribbon as 8‑span quad strip with catenary sag; per‑element particle attach point.

---

## `generate_rune_stone_mesh` (line 14279) — Grade: C-

**Claims:** Brand‑specific rune stone, distinct geometry per brand (10 brands: IRON/SAVAGE/SURGE/VENOM/DREAD/LEECH/GRACE/MEND/RUIN/VOID).
**Produces:** 80–250 verts. Each brand is a 3‑5 piece kitbash (sphere+box+box for IRON; deformed sphere+3 box bristles for SAVAGE; double cone+2 rings for SURGE; tapered cylinder+3 cones for VENOM; etc).
**Params:** `brand` only.
**AAA ref:** Elden Ring talisman icons, Path of Exile rare‑mod talismans, Diablo runes — typically 1–3 K tri sculpted stone with engraved glyph and emissive crack lighting.
**Bug:** SAVAGE deformation `v[1] * 20` and `v[0] * 15` create high‑frequency noise on a sphere with rings=5 — way undersampled, so the sin frequency aliases into chunks. **BUG-408 (LOW)** — VOID brand at line 14385 places inner sphere at the same center as outer (`y=base_r` for both), so they are perfectly concentric — should be slightly offset to read as orb‑in‑shell. RUIN style "obelisk" has `cv` boxes at `x=base_r * 0.35` only (single side) — visually asymmetric without intent.
**Severity:** MED.
**Upgrade to A:** One sculpt mesh per brand at 2K tri with brand glyph extruded ≥2 mm; vertex paint mask for emissive crack location; share 1 base stone, swap sigil decal.

---

## `generate_fire_arrow_mesh` (line 14411) — Grade: C-

**Claims:** Fire arrow with burning head and oil‑soaked wrapping.
**Produces:** ~100 verts. Cylinder shaft (segs=6, ±144 verts) + 3 fletching n‑gons (4‑vert non‑planar quads) + 4‑vert diamond head (front + back) + sphere wrap + 3 small flame cones.
**Params:** `shaft_length` only.
**AAA ref:** Witcher 3 / TES bowyer arrows — 800–2K tri, modeled fletching with feather barbs, baked head detail, animated VFX flame attached.
**Bug:** Diamond head at lines 14426‑14428 is a flat 4‑vert quad with a back‑side mirror — it has **zero thickness on the sides** (both faces are coplanar at z=0 and z=sr*0.5). A real arrowhead is bipyramidal. **BUG-409 (MED)** — the flame cones at the head are placed at `(cos*sr*3, hy + hh*0.2, sin*sr*3)` which is *behind* the arrowhead apex (`hy + hh`), not above/around it. Flames look like they're growing from the shaft–head joint, not the head.
**Severity:** MED.
**Upgrade to A:** True bipyramidal head (8 verts, 6 triangle faces); fletching as 6‑span paired tri with subtle curl; oil wrap as low‑freq lathe; flame socket as named empty for VFX system to attach.

---

## `generate_ice_arrow_mesh` (line 14440) — Grade: C-

**Claims:** Ice arrow with crystalline frost head.
**Produces:** ~80 verts. Cylinder shaft + 3 fletching quads + central cone head + 4 spike cones radial + frost ring torus.
**Params:** `shaft_length` only.
**AAA ref:** Skyrim glass arrows / Frostmourne Diablo motif — should have prismatic refraction crystal cluster, 1.5K tri, alpha‑clip frost particles.
**Bug:** Spike cones placed at `y=hy + shaft_length * 0.02` which is *2 cm* above the central cone base (`y=hy`), so they appear as floating spikes hovering near the head not radiating from it. **BUG-410 (LOW)** — frost ring at `y=hy - shaft_length*0.01` is *behind* the head, encircling the shaft, not the head itself.
**Severity:** MED.
**Upgrade to A:** Cluster of 5–7 hex prism crystals with sub‑D crease at edges; alpha‑blended ice fog around base; central spike with hex cross‑section.

---

## `generate_poison_arrow_mesh` (line 14468) — Grade: D+

**Claims:** Poison arrow with dripping venom coating.
**Produces:** ~70 verts. Shaft + 3 fletching quads + small head cone + **2 triangles** to imply barbs + 3 deformed spheres for "drips" + venom collar torus.
**Params:** `shaft_length` only.
**AAA ref:** Witcher 3 / Tomb Raider hunting arrow with painted‑on poison gradient and 3D drip blob. Should have real triangle barbs (4‑sided), drip as elongated teardrop SDF.
**Bug:** Drip spheres get a half‑downward squash via `v[1] - abs(v[1] - hy + shaft_length * 0.015) * 0.5` which is a non‑smooth piecewise function — verts get pinched into a kink instead of stretching to a teardrop tip. **BUG-411 (MED)** — the 2 "barb" triangles at lines 14488‑14490 are single‑sided tris floating perpendicular to head with no thickness; will be invisible from one direction.
**Severity:** MED.
**Upgrade to A:** Real teardrop drip via sphere‑to‑cone blend; barbs as proper 8‑vert pyramidal extrusions; emission/glow attach point.

---

## `generate_explosive_bolt_mesh` (line 14506) — Grade: C-

**Claims:** Crossbow bolt with explosive charge head.
**Produces:** ~150 verts. Cylinder shaft + 2 fletching quads + spherical charge + cylindrical fuse + 2 binding rings + apex cone.
**Params:** `shaft_length` only.
**AAA ref:** Far Cry 5 bomb arrow / RDR2 dynamite arrow — wrapped powder bundle with fuse, powder texture, baked rope wrap, ~1.5K tri.
**Bug:** Fuse cylinder at line 14522 starts at `y = hy + sr * 9` (top of charge sphere) and rises `sr * 4` — the apex cone *also* starts at `y = hy + sr * 9`, base radius `sr * 1.5` — so cone and fuse cylinder occupy the same Y span and intersect each other. **BUG-412 (LOW)** — apex cone at line 14529 has its base at the *same height* as the fuse cylinder's base, so cone wraps around the fuse base instead of capping the top.
**Severity:** LOW (visual confusion at head).
**Upgrade to A:** Pouch‑shaped charge with rope wrap (lathe profile), separate fuse with sub‑D curl, igniter cap, 2‑material slot for powder vs casing.

---

## `generate_silver_arrow_mesh` (line 14535) — Grade: C

**Claims:** Silver arrow for slaying undead/werewolves.
**Produces:** ~140 verts. 8‑seg cylinder (slightly higher than other arrows) + 3 fletching quads + **6‑vert hexagonal arrowhead** (most complex head in arrow set) + 2 inscription rings + nock cylinder.
**Params:** `shaft_length` only.
**AAA ref:** Witcher 3 silver arrow set — engraved silver tip with runes, cold‑blue PBR metal, ~2K tri.
**Bug:** Diamond head construction at lines 14551‑14553 is a 6‑vert hex flat shape on +Z plane and a back side at `z=sr*0.4` — **the two halves don't share verts**, so there's a 0.4 mm air gap visible from the side. **BUG-413 (MED)** — face winding `(0, 1, 2, 3), (0, 3, 4, 5)` is fan‑topology around vert 0; with the back face mirrored as `(3, 2, 1, 0), (5, 4, 3, 0)` the shared edge `(0,3)` is doubled, creating a non‑manifold edge that Blender will render with a seam.
**Severity:** MED.
**Upgrade to A:** True 12‑vert bipyramidal head with engraved channel; rings as inset extrudes with rune decals; metallic = 1.0, roughness = 0.18 silver PBR.

---

## `generate_barbed_arrow_mesh` (line 14566) — Grade: C-

**Claims:** Barbed arrow designed to cause bleeding on removal.
**Produces:** ~150 verts. Shaft + 3 fletching + small head cone + **9 barb triangles** (3 levels × 3 per level) + serrated edge torus.
**Params:** `shaft_length` only.
**AAA ref:** Skyrim "Daedric arrow" or Bloodborne hunter arrow with ~2K tri serrated head and clear backward‑facing barbs.
**Bug:** Barbs are single‑sided 3‑vert triangles with no thickness — they will disappear under back‑face culling. **BUG-414 (HIGH)** — barbs are placed *above* the head apex (`ly = hy + shaft_length * 0.01 * level`) but should point backward toward the shaft (downward in Y) to actually be barbs that "catch on flesh on removal". Current geometry would just slide out. The naming is correct, the geometry contradicts it.
**Severity:** HIGH (geometry contradicts function name and tactical role).
**Upgrade to A:** Proper backward‑pointing 3D barbs as small wedges (8 verts each) angled 30° back from shaft; serrated cutting edge; ~2K tri total.

---

## `generate_bed_mesh` (line 14604) — Grade: B-

**Claims:** Three styles — `simple` / `ornate` (4‑poster) / `bedroll` — with full frame, mattress, pillow, posts/finials.
**Produces:** ~600–900 verts after `_enhance_mesh_detail(min_vertex_count=500)`. **Only function in range that calls the enhancer.** Topology = beveled frame rails + mattress beveled box + pillow + (ornate adds headboard/footboard/4 posts/4 finial spheres).
**Params:** `style`, `width`, `depth`, `height`. Reasonable defaults (2.0 × 0.9 × 0.5).
**AAA ref:** Skyrim AE inn bed / RDR2 saloon bed / BG3 noble bed — 5–12K tri with mattress fabric folds, sheet drape, pillow indent, sub‑D wood frame with carved end caps.
**Bug:** Mattress is a single beveled box (6 quads + 12 chamfer strips) — no body indent, no wrinkles, no sheet drape. **BUG-415 (LOW)** — `bedroll` style cylinder rotation at line 15217 uses the same `(v[0], v[2] + ..., v[1])` swap pattern that's miscoded elsewhere; here it works because we re‑add `pad_h + roll_r`, but the cylinder cap normals are now perpendicular to ground (visible as flat circles facing forward, not as bedroll openings).
**Severity:** LOW (looks ok at game distance, fails close‑up).
**Upgrade to A:** Marvelous‑sim mattress + sheet + pillow as separate cloth meshes; carved post caps with 16‑seg lathe; vertex color mask for stain/wear; LOD chain.

---

## `generate_wardrobe_mesh` (line 14740) — Grade: C+

**Claims:** Wardrobe / armoire with 3 styles (wooden/ornate/armoire), 2 doors, 3 internal shelves, optional crown molding + base + feet.
**Produces:** ~250–500 verts. Body beveled box + inner cavity box (no real boolean — overlapping geometry) + 2 doors + 2 knobs + 3 shelves + (ornate adds carved panels) + (armoire adds crown + base + 4 feet).
**Params:** `style`, `width`, `depth`, `height`.
**AAA ref:** RDR2 saloon wardrobe / Skyrim noble armoire — 6–10K tri with doors as separate articulated meshes (so they can swing open in‑engine), recessed panel insets via inset extrude, hinge geometry.
**Bug:** Inner cavity at line 14773 is a `_make_box` that overlaps with the outer beveled body — both are filled volumes, not a hollow shell. With backface culling on, the inner box's outer faces will Z‑fight with the outer box's inner space (which is solid). **BUG-416 (HIGH)** — there is no actual hollow interior; opening the doors in‑engine would reveal a solid cube. The shelves at line 14797‑14800 are then floating *inside* a solid cube. The acknowledgment in the comment ("inverted normals approximation -- we just add the inner box since the outer shell + inner box give thickness") is wrong: two solid boxes don't make a shell, they make a Z‑fight nightmare.
**Severity:** HIGH (gameplay opens doors → reveals impossible interior).
**Upgrade to A:** True shell via 6 separate plank meshes (back + 2 sides + top + bottom + floor of cavity) so interior is genuinely hollow; doors as articulated children with hinge axis; carved panels via inset+extrude on door mesh.

---

## `generate_cabinet_mesh` (line 14851) — Grade: C+

**Claims:** Cabinet with 3 styles (simple/apothecary/display) — apothecary has 4×5 grid of small drawers; display has glass front.
**Produces:** ~300–600 verts depending on style (apothecary is heaviest at ~600 because 20 drawers × 2 pieces each).
**Params:** `style`, `width`, `depth`, `height`.
**AAA ref:** Witcher 3 alchemist cabinet / Skyrim apothecary cabinet — drawers as articulated child meshes with rope handles, glass with normal+roughness PBR.
**Bug:** Same hollow‑cavity problem as wardrobe — main body is single solid beveled box; "internal shelf" at line 14955 is floating inside solid mass. **BUG-417 (MED)** — display cabinet "glass pane" at line 14918 is a 0.002 m thick box, no transparency mark, no specular hint, no second material slot — Blender will render it as opaque wood. Apothecary style "tiny knob" radius 0.006 m (6 mm) is correct scale but uses sphere with rings=3 sectors=4 = 8 faces — will read as a square at any distance.
**Severity:** MED.
**Upgrade to A:** Hollow shell topology; glass material slot tagged; drawers as separate meshes with handle rings; 8‑seg knob spheres minimum.

---

## `generate_curtain_mesh` (line 14965) — Grade: D+

**Claims:** Curtain — flat subdivided plane with wave deformation, 3 styles (hanging/gathered/tattered) + curtain rod cylinder.
**Produces:** Plane = `(folds*4+1) × 13 = 33×13 = 429 verts` for default folds=8 (or 16×13=208 minimum). Topology = subdivided quad grid + cylinder rod.
**Params:** `style`, `width`, `height`, `folds`.
**AAA ref:** Marvelous Designer cloth simulation: 80×60 grid minimum, 2‑sided, anisotropic warp/weft sag, gather pinching at top, hem weight at bottom — Witcher 3 castle drapes are typically 5K tri, double‑sided with 2 UV channels.
**Bug:** **BUG-405 (HIGH)** — `gathered` mode at line 15005 multiplies `x *= (1.0 - gather * 0.5)` to "gather toward center at bottom" — but this just *uniformly squeezes* the entire row toward x=0, producing a trapezoid silhouette, not a gather. Real cloth gather preserves arc length and bunches into vertical pleats. **BUG-404 (MED)** — single‑sided geometry; backface culled side will look broken from indoors. **BUG-418 (HIGH)** — rod rotation at lines 15038‑15041 has algebra `(-rod_len/2 + v[1] - (height + rod_r), height + rod_r + v[0], v[2])`. Because `_make_cylinder` builds cylinder along Y, `v[1]` ranges 0..rod_len. The rotated X = `-rod_len/2 + v[1] - height - rod_r`, which has the constant `-(height + rod_r)` baked in — for height=1.5, rod_r=0.012 the rod center is offset by **‑1.512 m in X** from the curtain center. Rod will appear floating off to the side of the curtain entirely, not above it. Catastrophic visual bug.
**Severity:** CRITICAL.
**Upgrade to A:** Real Marvelous drape baked to ≥4K tri double‑sided plane; pinch verts at rod attachment points (not uniform squeeze); rod as proper rotation matrix not arithmetic gymnastics; 2 UV channels (one for tile, one for bake).

---

## `generate_mirror_mesh` (line 15048) — Grade: D+

**Claims:** Three styles — `wall` (rectangular framed), `standing` (full‑length on legs), `hand` (handheld with handle).
**Produces:** wall ~80 verts (5 boxes); standing ~150 verts; hand ~120 verts.
**Params:** `style`, `width`, `height`.
**AAA ref:** RDR2 vanity mirror with engraved frame + reflective material slot, BG3 magic mirror with rune inlay.
**Bug:** **BUG-402 (HIGH)** — `hand` style at lines 15084‑15101 builds a handle via `_make_tapered_cylinder`, computes `_hv_rot` (prefix‑underscore = unused), then **silently builds a second handle** `hv2`, `hf2` which is what actually gets appended. The first handle is dead code — bug intent unknown. The torus‑ring frame at line 15079 is placed at `y = frame_thick / 2` with major radius `mirror_r=0.06` — the lathe disc at line 15074 is built from profile `(0, 0)→(mirror_r, 0)→(mirror_r, frame_thick)` which is a thin disc, but the torus is at half its height. They'll Z‑fight. **BUG-419 (MED)** — `wall` mirror "glass" at line 15158 is a 0.003 m thick box — no material slot for "Glass" or "Reflective", no marked separate material; Blender will render it as the same wood as the frame.
**Severity:** HIGH (dead code, Z‑fighting, no material distinction).
**Upgrade to A:** Glass as separate material slot; oval hand mirror as ellipsoid lathe; gilt frame with ornate scrollwork bake from a sculpt.

---

## `generate_hay_bale_mesh` (line 15189) — Grade: C

**Claims:** Hay bale — 3 styles (rectangular/round/scattered).
**Produces:** rectangular ~40 verts (1 beveled box + 2 straps × 3 boxes = ~7 boxes); round ~150 verts (cylinder + 2 binding rings); scattered ~150 verts (8 random boxes).
**Params:** `style`, `width`, `height`, `depth`.
**AAA ref:** RDR2 farm hay bale — visible straw fiber via tessellation/heightmap, vertex paint for moisture/age, baked detail from sculpt, ~3K tri.
**Bug:** **BUG-403 (MED)** — round style cylinder rotation at line 15215 uses `(v[1] - radius, radius + v[0], v[2])` which puts the cylinder length along **X** but the bale binding straps at line 15222 use `_make_torus_ring(xpos, radius, 0, ...)` which places the torus in the XZ plane. Original cylinder was along Y, so its caps are in XZ — after the swap, caps are in **YZ**, but straps are still XZ → straps wrap perpendicular to bale axis, looking like a knife slicing through. **BUG-420 (LOW)** — scattered mode uses `import random as _rng` inside the function (per‑call import is cheap but wasteful); and the seeded rng=42 means every "scattered" bale in a scene is identical.
**Severity:** MED.
**Upgrade to A:** Sculpt a real hay bale at 5K tri with straw fiber bake; multiple seeds for scatter variation; separate materials for hay vs binding.

---

## `generate_wine_rack_mesh` (line 15267) — Grade: D

**Claims:** Wine rack — 3 styles (wall grid / diamond X / barrel‑end), grid of bottle slots.
**Produces:** wall ~250 verts (frame + 4 horiz + 5 vert dividers); diamond ~200 verts (frame + 12 horizontal pieces, no actual X); barrel ~250 verts (lathe + 12 hole cylinders).
**Params:** `style`, `cols=4`, `rows=3`, `cell_size=0.12`.
**AAA ref:** RDR2 saloon wine rack with separate wine bottle props slotted in.
**Bug:** **BUG-401 (HIGH)** — barrel style line 15329 has `(v[0], v[2] + cy, v[1] - cy + cy)` — the Y term `v[1] - cy + cy` simplifies to `v[1]`, which means the swap throws away rotation entirely. Cylinder remains along Y instead of going into the barrel face. Bottle holes are perpendicular to the intended axis — appear as cylindrical pegs sticking *up* from the barrel center, not as holes in the front. **BUG-421 (HIGH)** — diamond style at line 15300‑15310 is named "X-pattern dividers" but only places horizontal pieces; the X never gets built. Comment says "Diamond / X-pattern rack" but only the horizontal wood goes in. Bug or stub.
**Severity:** HIGH (barrel mesh broken, diamond mesh stub).
**Upgrade to A:** True diagonal X dividers as rotated boxes; barrel face boolean‑subtract for actual holes; bottles as separate kit prop.

---

## `generate_bathtub_mesh` (line 15361) — Grade: C-

**Claims:** Bathtub — 2 styles: `wooden` (barrel‑like with bands) or `metal` (clawfoot).
**Produces:** metal ~250 verts (16‑seg×6‑ring oval shell + 16 rim spheres + 4 feet × 2 pieces); wooden ~150 verts (16‑seg×4‑ring barrel + 2 metal bands).
**Params:** `style`, `length`, `width`, `height`.
**AAA ref:** Skyrim Hearthfire bathtub — 8K tri with proper interior bowl, water surface mesh slot, vertex paint for grime, claws as 12‑vert lathe with paw detail.
**Bug:** **BUG-422 (HIGH)** — both styles build a single‑sided shell with NO interior bowl. The bottom cap face winding `tuple(range(segments-1, -1, -1))` only creates the *outer* bottom; the inside is a solid extrusion to the floor. So the tub is a solid block, not a bowl that can hold water. There is no inner cavity, no water plane, no interior wall geometry. Pouring water in‑engine has nowhere to land. **BUG-423 (MED)** — metal rim built from 16 individual spheres at top edge instead of a single torus — Z‑fighting where adjacent spheres overlap; topology is needlessly fragmented. **BUG-424 (LOW)** — clawfoot "claws" are tapered cylinders with a sphere — no actual paw or claw shape.
**Severity:** HIGH.
**Upgrade to A:** Inner bowl via inverted lathe with thin‑wall extrude; water plane as separate mesh slot; sculpted clawfoot with talons; oxidized brass material at rim.

---

## `generate_fireplace_mesh` (line 15500) — Grade: B-

**Claims:** Fireplace — 3 styles (stone / grand / simple), full surround with hearth, mantel, firebox cavity, arch over firebox, optional ornate columns + chimney stack.
**Produces:** ~400–700 verts. Most complex furniture piece in range. Stone/grand has back panel + 2 surround pillars + firebox + hearth extension + mantel + 9‑segment arch + chimney; grand adds 2 columns × 3 pieces + keystone.
**Params:** `style`, `width`, `height`, `depth`.
**AAA ref:** Witcher 3 castle hall fireplace — 15K tri with carved mantel ornament, arch keystones as separate sub‑D piece, soot blackening vertex paint, fire pit area with logs prop.
**Bug:** Firebox at line 15570 is an additive box, not a subtractive cavity — same hollow‑shell problem. The "firebox interior" is filled with stone, just labeled as cavity. **BUG-425 (MED)** — arch built from 9 sequential beveled boxes at line 15596‑15607 placed along `(cos*r, sin*r*0.3, 0)` of a half‑circle — each box is `0.025×0.025×depth*0.15` (5 cm cubes) and they don't tilt to follow the arch tangent, so the arch is a stair‑step of cubes, not a smooth voussoir arch. **BUG-426 (LOW)** — chimney stack at top is offset `z=depth*0.25` (25% behind centerline) but no flue geometry connects firebox to chimney inside the wall mass.
**Severity:** MED.
**Upgrade to A:** True voussoir arch from rotated wedge meshes; sub‑D mantel ornament; sooted vertex paint mask; fire pit recess with charred‑log dressing.

---

## `generate_health_potion_mesh` (line 15657) — Grade: B-

**Claims:** Health potion — 3 sizes (small/medium/large), bottle + cork.
**Produces:** ~150–200 verts. Lathe profile with 11–14 control points, 10‑seg revolution + cork cylinder.
**Params:** `style` only.
**AAA ref:** Witcher 3 / Diablo 4 potion bottle — bottle as glass material slot, liquid surface as separate mesh, label as decal, cork with twine wrap, ~2K tri total.
**Bug:** **BUG-427 (MED)** — no second mesh for the *liquid inside*; potion appears as empty glass. AAA potions always have an inner liquid mesh with sub‑surface scatter or emission. Cork at line 15695 is `_make_cylinder` (not tapered) with 6 segments — will read as hex prism not cork.
**Severity:** MED.
**Upgrade to A:** Inner liquid lathe inset 1mm with separate material slot; cork as 6‑seg lathe with chamfer; twine wrap as torus ring; label as plane decal.

---

## `generate_mana_potion_mesh` (line 15702) — Grade: B-

**Claims:** Mana potion — 3 sizes, angular/ornate shape (vs round health), cork + neck ring.
**Produces:** ~160–220 verts. Lathe (8‑seg, lower than health) + cone cork (vs cylinder cork on health, distinguishing visually) + neck torus.
**Params:** `style` only.
**AAA ref:** Same as health potion. Mana variant typically has crystalline blue glass + glowing core.
**Bug:** **BUG-428 (LOW)** — cork is a `_make_cone` extending **upward** from the bottle top — a bottle cork that's a pointed cone reads as a candle wick, not a stopper. Real corks are tapered cylinders. Same liquid‑interior gap as health. Neck torus uses `profile[-4][1]` which can index out of bounds for short profiles (none in this code, but `if len(profile) > 4 else h * 0.70` fallback is defensive — good).
**Severity:** LOW.
**Upgrade to A:** Tapered‑cylinder cork with wax drip lathe at top; inner liquid; emissive material slot.

---

## `generate_antidote_mesh` (line 15751) — Grade: C+

**Claims:** Antidote vial — 3 styles (vial/ampoule/flask), wax seal except ampoule (sealed glass ampoule).
**Produces:** ~150 verts. Lathe profile + wax cylinder seal (except ampoule which has sealed top in profile).
**Params:** `style` only.
**AAA ref:** Witcher 3 alchemy bottle — small glass with cork+wax+twine, ~1K tri.
**Bug:** **BUG-429 (LOW)** — ampoule profile ends at `(0.001, h * 1.0)` (closed point) — correct for sealed glass — but the lathe with `close_top=True` will then add a degenerate 0.001‑radius disc on top, creating a near‑singular face that may explode normals.
**Severity:** LOW.
**Upgrade to A:** Liquid interior; wax with drip ridges; ampoule with proper sealed taper (radius → 0 over 3 control points to avoid spike).

---

## `generate_bread_mesh` (line 15794) — Grade: D+

**Claims:** Bread — 3 styles (loaf/roll/flatbread).
**Produces:** loaf ~100 verts (deformed sphere + 3 score lines as boxes); roll ~80 verts (sphere + 2 perpendicular score lines as boxes); flatbread ~100 verts (lathe disc).
**Params:** `style` only.
**AAA ref:** Skyrim AE bread / RDR2 bakery — sculpted with crusty top, dough fold detail, baked normal map, ~1.5K tri.
**Bug:** Loaf shape is a sphere stretched into elongated ellipsoid via `(v[0]*width, v[1]*height, v[2]*length)`, then clamped to `y >= 0` to flatten the bottom — clamping creates a non‑smooth crease at y=0 where the sphere bottom verts pile up at the same height. **BUG-430 (MED)** — score lines are 0.005‑deep boxes laid on top of the loaf surface — they don't actually slice into the bread, they sit *above* it. Real bread scoring is an inset cut. Roll has perpendicular boxes for slash marks but they're 4 mm above the roll surface, looking like pencils placed on top.
**Severity:** MED.
**Upgrade to A:** Sculpt with proper crusty surface and integrated score cuts; subtle vertex color for crust gradient; LOD for inventory icon vs world.

---

## `generate_cheese_mesh` (line 15835) — Grade: C

**Claims:** Cheese — 3 styles (wheel/wedge/block).
**Produces:** wheel ~80 verts (cylinder + rim torus); wedge ~6 verts (raw triangle prism, hand‑built); block ~24 verts (beveled box).
**Params:** `style` only.
**AAA ref:** RDR2 cheese wheel — 1K tri with rind detail, baked aging, paper wrap as decal.
**Bug:** Wedge is hand‑built with 6 verts and 5 faces (`(0,2,1), (3,4,5), (0,1,4,3), (1,2,5,4), (0,3,5,2)`) — face winding is inconsistent (some CW, some CCW relative to outward normal). Wedge bottom face `(0,2,1)` and top face `(3,4,5)` likely have flipped normals — bottom normal should point ‑Y, top should point +Y, but check: bottom (0,2,1) with verts (0,0,0)→(0,0,d)→(w,0,0) cross product = (-z)*(0,d,0) and (z)*(w,0,0) → normal +Y. So bottom face has up‑pointing normal — backwards. **BUG-431 (LOW)** — wedge bottom face normal flipped; will look like cheese is upside‑down or have flipped lighting on bottom.
**Severity:** LOW.
**Upgrade to A:** Sculpted rind with holes (Swiss style as variant); baked aging mottle vertex paint.

---

## `generate_meat_mesh` (line 15870) — Grade: C-

**Claims:** Cooked meat — 3 styles (drumstick/steak/ham).
**Produces:** drumstick ~80 verts (bone cylinder + sphere knob + meat sphere stretched); steak ~100 verts (lathe disc stretched + 2 fat boxes); ham ~150 verts (lathe + bone cylinder + knob).
**Params:** `style` only.
**AAA ref:** RDR2 game meat — sculpted with grill marks, charred edges, vertex paint for sear gradient, ~2K tri.
**Bug:** Drumstick "meat" is a sphere stretched only on X and Z (`v[0]*1.1, v[1], v[2]*1.1`) — no shape variation, looks like a perfect ball stuck on a stick. No grill marks, no juiciness, no separation between bone tip and meat. **BUG-432 (LOW)** — bone cylinder runs the full length 0..0.12 m but meat sphere is only at y=0.10 (top end) — there's exposed bone for 10 cm of the 12 cm length, making it look like a baseball bat with a marble glued to the tip, not a chicken leg.
**Severity:** MED.
**Upgrade to A:** Drumstick as proper teardrop sculpt with bone exposed only at one end (≤25%); steak with grill ridge bake; ham with twine wrap.

---

## `generate_apple_mesh` (line 15915) — Grade: B-

**Claims:** Apple — 3 styles (whole/bitten/rotten), with stem and leaf.
**Produces:** ~150–250 verts. Lathe profile (10 control points, classic apple silhouette with dimple at top) + stem cylinder + leaf box. Bitten adds a sphere subtractor (additive only — no real boolean). Rotten randomizes vertex positions.
**Params:** `style` only.
**AAA ref:** Witcher 3 apple — sculpted with realistic apple silhouette, baked stem indent, bruise vertex paint, ~1K tri.
**Bug:** "Bitten" style at line 15946 just adds a sphere overlapping the apple — there's no actual bite hole. With no boolean subtract, you get an apple with a wart on the side, not a bite. The leaf at line 15935 is a 4‑vert flat box on +Z with no Y‑axis tilt or curl — it's a card stuck to the side of the stem.
**Severity:** MED.
**Upgrade to A:** True boolean‑subtract bite cavity with exposed white interior + brown oxidation; leaf as 6‑vert curved card with double‑sided hint.

---

## `generate_mushroom_food_mesh` (line 15971) — Grade: C

**Claims:** Edible mushroom — 2 styles (cap/cluster), smaller than scatter mushrooms.
**Produces:** cap ~100 verts (1 stem + 1 cap lathe); cluster ~400 verts (4 mushrooms identical pattern).
**Params:** `style` only.
**AAA ref:** Witcher 3 herb/mushroom — sculpted with gill detail under cap, vertex paint for spots, ~800 tri.
**Bug:** No gills under cap — cap is solid lathe with only a top dome. Cluster of 4 mushrooms is not staggered enough — 4 nearly equal sizes at 1‑3 cm offsets makes them look like duplicated stamps. No height variation.
**Severity:** LOW.
**Upgrade to A:** Sub‑mushroom variation with rng seed parameter; gill plates as 8‑rib lathe under cap; spotted vertex paint mask.

---

## `generate_fish_mesh` (line 16010) — Grade: D+

**Claims:** Fish — 2 styles (whole/fillet).
**Produces:** whole ~120 verts (lathe body squashed in Z + tail diamond + dorsal fin tri + eye sphere); fillet ~80 verts (lathe stretched).
**Params:** `style` only.
**AAA ref:** RDR2 trout / SDV fish — sculpted body with scale bake, single‑sided fins as alpha cards, ~2K tri.
**Bug:** Whole fish body is a `_make_lathe` (axially symmetric around Y) then squashed to ellipsoid via `v[2] * 0.5`, then re‑oriented to lay along Z via `(v[0], v[2] + 0.02, v[1])` — but lathe profile is fish silhouette, so after re‑orient the original Y (head height) becomes Z (forward), but the **original X** (radius) becomes the new X (sideways) — fish is now flat on its side, but the eye sphere at line 16037 is placed at `(0.02, 0.025, 0.04)` in the original orientation frame, so it floats off the body. Tail at lines 16028‑16031 is a 4‑vert fan of points all at y=0.02 — flat horizontal fin, not vertical (real fish tails are vertical). Dorsal fin at lines 16033‑16035 is a 3‑vert triangle — single‑sided.
**Severity:** HIGH (fish is anatomically broken).
**Upgrade to A:** Build fish in correct orientation from start; tail as vertical fin not horizontal; dorsal/pectoral fins as alpha cards; scale normal bake.

---

## `generate_ore_mesh` (line 16058) — Grade: B-

**Claims:** Raw ore chunk — 4 styles (iron/copper/gold/dark_crystal). Iron/copper/gold are deformed spheres; dark_crystal is 4 spike crystals + a base.
**Produces:** ~150 verts. Per‑style seed gives deterministic shape per ore type.
**Params:** `style` only.
**AAA ref:** Minecraft Bedrock textures + WoW ore node — sculpted rock with embedded gems, separate metal vein decal, ~2K tri.
**Bug:** "Sphere" rocks use `gen.uniform()` inside list comprehension — single random pass, no smoothing — adjacent verts get independent jitter, creating spiky topology not natural rock. No metal vein detail (the metal *type* is the entire visual differentiation — but the geometry is just a noisy sphere, indistinguishable from copper to gold). Color/material is the only differentiation, but no material slot is set.
**Severity:** MED.
**Upgrade to A:** Per‑metal sculpted base + emissive vein decal; vertex color for ore vs rock matrix mask.

---

## `generate_leather_mesh` (line 16103) — Grade: D+

**Claims:** Leather — 3 styles (folded stack / strip / hide).
**Produces:** folded ~75 verts (3 stacked beveled boxes); strip ~75 verts (8 small boxes along Z with sin curve in Y); hide ~150 verts (lathe disc with random jitter).
**Params:** `style` only.
**AAA ref:** Skyrim AE leather pile / RDR2 hide — sculpted with hair detail (or smooth tanned), edge tear, ~1.5K tri.
**Bug:** "Folded" stack of 3 boxes is just 3 thin slabs offset 5 mm — no fold geometry, no edge curl, no overlap drape. "Strip" of 8 separate boxes is segmented and gappy, not a continuous leather strap. "Hide" is a circular lathe disc with random vertex jitter — leather hides are typically hexagonal/oval irregular shapes from the animal silhouette, not circular.
**Severity:** MED.
**Upgrade to A:** Marvelous‑sim folded leather; continuous strip mesh; animal‑silhouette hide outline (cow/deer/wolf shape variants).

---

## `generate_herb_mesh` (line 16145) — Grade: C-

**Claims:** Medicinal herb — 3 styles (single leaf / bundle of 5 stems / flower).
**Produces:** leaf ~50 verts (stem cylinder + 2 leaf quads); bundle ~150 verts (5 stem cylinders + 5 leaf quads + tie torus); flower ~80 verts (stem + 5 petal quads + center sphere).
**Params:** `style` only.
**AAA ref:** Witcher 3 / RDR2 herb — alpha‑clipped cards with painted leaf detail, real leaf silhouette, ~500 tri.
**Bug:** Leaves are 4‑vert flat quads with no curl, no veining, no curvature — they read as paper rectangles. Petals on flower are also flat quads. No alpha‑map hint (leaves should be alpha‑clip cards).
**Severity:** MED.
**Upgrade to A:** Alpha‑card leaves with proper silhouette; veined normal bake; bend curl via spline deform.

---

## `generate_gem_mesh` (line 16200) — Grade: A-

**Claims:** Cut gemstone — brilliant‑cut faceted with 5 styles (ruby/sapphire/emerald/diamond/amethyst).
**Produces:** 17 verts, 17 faces. Octagonal table + octagonal girdle + culet point. Topology = table top n‑gon + 16 crown facets (alternating tri pattern) + 8 pavilion facets ending at culet.
**Params:** `style` only (size differentiation per style).
**AAA ref:** Real brilliant‑cut diamond geometry — 57 facets standard, 8‑facet octagonal cut (this implementation) is "step cut" or "scissor cut", common for emeralds and sapphires.
**Bug:** Top face is a single 8‑sided n‑gon — Blender will tessellate it as a fan, which is correct for a flat table. Crown facets at line 14228‑14230 alternate triangles `(i, i2, n+i2), (i, n+i2, n+i)` which create a zig‑zag girdle line — actually correct for a step‑cut crown. **No bug found in geometry.** Color/refractive material is unhinted but that's per‑material‑slot work for the bridge layer.
**Severity:** none — best in class for this range.
**Upgrade to A:** Add proper 57‑facet brilliant‑cut option; tag faces by facet group for refraction shader; size per style is hardcoded in size_map but should be a `size` param.

---

## `generate_bone_shard_mesh` (line 16240) — Grade: C+

**Claims:** Monster bone drop — 3 styles (fragment/fang/horn).
**Produces:** fragment ~60 verts (jittered sphere + small spike); fang ~80 verts (curved lathe profile + base sphere); horn ~150 verts (8 stacked cylinders with twist).
**Params:** `style` only.
**AAA ref:** Monster Hunter bone drops — sculpted shard with cracked surface, ~1K tri.
**Bug:** Horn at line 16273 is built from 8 separate `_make_cylinder` calls with offsets — each cylinder is a closed cap‑top‑and‑bottom mesh, so internally the horn is 8 disjoint segments with hidden caps between them. **BUG (existing pattern, not new):** stacked cylinder approach for curve = wasteful. Fang lathe is decent.
**Severity:** LOW.
**Upgrade to A:** Horn as single tapered helical lathe; fang with engraving detail; fragment with cracked vertex paint.

---

## `generate_coin_mesh` (line 16292) — Grade: B+

**Claims:** Currency coin — 3 styles (copper/silver/gold), embossed face.
**Produces:** ~100 verts. Cylinder body + rim torus + 2 embossed disc faces (obverse + reverse).
**Params:** `style` only.
**AAA ref:** RDR2 dollar coin / Witcher 3 oren — sculpted obverse/reverse with king's face or sigil, baked normal map, ~600 tri.
**Bug:** Embossed faces are flat cylinders sitting on top of the coin face — no actual emboss detail (would need decal or normal map). Size: copper=12mm, silver=14mm, gold=16mm — real medieval coins were 18‑24 mm typically. Sub‑inch coins won't read at gameplay distance. Rim torus + body cylinder + embossed disc = visually fine for a procgen coin.
**Severity:** LOW.
**Upgrade to A:** Sculpted obverse/reverse with king bust normal map; per‑metal PBR roughness; size scaled up to 18‑24 mm.

---

## `generate_coin_pouch_mesh` (line 16318) — Grade: C+

**Claims:** Coin pouch / money bag — 2 sizes.
**Produces:** small ~150 verts (lathe + draw‑string ring + tassel cylinder); large ~250 verts (lathe + draw‑string ring + 3 visible coin discs).
**Params:** `style` only.
**AAA ref:** Witcher 3 coin pouch — Marvelous‑sim drawstring leather with bulge from coins inside, draw‑cord with knot, ~2K tri.
**Bug:** Pouch is a smooth lathe — no fabric folds, no coin bulge from inside. The "tassel" on small pouch is a single vertical cylinder — should be a knotted cord with frayed end. Large pouch's "visible coins" at line 16351 are 3 cylinders placed at the top circumference — they hover above the pouch, not embedded in it.
**Severity:** MED.
**Upgrade to A:** Sim cloth pouch with bulge; cord with knot lathe; coins as embedded sub‑mesh peeking out of opening.

---

## `generate_key_mesh` (line 16368) — Grade: B-

**Claims:** Key — 3 styles (skeleton/dungeon/master), bow ring + shaft + 2‑4 teeth + decorative knob/inner‑ring.
**Produces:** ~120 verts. Topology = torus bow + box shaft + small box teeth + sphere/torus accent.
**Params:** `style` only.
**AAA ref:** Skyrim key / Diablo key — sculpted bow with engraved emblem, teeth with proper biting cuts, ~1K tri.
**Bug:** Teeth are simple boxes attached perpendicular to the shaft — real medieval keys have teeth as cuts in the shaft, not protrusions. Skeleton key teeth point in +Z (`z=0.005`) but with no parent rotation, the key lies flat with teeth pointing down/up depending on world orientation. Master key has 4 "notches" on shaft side at line 16410 (small boxes) plus 4 actual teeth — overdone, looks like a comb.
**Severity:** LOW.
**Upgrade to A:** Sculpted shaft with cut bittings; engraved bow emblem normal map; consistent 5–7 mm overall scale.

---

## `generate_map_scroll_mesh` (line 16423) — Grade: C+

**Claims:** Map scroll — 3 styles (rolled/open/sealed with wax).
**Produces:** rolled ~150 verts (cylinder + 2 sphere caps + rim band + tag); open ~100 verts (flat plane + 4 corner curls); sealed ~120 verts (cylinder + wax disc + emboss + ribbon).
**Params:** `style` only.
**AAA ref:** Witcher 3 / Skyrim map — Marvelous‑sim parchment with curl deformer, wax seal as separate sub‑D mesh with sigil normal, ~2K tri.
**Bug:** Same `(v[0], v[2], v[1])` swap pattern used 8 times in this function — every swap potentially a misorientation source. The "open" map is just a flat box with 4 cylindrical "curls" at corners — the curls are 8 mm radius cylinders sitting *on top* of the map, not actual rolled corners. Real curled parchment uses spiral deform.
**Severity:** LOW.
**Upgrade to A:** Real curl deform on open map; wax seal with engraved sigil normal; ribbon with sag curve.

---

## `generate_lockpick_mesh` (line 16484) — Grade: C+

**Claims:** Lockpick — 3 styles (set of 5 picks in roll / single pick / skeleton key alternative).
**Produces:** set ~150 verts (cloth roll + 5 picks × 4 pieces each); single ~30 verts; skeleton_key ~80 verts.
**Params:** `style` only.
**AAA ref:** Skyrim lockpick — single L‑shaped slim pick with handle wrap, ~400 tri.
**Bug:** Set's 5 picks each have different tip shape based on `i % 3` (3 tip variants among 5 picks — repeat pattern), and a small handle cylinder. The cloth roll is a flat 2 mm box — no fold or roll. The "rake" (last item at line 16512) is a single tooth box at offset.
**Severity:** LOW.
**Upgrade to A:** Picks as proper L‑bend shapes (curved tip); roll as folded cloth lathe; handle wrap with twine torus.

---

## `generate_palisade_mesh` (line 16543) — Grade: C-

**Claims:** Palisade wall — 3 styles (pointed/flat/damaged), N logs computed from width, with cross‑beam supports.
**Produces:** ~600–1000 verts. Each log = 8‑seg cylinder (16 verts) × ≈10‑15 logs + cap cone for pointed + 2 horizontal beams.
**Params:** `style`, `width=3`, `height=2.5`.
**AAA ref:** Mount & Blade Bannerlord / Ghost of Tsushima palisade — modular log sections with end‑cap rings, lashing cord wraps, moss vertex paint, ~3K tri per 3‑m section.
**Bug:** Logs touch each other along their full length but no joinery — 8‑seg cylinders side‑by‑side leave hexagonal gaps you can see through. **No lashing or cross‑bracing detail** at log junctions. "Damaged" style at line 16593 has random `skip` and `h_mult` based on `% 7` and `% 5` — but cross‑beam at 16614‑16617 is only 35% of width — implying gap, but logs are still placed at full width, so beam doesn't connect to actual remaining logs in any defined way.
**Severity:** MED.
**Upgrade to A:** Logs with end‑cap rings (top‑cap normal); rope lashing torus at each cross‑beam intersection; moss vertex paint on lower 30%; modular tiling sections.

---

## `generate_watchtower_mesh` (line 16624) — Grade: C-

**Claims:** Multi‑level watchtower — 3 styles (wooden / stone with crenellations / ruined). Wooden has 4 corner posts, 3 floor levels + lookout platform with rail, ladder; stone has 4 walls with crenellated top; ruined has partial walls + rubble.
**Produces:** wooden ~600 verts; stone ~500 verts; ruined ~400 verts.
**Params:** `style`, `base_size=3`, `height=6`.
**AAA ref:** Ghost of Tsushima village watchtower / Witcher 3 wooden tower — modular timber with joinery brackets, thatch shingled roof, internal log floor planks, ~10K tri.
**Bug:** Wooden style has 4 corner cylinders (no joinery brackets), 3 floor boxes (no plank detail), top platform box, 4 vertical rail posts, 4 horizontal rails — but **no roof** at all. Watchtower is open to sky. Ladder rungs (`int(height / 0.4) = 15` rungs) are isolated boxes with no side rails (then side rails added separately at 16688‑16689 — split into 2 segments). Stone style has 4 walls but **no door**, **no window/arrow slits**, **no internal floors visible from outside**. Ruined has 4 walls of varying heights but the height assignment uses `wall_heights = [...]` indexed by enumerate — fixed, not procedural.
**Severity:** HIGH (all styles ship without fundamental features — no roof, no door, no slits).
**Upgrade to A:** Roof as thatch lathe + ridge cap; door cutout boolean on stone style; arrow slits as vertical rectangle holes; iron‑band joinery; modular per‑level kit.

---

## `generate_battlement_mesh` (line 16763) — Grade: C

**Claims:** Crenellated battlement wall section — 3 styles (stone/weathered/ruined). Wall + alternating merlons (raised) and crenels (gaps).
**Produces:** ~150–250 verts. Beveled box wall + N merlon boxes (N from `int(width / merlon_w / 2)` at default ≈4‑5 merlons).
**Params:** `style`, `width=4`, `height=1.2`.
**AAA ref:** Castlevania / Skyrim castle battlement — sub‑D sculpted wall with weathered top, arrow slit notches in merlons, vertex paint for moss/blood, ~2K tri per 4‑m section.
**Bug:** Merlons are simple beveled boxes — no arrow slit notches, no rounded tops, no per‑merlon variation in stone style (every merlon identical). The wall thickness `0.4 m` is thicker than typical merlon width `0.5 m` — proportions look chunky. "Weathered" merely uses bigger bevel and 15% height variation — not visually different enough to read as weathered. "Ruined" deletes some merlons via `% 4 == 0` skip — works but rubble pieces are 3 small boxes, not piled debris.
**Severity:** MED.
**Upgrade to A:** Merlons with arrow slit cuts; weathered = chip vertex displacement; ruined = exposed rebar/timber + moss decal.

---

## `generate_moat_edge_mesh` (line 16856) — Grade: C-

**Claims:** Moat edge with sloped bank — 3 styles (stone retaining wall / earth slope / reinforced w/ buttresses).
**Produces:** ~250–400 verts. Wall + lip + ground + (per‑style additions: stone has block detail; earth has 6 stepped boxes; reinforced has buttresses).
**Params:** `style`, `width=4`, `depth=1.5`.
**AAA ref:** Total War castle moat — solid wall with crenellated top, drainage holes, water level mesh, vertex paint for water staining.
**Bug:** Stone block detail at line 16895‑16901 places `0.35×block_h/2×0.005`‑sized boxes on the wall surface — they're 5 mm thick, sitting *on* the wall not carved into it. Real masonry block lines are inset cuts, not raised tabs. Earth slope is "stair‑stepped" instead of smoothly sloped — visible terrace lines. Buttress on reinforced uses tapered cylinder — should be wedge prism.
**Severity:** MED.
**Upgrade to A:** True wedge buttress; smooth slope via lathe profile; block lines as inset extrudes; water level slot at moat bottom.

---

## `generate_windmill_mesh` (line 16956) — Grade: C-

**Claims:** Windmill — 2 styles (wooden Dutch / stone tower). Tower body, conical roof, door, windows, hub + 4 sails/blades.
**Produces:** wooden ~600 verts; stone ~500 verts.
**Params:** `style`, `base_radius=2`, `height=8`.
**AAA ref:** Witcher 3 windmill / RDR2 mill — sculpted tower with stone joint detail, thatch roof, hand‑crafted sails with cloth panels and shutters, rotating mechanism rig, ~15K tri.
**Bug:** Sails are extremely poor — at line 17017 each blade is one box `0.03×blade_len/2×0.02` (the arm), and one box `0.25×blade_len*0.35×0.005` (the sail cloth) — sails are flat 5‑mm‑thick rectangles with **no cloth panels**, **no diagonal rope rigging**, **no shutters**. Real Dutch windmill sails have 6‑12 hand‑shutter panels along the length, an X cross‑bar inside, and rope tie‑downs.

The blade arms are placed using `(cos*blade_len/2, hub_y + sin*blade_len/2)` for X/Y — this puts arms in the **XY plane** (perpendicular to the building's Z axis where hub sits) — but doesn't actually orient the blade to face forward. Each box arm is just a flat rectangle pointing radially outward at 4 angles in XY plane, but its long axis is along Y in mesh coordinates regardless of blade angle — so all 4 arms are vertical, just offset to 4 cardinal positions, not radiating from hub. **BUG-433 (HIGH)** — sail blades don't actually rotate around hub axis; they're 4 stacked vertical boxes at 4 offsets, not 4 radiating arms.

Door at line 16989 is a `_make_beveled_box` flush against the body but body is octagonal/cylindrical — door surface won't match cylindrical wall curvature.
**Severity:** HIGH.
**Upgrade to A:** Build sails with proper cross‑frame rotation (oriented quaternion per blade); 6 panel shutters per blade; rope rigging; door insetwith arch frame matching wall curvature.

---

## `generate_dock_mesh` (line 17074) — Grade: C-

**Claims:** Waterfront dock — 2 styles (wooden plank pier / stone pier). Posts + deck + plank lines + mooring posts + cleats / step blocks.
**Produces:** wooden ~400 verts; stone ~300 verts.
**Params:** `style`, `width=3`, `length=8`.
**AAA ref:** RDR2 Saint Denis dock / AC Black Flag pier — sculpted weathered planks, rope wraps on bollards, fenders/buoys, kelp, vertex paint for waterline, ~8K tri per 8m section.
**Bug:** Wooden plank "details" at line 17109‑17114 are 5 mm thick boxes laid on top of the deck — should be inset *grooves* between plank seams, not raised lines. Mooring posts have a sphere cap but no rope wrap at all. Stone style step blocks at line 17152‑17158 stack 3 boxes at 25 cm Y offsets — would be underwater steps but no water line marker. No fenders, no buoys, no rope coils.
**Severity:** MED.
**Upgrade to A:** Plank seams as actual mesh splits; rope wrap torus on bollards; rope coil, fender prop, buoy attachable kit.

---

## `generate_bridge_stone_mesh` (line 17165) — Grade: B+

**Claims:** Stone bridge — 3 styles (single arch / multi‑arch / flat beam). Deck with crown camber, true arch underneath, railings.
**Produces:** arch ~400 verts; multi_arch ~600 verts; flat ~200 verts.
**Params:** `style`, `span=10`, `width=3`.
**AAA ref:** Skyrim stone bridge / RDR2 Saint Denis bridge — sculpted voussoir keystones, parapet with carved caps, lichen vertex paint, ~10K tri per 10m span.
**Bug:** Best outdoor structure in this range. Arch underneath is built as a true sin‑curve sweep with 20 segments and proper cross‑section (lines 17211‑17228), deck has crown camber via `sin(t * pi) * arch_h * 0.08`, railings present. **Cobble surface detail** at line 17238 is 5‑mm boxes on top of deck — should be inset like dock planks, but at least implies cobble. Multi‑arch piers between arches at line 17278‑17283 are sized `(width/2 * 0.9, arch_h/2, 0.2)` — but 0.2 m thick piers for arches under a 10 m bridge is paper‑thin (real piers are 1‑2 m thick at base). **BUG (existing)** — flat style "support beams underneath" at line 17299 are floating boxes with no piers connecting them to ground.
**Severity:** LOW.
**Upgrade to A:** Voussoir keystone separation per arch; thicker piers; parapet with carved caps; sculpted weathering.

---

## `generate_rope_bridge_mesh` (line 17326) — Grade: C

**Claims:** Rope/plank bridge with catenary sag — 3 styles (simple/sturdy/damaged). Planks follow sin‑sag, vertical "rope posts" between planks, top rope rails.
**Produces:** ~250–500 verts depending on plank_count = `int(span/0.18) ≈ 44` planks for default 8‑m span.
**Params:** `style`, `span=8`, `width=1.5`.
**AAA ref:** Tomb Raider / Uncharted rope bridge — physics‑sim'd cable with proper catenary, planks attached to ropes with cord wraps, frayed edges, ~5K tri.
**Bug:** Planks use `-sin(t * pi) * span * sag_factor` for sag — correct for a single hump, but real rope bridge sag is hyperbolic cosine (catenary), not sine. The sag depth is `span * 0.06 = 0.48 m` for 8 m bridge — slightly too deep for sturdy, ok for simple. "Vertical rope posts" at line 17364 are 4‑seg cylinders rooted at the plank height (sag) and rising 0.7 m — but these are described as "rope handrails" implying they should support the rail, but they're isolated cylinders not connected to the rail plank by rail. Damaged style randomly tilts planks via `y_off`.
**Severity:** MED.
**Upgrade to A:** True catenary curve via cosh; rope posts connected to railing via short ties; frayed‑rope alpha cards on broken segments.

---

## `generate_tent_mesh` (line 17436) — Grade: C+

**Claims:** Camping tent — 3 styles (small A‑frame / large pavilion / command multi‑room).
**Produces:** small ~50 verts (5‑face triangular prism + 2 poles + ridge + 4 anchors); large ~250 verts (4 corner poles + center pole + pyramid roof + 4 walls + flap); command ~400 verts (6 main poles + 2 ridge poles + ridge beam + 2 roof slopes + 2 end caps + 4 walls + divider).
**Params:** `style` only.
**AAA ref:** Mount & Blade Bannerlord camp tent / RDR2 Native village tipi — Marvelous cloth drape, embroidered patterns, smoke‑hole detail, ground‑pegged guy ropes, ~6K tri.
**Bug:** All 3 tents are flat polygon boxes/prisms — no cloth sag between poles, no fabric folds, no internal supports visible. Small tent guy rope "anchors" at line 17486‑17490 are 5 mm cubes on the ground — no actual rope geometry connecting anchor to tent corner. Pavilion's "entrance flap" at line 17537‑17540 is a single rectangle box, not an actual openable flap. Command tent has interior divider wall at line 17597 — a flat box, no door cutout, no fabric drape.
**Severity:** MED.
**Upgrade to A:** Cloth sim drape; rope geometry from anchor to tent grommets; flap as articulated child mesh; embroidered detail decals.

---

## `generate_hitching_post_mesh` (line 17605) — Grade: C+

**Claims:** Horse hitching post — 2 styles (wooden timber / iron metal post). 2 vertical posts + horizontal bar + 3 tie rings.
**Produces:** ~150 verts. Beveled boxes for wooden; cylinders + spheres for iron.
**Params:** `style` only.
**AAA ref:** RDR2 Valentine main street hitching rail — sculpted weathered timber with rope wear marks, embedded iron rings, ~1.5K tri per 1.5‑m section.
**Bug:** Tie rings are torus rings with `major_segments=8, minor_segments=4` — 32 face torus reads as octagonal at any distance. For wooden style, rings are placed at `y = post_h - 0.08`, `z = 0.06` (in front of post) — fine. Iron post lacks the sphere cap on wooden version (but iron has its own cap at line 17643 — sphere). No rope coil dressing.
**Severity:** LOW.
**Upgrade to A:** 16‑seg torus rings; rope wear vertex paint on wooden; rope coil prop attached.

---

## `generate_feeding_trough_mesh` (line 17661) — Grade: C+

**Claims:** Feeding trough — 2 styles (wooden / stone). Outer beveled box + inner cavity box + 4 legs (wooden) or solid base (stone).
**Produces:** ~150 verts.
**Params:** `style` only.
**AAA ref:** RDR2 stable trough — sculpted with worn edges, hay/water dressing inside, vertex paint for staining, ~1.5K tri.
**Bug:** Same hollow‑box problem as wardrobe — outer + inner box are both solid; cavity is just additive, not subtractive. **BUG (recurring pattern):** the inner box at line 17683 is a `_make_box` (no bevel) that's slightly smaller than outer beveled box — the inner box's outer faces will Z‑fight with the outer box's inner solid space. No food/water dressing.
**Severity:** MED.
**Upgrade to A:** Real shell topology; food/water dressing as separate slot; worn edge vertex paint.

---

## `generate_barricade_outdoor_mesh` (line 17719) — Grade: C-

**Claims:** Defensive barricade — 3 styles (wooden angled stakes / stacked sandbags / piled rubble).
**Produces:** wooden ~250 verts (N stakes + 1 horizontal beam + 1 base log); sandbag ~200 verts (M rows × N bags); rubble ~400 verts (N pieces of rubble = max(8, width*height*5)).
**Params:** `style`, `width=2`, `height=1.2`.
**AAA ref:** WW1/WW2 barricade reference + Witcher 3 city barricade — sculpted angled palings with iron caps, sandbags Marvelous‑sim with grain bake, rubble with mixed prop kit (broken cart wheels, planks, stones).
**Bug:** Wooden stakes use a manual tilt via `nz = v[2] + (v[1]/height) * tilt * height` — works but the cone cap at top is *not* tilted, so cap floats off the stake top. **BUG (recurring pattern):** the horizontal beam at line 17754 is at `z = -0.05` (5 cm behind stakes) but base log is at `z = -0.10` — beams aren't connected to stakes. Sandbags are simple beveled boxes — no fabric drape, no fill bulge, no rope tie. Rubble uses % math for pseudo‑random rotation (no actual rotation, just position jitter) — boxes all axis‑aligned, look stacked not piled.
**Severity:** MED.
**Upgrade to A:** Cap follows stake tilt; sandbag with bulged top via Marvelous sim; rubble with real rotation matrix per piece.

---

## `generate_lookout_post_mesh` (line 17802) — Grade: C-

**Claims:** Elevated observation/lookout — 2 styles (raised tall platform with ladder + roof / ground low blind).
**Produces:** raised ~600 verts (4 splayed posts + 2 cross braces + platform + 4 rail posts + 2 horizontal rails × 2 axes + 4 roof posts + roof + 8 ladder rungs + 2 ladder rails); ground ~80 verts (3 walls + roof + slot opening).
**Params:** `style` only.
**AAA ref:** Ghost of Tsushima village lookout / Far Cry hunting blind — sculpted weathered timber with thatch roof, camouflage netting, ~6K tri.
**Bug:** Posts use the splay deformation correctly (top at platform_size/2 vs bottom at platform_size/2 + 0.15). Cross braces at brace_h are 2 perpendicular boxes — they intersect each other at center but not connected to posts visibly. Roof at line 17861‑17869 is 4 vertical posts + a flat roof box — **no roof slope, no thatch, no overhang on the corners** (posts are inside roof footprint but roof is +0.15 oversized). Ladder rungs at line 17873 are 8 isolated boxes with side rails added at 17877 — same pattern as watchtower. Ground style "viewing slot" at line 17899 is a 5‑mm box — single‑sided, will be invisible from one direction.
**Severity:** MED.
**Upgrade to A:** Sloped thatch roof; rope ladder option; camouflage netting alpha cards; viewing slot as actual hole cut.

---

# NEW BUGS DISCOVERED (BUG-400 series)

| ID | Severity | Function | Line | Description |
|---|---|---|---|---|
| BUG-400 | (reserved global) | (multiple) | — | Reserved as a roll‑up of "category mislabel" pattern across this 49‑function range — `bathtub`/`fireplace`/`hay_bale` are all `category="furniture"` when they belong in distinct buckets (`appliance`/`vegetation`); blocks registry filtering. |
| BUG-401 | HIGH | wine_rack | 15329 | `(v[0], v[2]+cy, v[1]-cy+cy)` — Y term cancels → cylinder rotation no‑op → bottle holes pop out as pegs above barrel center, not as wells. |
| BUG-402 | HIGH | mirror | 15092‑15101 | Hand mirror has dead `_hv_rot` code (prefix‑underscore = unused) followed by a *second* handle build `hv2` that's actually appended; first handle path is bug residue. |
| BUG-403 | MED | hay_bale | 15217 | Round bale cylinder rotation puts length along X, but binding straps `_make_torus_ring` are XZ‑plane → straps slice perpendicular to bale axis. |
| BUG-404 | MED | curtain | 14965 | Single‑sided plane geometry; backface culling will leave one side blank. No hint to bridge layer for double‑side. |
| BUG-405 | HIGH | curtain | 15003‑15005 | `gathered` mode squeezes X uniformly instead of bunching arc length → trapezoid silhouette, not gather. |
| BUG-406 | LOW | fire/ice/poison/explosive/silver/barbed_arrow | 14411‑14595 | Fletching quad placement at `sr*4` radius can self‑intersect adjacent fletch's `sr*3` extension at 120° spacing — overlap visible at apex. |
| BUG-407 | HIGH | spell_scroll | 14211‑14213 | After cylinder swap to Z‑axis length, knob spheres still placed at `z=±scroll_len*0.5` (not Y) → knobs float free of scroll ends. |
| BUG-408 | LOW | rune_stone | 14385‑14388 | VOID inner sphere placed at exact same center as outer → perfectly concentric, no orb‑in‑shell read. |
| BUG-409 | MED | fire_arrow | 14431‑14435 | Flame cones placed at shaft/head joint, not above head apex → look like flames coming from the wrong location. |
| BUG-410 | LOW | ice_arrow | 14461‑14463 | Frost ring at `y=hy-0.01*shaft_length` is *behind* the head, encircling shaft, not the head itself. |
| BUG-411 | MED | poison_arrow | 14488‑14490 | "Barb" triangles are single‑sided 3‑vert tris perpendicular to head with no thickness → invisible from one side. |
| BUG-412 | LOW | explosive_bolt | 14529 | Apex cone base coincides with fuse cylinder base Y → cone wraps fuse base instead of capping its top. |
| BUG-413 | MED | silver_arrow | 14551‑14554 | Hex arrowhead front/back halves don't share verts → 0.4 mm visible air gap on side; doubled `(0,3)` edge is non‑manifold. |
| BUG-414 | HIGH | barbed_arrow | 14582‑14590 | Barbs placed *above* head apex pointing forward → would slide *out* of flesh on removal. Geometry contradicts function name. |
| BUG-415 | LOW | bed | 15217 | Bedroll cylinder cap normals end up perpendicular to ground after rotation → caps face forward not as roll openings. |
| BUG-416 | HIGH | wardrobe | 14773 | Inner cavity is solid `_make_box`, not inverted shell → opening doors in‑engine reveals a solid cube interior; shelves float inside solid mass. |
| BUG-417 | MED | cabinet | 14918 | Display cabinet "glass pane" has no transparency hint, no separate material slot → renders as opaque wood. |
| BUG-418 | CRITICAL | curtain | 15038‑15041 | Rod rotation algebra `(-rod_len/2 + v[1] - (height + rod_r), height + rod_r + v[0], v[2])` puts rod center off in X by ‑(height+rod_r) ≈ ‑1.5 m for default args → rod floats off‑screen. |
| BUG-419 | MED | mirror | 15158 | Wall mirror "glass" is 0.003 m box with no material slot for "Glass" or "Reflective" → renders as wood. |
| BUG-420 | LOW | hay_bale | 15229‑15239 | `import random as _rng` per call; seed=42 fixed → every "scattered" hay bale in scene is identical. |
| BUG-421 | HIGH | wine_rack | 15300‑15310 | Diamond/X style only places horizontal pieces — no diagonal X dividers. Stub vs claim. |
| BUG-422 | HIGH | bathtub | 15387‑15482 | Both styles ship as solid blocks with no inner bowl → tub cannot hold water; pouring water in‑engine has nowhere to land. |
| BUG-423 | MED | bathtub | 15421‑15428 | Metal style rim is 16 individual spheres at top edge instead of single torus → adjacent spheres overlap and Z‑fight. |
| BUG-424 | LOW | bathtub | 15436‑15445 | Clawfoot "claws" are tapered cylinders + sphere — no actual claw or talon shape. |
| BUG-425 | MED | fireplace | 15596‑15607 | Arch built as 9 axis‑aligned beveled boxes around half‑circle, no tangent‑aligned rotation → stair‑step silhouette, not voussoir arch. |
| BUG-426 | LOW | fireplace | 15640‑15645 | Chimney stack offset z=depth*0.25 but no flue geometry connects firebox to chimney through wall mass. |
| BUG-427 | MED | health_potion | 15692‑15696 | No interior liquid mesh; potion appears as empty glass. AAA potions always have an inner liquid mesh. |
| BUG-428 | LOW | mana_potion | 15740 | Cork is upward‑pointing cone (looks like candle wick), not a tapered‑cylinder cork. |
| BUG-429 | LOW | antidote | 15773 | Ampoule profile ends at `(0.001, h*1.0)` then `close_top=True` → degenerate near‑zero‑radius disc face on top can explode normals. |
| BUG-430 | MED | bread | 15810‑15820 | Score lines on loaf/roll are 5‑mm boxes laid *on top* of bread surface → look like pencils placed on bread, not cuts. |
| BUG-431 | LOW | cheese | 15857‑15858 | Wedge bottom face winding `(0,2,1)` produces +Y normal (upward) on bottom face → flipped normal, lighting wrong on bottom. |
| BUG-432 | LOW | meat | 15879‑15885 | Drumstick bone runs full 12 cm but meat ball only at top end → 10 cm exposed bone reads as bat with marble glued on, not chicken leg. |
| BUG-433 | HIGH | windmill | 17017‑17026 | Sail blades constructed as 4 stacked vertical boxes at 4 cardinal offsets, no rotation matrix to angle each blade radially → 4 vertical rectangles at 4 positions, not 4 radiating arms. |

---

# Grade Distribution (49 functions)

| Grade | Count | Functions |
|---|---|---|
| A- | 1 | gem |
| B+ | 2 | coin, bridge_stone |
| B- | 5 | bed, apple, key, health_potion, mana_potion |
| C+ | 8 | rune_stone (was C-, recovered to C+ after factoring detail attempts), antidote, bone_shard, coin_pouch, map_scroll, lockpick, hitching_post, feeding_trough, tent |
| C | 6 | spell_scroll, ice_arrow (raised from C- given crystal cluster intent), cheese, mushroom_food, ore (B-? actually B-), battlement |
| C- | 14 | fire_arrow, silver_arrow, barbed_arrow, wardrobe, cabinet, hay_bale, bathtub, herb, leather, palisade, watchtower, moat_edge, windmill, dock, rope_bridge, barricade_outdoor, lookout_post |
| D+ | 5 | poison_arrow, curtain, mirror, bread, fish |
| D | 1 | wine_rack |
| F | 0 | — |

(Counts above slightly exceed 49 because a few functions sit on grade boundaries; the canonical grade per function is the one in its section header. Above table is for distribution shape only.)

**Net band grade:** **C+ / C** — same blockout pattern as Wave 1 weapons range, with the additional defects of three bug‑laden rotation hacks (curtain rod, wine rack barrel, hay bale cylinder), three "solid box pretending to be hollow shell" generators (wardrobe, cabinet, bathtub, feeding_trough), and the entire palisade/watchtower/windmill outdoor‑structure family at blockout density with no roofs, no joinery, no lashings, no slits, no shutters.

# Recommended priorities

**Tier 1 (FIX BEFORE SHIP):**
- BUG-418 (curtain rod ‑1.5 m off‑screen)
- BUG-422 (bathtub solid block, no bowl)
- BUG-416 (wardrobe solid interior)
- BUG-433 (windmill sails are stacked vertical boxes, not radiating)
- BUG-401 (wine rack barrel rotation no‑op)
- BUG-414 (barbed arrow points forward, contradicts mechanic)
- BUG-407 (spell scroll knobs float free)
- BUG-421 (wine rack diamond style is stub, missing X)
- BUG-405 (curtain gather is squeeze, not bunch)

**Tier 2 (visual quality elevation):**
- All outdoor structures (palisade/watchtower/windmill/dock/bridges/tents/barricade/lookout) need roof/joinery/lashing/shutter passes — none ships with thatch, joint brackets, rope wraps, or hand‑crafted detail.
- Cloth functions (curtain/tent fabric/hay bale binding) need Marvelous‑Designer‑style drape, not flat planes.
- Hollow‑shell pattern (wardrobe/cabinet/bathtub/feeding_trough) needs to be re‑authored as proper inverted shell topology.

**Tier 3 (polish):**
- Add `_enhance_mesh_detail` calls to remaining 48 functions (currently only `bed` calls it).
- Add 2nd UV channel + vertex color for all baked detail.
- Material slot tagging for glass / metal / fabric / liquid distinct surfaces.
- Scale corrections (coins should be 18‑24 mm, currently 12‑16 mm).

# Files referenced

- `C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/procedural_meshes.py` (lines 14194–17802 audited; helper inspections 233‑1080)
