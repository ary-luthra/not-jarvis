"""Named head poses and antenna presets. Pure data, no imports from the rest of the package.

Pose conventions:
    yaw / pitch / roll — degrees
    x / y / z         — meters, SDK frame (X+ forward, Y+ left, Z+ up)

Antenna conventions:
    [left_rad, right_rad] — signed radians; positive reads as "perked forward"
"""

from collections import namedtuple


Pose = namedtuple("Pose", "yaw pitch roll x y z", defaults=(0, 0, 0, 0, 0, 0))


# ── Named head poses ──
# Tune amplitudes against hardware. These are conservative starting values.
POSES: dict[str, Pose] = {
    # Baseline neutral, deliberately asymmetric so it doesn't read as a mannequin
    "center":        Pose(yaw=2, pitch=3),

    # Head tilts — "leaning to hear"
    "tilt_L":        Pose(yaw=6,  pitch=3, roll=12,  y=0.012),
    "tilt_R":        Pose(yaw=-6, pitch=3, roll=-12, y=-0.012),

    # Thinking "look away" poses — pull-back reads as introversion
    "look_away_L":   Pose(yaw=-14, pitch=-8, roll=-3, x=-0.015),
    "look_away_R":   Pose(yaw=14,  pitch=-8, roll=3,  x=-0.015),

    # Alternative ponder poses (used inside thinking state for variety)
    "ponder_up_R":   Pose(yaw=8,  pitch=-6, roll=3,  x=-0.01),
    "ponder_up_L":   Pose(yaw=-8, pitch=-6, roll=-3, x=-0.01),

    # Translation-led gestures
    "lean_in":       Pose(pitch=-3, x=0.02),
    "pull_back":     Pose(pitch=5,  x=-0.025),
    "stretch_up":    Pose(pitch=-3, z=0.015),
    "duck":          Pose(pitch=2,  z=-0.012),
    "recoil":        Pose(pitch=6,  x=-0.03, z=0.006),

    # Lateral peeks — curious sideways lean
    "peek_L":        Pose(yaw=4,  y=0.018),
    "peek_R":        Pose(yaw=-4, y=-0.018),

    # Nod components
    "nod_down":      Pose(pitch=7, x=0.01),
    "nod_up":        Pose(pitch=-3, x=-0.005),

    # Overhead stare / contemplation
    "look_up":       Pose(pitch=-15, z=0.012),

    # Quick sideway glances (used for idle gaze-shifts)
    "gaze_L":        Pose(yaw=-12, pitch=3),
    "gaze_R":        Pose(yaw=12,  pitch=3),
}


# ── Antenna presets ──
# Left/right in radians. Asymmetric presets are for "listening hard" vibes.
ANTENNAS: dict[str, list[float]] = {
    "relaxed":    [-0.1, -0.1],
    "alert":      [ 0.3,  0.3],
    "perked":     [ 0.5,  0.5],
    "droop":      [-0.5, -0.5],
    "listen_L":   [ 0.5,  0.1],
    "listen_R":   [ 0.1,  0.5],
    "curious_L":  [ 0.4, -0.1],
    "curious_R":  [-0.1,  0.4],
    "flick_L":    [ 0.6, -0.1],
    "flick_R":    [-0.1,  0.6],
    "flat":       [ 0.0,  0.0],
}
