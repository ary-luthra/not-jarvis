"""Pure helpers for body motion: pose construction, randomness, duration/amplitude rules."""

import math
import random

import numpy as np
from scipy.spatial.transform import Rotation as R


def make_pose(yaw: float = 0, pitch: float = 0, roll: float = 0,
              x: float = 0, y: float = 0, z: float = 0) -> np.ndarray:
    """Build a 4x4 head pose. Angles in degrees, translation in meters (SDK frame: X+ forward, Y+ left, Z+ up)."""
    pose = np.eye(4)
    pose[:3, :3] = R.from_euler("xyz", [roll, pitch, yaw], degrees=True).as_matrix()
    pose[:3, 3] = [x, y, z]
    return pose


def rand_signed(lo: float, hi: float) -> float:
    """Random magnitude in [lo, hi] with random sign."""
    return random.uniform(lo, hi) * random.choice([-1, 1])


def min_duration(amplitude_deg: float = 0, amplitude_m: float = 0) -> float:
    """Enforce duration >= max(0.15s, 0.02s/deg, 2.0s/m). Prevents servo-step artifacts."""
    return max(0.15, amplitude_deg * 0.02, amplitude_m * 2.0)


def split_body_head(target_yaw_deg: float) -> tuple[float, float, float]:
    """Decide how to split a yaw target between head and body.

    Returns (head_yaw_deg, body_yaw_rad, head_lead_seconds). The head_lead is
    how long the head should move before the body starts — gives the staggered,
    "lead with the head" feel.
    """
    abs_yaw = abs(target_yaw_deg)
    if abs_yaw < 10:
        return (target_yaw_deg, 0.0, 0.0)
    if abs_yaw < 25:
        head_frac, body_frac, lead = 0.8, 0.2, 0.05
    elif abs_yaw < 40:
        head_frac, body_frac, lead = 0.6, 0.4, 0.09
    else:
        head_frac, body_frac, lead = 0.5, 0.5, 0.12
    return (target_yaw_deg * head_frac,
            math.radians(target_yaw_deg * body_frac),
            lead)
