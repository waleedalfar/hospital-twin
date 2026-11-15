"""Latent severity and vital signs (PROMPT.md §5.4).

Each patient has a hidden severity s(t) >= 0: a mean-reverting random walk (Ornstein-Uhlenbeck) around a
personal level `mu`, plus occasional deterioration episodes that push it up for several hours. Vitals are
drawn from s(t) plus noise. A critical event fires when s(t) crosses CRITICAL_THRESHOLD.
"""

import math
from typing import Any

from twin.common.ws import Vitals
from twin.sim import config as c
from twin.sim.entities import PatientProfile, Physiology


def initial_physiology(profile: PatientProfile, esi: int, respiratory: bool, rng: Any) -> Physiology:
    mu = c.BASE_MU_BY_ESI[esi] + 0.08 * profile.comorbidity_count + rng.gauss(0.0, 0.15)
    mu = max(c.MU_FLOOR, mu)
    return Physiology(s=max(0.0, mu + rng.gauss(0.0, 0.2)), mu=mu, respiratory=respiratory)


def episode_rate_per_h(profile: PatientProfile, esi: int, respiratory: bool, flu: bool, in_icu: bool) -> float:
    """Chance per hour that a deterioration episode starts: higher with age, comorbidities, ESI 1-2 and,
    for respiratory patients, during a flu surge."""
    rate = c.EPISODE_BASE_PER_H
    rate *= 1.0 + max(0, profile.age - 45) / 25.0
    rate *= 1.0 + 0.3 * profile.comorbidity_count
    rate *= c.EPISODE_ESI_FACTOR[esi]
    if flu and respiratory:
        rate *= c.EPISODE_FLU_RESPIRATORY_FACTOR
    if in_icu:
        rate *= 0.6
    return rate


def step(
    phys: Physiology,
    profile: PatientProfile,
    esi: int,
    now: float,
    dt_min: float,
    rng: Any,
    *,
    flu: bool,
    in_icu: bool,
    treated: bool,
) -> None:
    """Advance the hidden state by `dt_min` sim minutes."""
    dt_h = dt_min / 60.0
    if phys.episode_until < now and rng.random() < 1.0 - math.exp(-episode_rate_per_h(profile, esi, phys.respiratory, flu, in_icu) * dt_h):
        phys.episode_drift = rng.uniform(*c.EPISODE_DRIFT_PER_H)
        phys.episode_until = now + 60.0 * rng.uniform(*c.EPISODE_DURATION_H)
    if treated:
        target = c.ICU_TARGET_MU if in_icu else c.MU_FLOOR
        phys.mu = target + (phys.mu - target) * math.exp(-c.RECOVERY_RATE_PER_H * dt_h)
    theta = c.THETA_ICU_PER_H if in_icu else c.THETA_PER_H
    decay = math.exp(-theta * dt_h)
    spread = c.SIGMA_PER_SQRT_H * math.sqrt((1.0 - decay * decay) / (2.0 * theta))
    drift = phys.episode_drift * dt_h if phys.episode_until >= now else 0.0
    phys.s = max(0.0, phys.mu + (phys.s - phys.mu) * decay + spread * rng.gauss(0.0, 1.0) + drift)


def is_critical(phys: Physiology, now: float) -> bool:
    return phys.s >= c.CRITICAL_THRESHOLD and now >= phys.cooldown_until


def after_rapid_response(phys: Physiology, now: float) -> None:
    phys.s = max(0.0, phys.s - c.RAPID_RESPONSE_RELIEF)
    phys.episode_until = -1.0
    phys.cooldown_until = now + 60.0 * c.CRITICAL_COOLDOWN_H


def after_icu_transfer(phys: Physiology, now: float) -> None:
    phys.episode_until = -1.0
    phys.mu = max(phys.mu, c.ICU_TARGET_MU)
    phys.cooldown_until = now + 60.0 * c.CRITICAL_COOLDOWN_H


# Patients with a respiratory complaint run a lower SpO2 and a higher respiratory rate at any severity.
RESPIRATORY_SPO2_OFFSET = 5.0
RESPIRATORY_RR_OFFSET = 6.0


def vitals(phys: Physiology, profile: PatientProfile, rng: Any, flu: bool = False) -> Vitals:
    s = phys.s
    resp = phys.respiratory
    infection = 0.6 if resp else 0.0
    age_bp = 0.3 * (profile.age - 50)
    spo2_slope = 3.0 if resp else 2.2
    # During a flu surge respiratory patients present with lower SpO2 and a faster rate than usual. That is a
    # change in what the vitals look like, not in who is going to deteriorate: exactly what drift monitoring is for.
    spo2_base = 98 - (RESPIRATORY_SPO2_OFFSET if resp else 0.0) - (c.FLU_SPO2_SHIFT if flu and resp else 0.0)
    rr_base = 15 + (RESPIRATORY_RR_OFFSET if resp else 0.0) + (c.FLU_RR_SHIFT if flu and resp else 0.0)
    return Vitals(
        hr=round(72 + 14 * s + rng.gauss(0, 4)),
        spo2=round(min(100.0, max(70.0, spo2_base - spo2_slope * s + rng.gauss(0, 0.8)))),
        sbp=round(max(60.0, 124 + age_bp - 8 * s + rng.gauss(0, 6))),
        dbp=round(max(35.0, 78 + age_bp / 2 - 5 * s + rng.gauss(0, 4))),
        temp=round(36.8 + 0.35 * s + infection * min(1.0, s) + rng.gauss(0, 0.2), 1),
        rr=round(max(8.0, rr_base + 2.5 * s + rng.gauss(0, 1.5))),
    )
