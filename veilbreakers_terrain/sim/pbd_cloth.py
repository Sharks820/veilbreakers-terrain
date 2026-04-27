"""pbd_cloth.py — XPBD cloth and flag simulation for terrain props.

Implements Position-Based Dynamics with the XPBD compliance correction
(Macklin et al. 2016) for offline baking of hanging cloth terrain props:
banners, curtain doors, flags, tapestries.

Constraint topology matches Maya nCloth:
  Structural — horizontal + vertical neighbours (stretch resistance)
  Shear      — diagonal neighbours (shear resistance)
  Bend       — skip-one neighbours (bend/drape resistance)

Wind model matches Maya nCloth aerodynamics:
  F_wind = c_wind * dot(face_normal, wind - v_particle) * face_normal

Sources:
  Muller et al. 2007 PBD original (matthias-research.github.io)
  Macklin et al. 2016 XPBD (matthias-research.github.io)
  mottosso.com nCloth reference — Maya parameter defaults and ranges
  homo-deus.com — constraint topology (structural/shear/bend), wind formula
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ClothParams:
    """Spring-mass parameters with Maya nCloth equivalents documented."""
    rows: int = 20
    cols: int = 15
    width: float = 2.0   # metres, horizontal
    height: float = 3.0  # metres, vertical drop

    # Maya nCloth equivalents: stretch_resistance=k_structural, bend_resistance=k_bend
    k_structural: float = 300.0
    k_shear: float = 80.0
    k_bend: float = 1.5

    mass: float = 0.05    # kg per particle (Maya: mass=1.0, but scaled differently)
    damping: float = 0.98
    c_wind: float = 0.05  # aerodynamic coefficient (Maya: air_drag=0.05 combined)

    wind_velocity: np.ndarray = field(default_factory=lambda: np.array([2.0, 0.5, 0.3]))
    wind_turbulence: float = 0.4

    gravity: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, -9.81]))

    dt: float = 1.0 / 60.0
    n_substeps: int = 8
    n_constraint_iters: int = 10


# Presets for common VeilBreakers terrain props
BANNER_PARAMS = ClothParams(
    rows=20, cols=12, width=1.5, height=2.5,
    k_structural=400.0, k_shear=80.0, k_bend=0.8,
    mass=0.04,
    wind_velocity=np.array([1.5, 0.3, 0.1]),
    wind_turbulence=0.5,
)

CURTAIN_PARAMS = ClothParams(
    rows=25, cols=20, width=2.5, height=3.0,
    k_structural=200.0, k_shear=40.0, k_bend=0.3,
    mass=0.08,
    wind_velocity=np.array([0.2, 0.0, 0.05]),
    wind_turbulence=0.1,
)

FLAG_PARAMS = ClothParams(
    rows=15, cols=20, width=2.0, height=1.2,
    k_structural=250.0, k_shear=60.0, k_bend=0.5,
    mass=0.03,
    wind_velocity=np.array([3.0, 0.8, 0.4]),
    wind_turbulence=0.8,
)


def _build_constraints(
    params: ClothParams,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build structural, shear, and bend constraint arrays."""
    R, C = params.rows, params.cols
    dx = params.width / (C - 1)
    dy = params.height / (R - 1)
    diag = math.sqrt(dx ** 2 + dy ** 2)

    idx = np.arange(R * C).reshape(R, C)
    p_s, r_s = [], []
    p_sh, r_sh = [], []
    p_b, r_b = [], []

    for r in range(R):
        for c in range(C - 1):
            p_s.append([idx[r, c], idx[r, c + 1]]); r_s.append(dx)
    for r in range(R - 1):
        for c in range(C):
            p_s.append([idx[r, c], idx[r + 1, c]]); r_s.append(dy)

    for r in range(R - 1):
        for c in range(C - 1):
            p_sh.append([idx[r, c],     idx[r + 1, c + 1]]); r_sh.append(diag)
            p_sh.append([idx[r, c + 1], idx[r + 1, c]]);     r_sh.append(diag)

    for r in range(R):
        for c in range(C - 2):
            p_b.append([idx[r, c], idx[r, c + 2]]); r_b.append(2 * dx)
    for r in range(R - 2):
        for c in range(C):
            p_b.append([idx[r, c], idx[r + 2, c]]); r_b.append(2 * dy)

    return (
        np.array(p_s,  dtype=np.int32), np.array(r_s,  dtype=np.float64),
        np.array(p_sh, dtype=np.int32), np.array(r_sh, dtype=np.float64),
        np.array(p_b,  dtype=np.int32), np.array(r_b,  dtype=np.float64),
    )


