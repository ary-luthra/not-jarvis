"""Body motion subpackage: BodyController + data-driven gesture system.

Public entry point: BodyController. Data tables (POSES, ANTENNAS, GESTURES)
and primitives (Beat, Pose) are also exported for test notebooks.
"""

from .controller import BodyController
from .gestures import Beat, GESTURES, MIN_JERK, CARTOON, EASE_IN_OUT, LINEAR
from .poses import Pose, POSES, ANTENNAS
from .scheduler import GesturePool, RARITY_TIERS

__all__ = [
    "BodyController",
    "Beat", "Pose",
    "POSES", "ANTENNAS", "GESTURES",
    "GesturePool", "RARITY_TIERS",
    "MIN_JERK", "CARTOON", "EASE_IN_OUT", "LINEAR",
]