def _project_xpbd(
    pos: np.ndarray,
    pairs: np.ndarray,
    rest: np.ndarray,
    inv_mass: np.ndarray,
    stiffness: float,
    dt_sub: float,
    lam: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised XPBD distance constraint projection (Macklin 2016)."""
    i0, i1 = pairs[:, 0], pairs[:, 1]
    diff = pos[i0] - pos[i1]
    dist = np.linalg.norm(diff, axis=1, keepdims=True) + 1e-12
    n_ = diff / dist
    C_ = dist[:, 0] - rest
    w0, w1 = inv_mass[i0], inv_mass[i1]
    alpha_t = 1.0 / (stiffness * dt_sub ** 2)
    d_lam = (-C_ - alpha_t * lam) / (w0 + w1 + alpha_t + 1e-12)
    lam += d_lam
    delta = np.zeros_like(pos)
    np.add.at(delta, i0,  (w0 * d_lam)[:, None] * n_)
    np.add.at(delta, i1, -(w1 * d_lam)[:, None] * n_)
    return pos + delta, lam


def simulate_cloth(
    params: ClothParams,
    pin_mask: np.ndarray,
    n_steps: int = 20,
    seed: int = 42,
) -> np.ndarray:
    """Run XPBD cloth for n_steps frames. Returns (n_steps+1, N, 3) position history.

    For static prop baking: use positions[-1] as rest mesh.
    For flag animation: use positions[::frame_skip] as shape keys.

    pin_mask: (N,) bool — True = pinned vertex (zero inverse mass).
    n_steps=20 is sufficient for static drape bake.
    n_steps=60 gives smooth flag loop frames.
    """
    rng = np.random.default_rng(seed)
    R, C = params.rows, params.cols
    N = R * C

    xs = np.linspace(0, params.width, C)
    zs = np.linspace(0, -params.height, R)
    xx, zz = np.meshgrid(xs, zs)
    pos = np.stack([xx.ravel(), np.zeros(N), zz.ravel()], axis=1).copy()
    vel = np.zeros((N, 3))
    inv_mass = np.where(pin_mask, 0.0, 1.0 / params.mass)

    p_s, r_s, p_sh, r_sh, p_b, r_b = _build_constraints(params)
    idx = np.arange(N).reshape(R, C)
    dt_sub = params.dt / params.n_substeps
    history = [pos.copy()]

    for _ in range(n_steps):
        for _ in range(params.n_substeps):
            noise = rng.standard_normal(3) * params.wind_turbulence * np.linalg.norm(params.wind_velocity)
            w = params.wind_velocity + noise

            f_wind = np.zeros((N, 3))
            for (ta, tb, tc) in [
                (idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[:-1, 1:].ravel()),
                (idx[1:, :-1].ravel(),  idx[1:, 1:].ravel(),  idx[:-1, 1:].ravel()),
            ]:
                v_ab = pos[tb] - pos[ta]
                v_ac = pos[tc] - pos[ta]
                fn = np.cross(v_ab, v_ac)
                mag = np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
                fn /= mag
                v_ctr = (vel[ta] + vel[tb] + vel[tc]) / 3.0
                dot = np.einsum('ij,ij->i', w[None] - v_ctr, fn)
                fw = (params.c_wind * dot)[:, None] * fn
                np.add.at(f_wind, ta, fw / 3)
                np.add.at(f_wind, tb, fw / 3)
                np.add.at(f_wind, tc, fw / 3)

            f_grav = params.gravity[None] * params.mass
            accel = (f_grav + f_wind) * inv_mass[:, None]
            vel = (vel + accel * dt_sub) * params.damping
            pos = pos + vel * dt_sub

            lam_s  = np.zeros(len(p_s))
            lam_sh = np.zeros(len(p_sh))
            lam_b  = np.zeros(len(p_b))
            for _ in range(params.n_constraint_iters):
                pos, lam_s  = _project_xpbd(pos, p_s,  r_s,  inv_mass, params.k_structural, dt_sub, lam_s)
                pos, lam_sh = _project_xpbd(pos, p_sh, r_sh, inv_mass, params.k_shear,      dt_sub, lam_sh)
                pos, lam_b  = _project_xpbd(pos, p_b,  r_b,  inv_mass, params.k_bend,       dt_sub, lam_b)

            vel = (pos - (pos - vel * dt_sub)) / dt_sub  # re-derive vel from corrected pos

        history.append(pos.copy())

    return np.array(history)


def bake_static_drape(
    params: ClothParams,
    pin_top_row: bool = True,
    n_steps: int = 20,
    seed: int = 42,
) -> np.ndarray:
    """Convenience: run 20-step sim and return final rest positions (N, 3).

    pin_top_row=True  → flag/banner pinned at top edge to a horizontal pole.
    pin_top_row=False → banner pinned at left edge to a vertical mast.
    """
    R, C = params.rows, params.cols
    N = R * C
    idx = np.arange(N).reshape(R, C)
    pin = np.zeros(N, dtype=bool)
    if pin_top_row:
        pin[idx[0, :]] = True
    else:
        pin[idx[:, 0]] = True
    history = simulate_cloth(params, pin, n_steps=n_steps, seed=seed)
    return history[-1]
