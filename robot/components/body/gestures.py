"""Named gestures as sequences of Beats. Pure data.

A Beat describes ONE atomic transition on up to three channels (head pose, antennas,
body yaw) plus how to get there (duration, interpolation method) and how long to hold.

Channel values:
    pose      — POSES key (str) | Pose | None = hold current
    antennas  — ANTENNAS key (str) | [L, R] list | None = hold current
    body_yaw  — float (radians) | None = hold current
    duration  — float (seconds) | None = auto from amplitude
    method    — InterpolationTechnique
    hold      — float (seconds) to sleep after arrival
"""

from collections import namedtuple

from reachy_mini.utils.interpolation import InterpolationTechnique

MIN_JERK = InterpolationTechnique.MIN_JERK
CARTOON = InterpolationTechnique.CARTOON
EASE_IN_OUT = InterpolationTechnique.EASE_IN_OUT
LINEAR = InterpolationTechnique.LINEAR


Beat = namedtuple(
    "Beat",
    "pose antennas body_yaw duration method hold",
    defaults=(None, None, None, None, MIN_JERK, 0.0),
)


# Gesture = list[Beat] | Callable[..., list[Beat]]
# Callable gestures are used for parameterized motion (e.g. orient(angle)).
# Static gestures are just lists.
GESTURES: dict[str, list[Beat]] = {

    # ── Head tilts ──────────────────────────────────────────
    "head_tilt_L": [
        Beat(pose="tilt_L", antennas="curious_L", duration=0.25, method=CARTOON, hold=0.8),
    ],
    "head_tilt_R": [
        Beat(pose="tilt_R", antennas="curious_R", duration=0.25, method=CARTOON, hold=0.8),
    ],
    "double_tilt": [
        Beat(pose="tilt_L", antennas="curious_L", duration=0.25, method=CARTOON, hold=0.5),
        Beat(pose="tilt_R", antennas="curious_R", duration=0.3,  method=CARTOON, hold=0.7),
    ],

    # ── Antenna-only gestures ──────────────────────────────
    "ear_flick_L": [
        Beat(antennas="flick_L", duration=0.12, method=CARTOON, hold=0.08),
        Beat(antennas="alert",   duration=0.18, method=MIN_JERK),
    ],
    "ear_flick_R": [
        Beat(antennas="flick_R", duration=0.12, method=CARTOON, hold=0.08),
        Beat(antennas="alert",   duration=0.18, method=MIN_JERK),
    ],
    "both_perk": [
        Beat(antennas="perked", duration=0.15, method=CARTOON, hold=0.4),
        Beat(antennas="alert",  duration=0.3,  method=MIN_JERK),
    ],

    # ── Soft, contented moves ──────────────────────────────
    "slow_blink": [
        Beat(pose="duck",   antennas="droop",   duration=0.25, method=EASE_IN_OUT, hold=0.6),
        Beat(pose="center", antennas="relaxed", duration=0.35, method=MIN_JERK),
    ],
    "settling_sigh": [
        Beat(pose="duck", antennas="droop", duration=0.4, method=EASE_IN_OUT, hold=1.2),
        Beat(pose="center", antennas="relaxed", duration=0.5, method=MIN_JERK),
    ],

    # ── Nods & emphasis ────────────────────────────────────
    "sharp_nod": [
        Beat(pose="nod_down", duration=0.15, method=CARTOON, hold=0.05),
        Beat(pose="nod_up",   duration=0.15, method=CARTOON, hold=0.05),
        Beat(pose="center",   duration=0.2,  method=MIN_JERK),
    ],
    "lean_in": [
        Beat(pose="lean_in", antennas="alert", duration=0.3, method=MIN_JERK, hold=0.6),
        Beat(pose="center",  antennas="alert", duration=0.35, method=MIN_JERK),
    ],
    "pull_back": [
        Beat(pose="pull_back", antennas="perked", duration=0.18, method=CARTOON, hold=0.3),
        Beat(pose="center",    antennas="alert",  duration=0.3,  method=MIN_JERK),
    ],

    # ── Alert / startled ──────────────────────────────────
    "alert_freeze": [
        Beat(pose="stretch_up", antennas="perked", duration=0.2, method=CARTOON, hold=1.2),
        Beat(pose="center",     antennas="relaxed", duration=0.4, method=MIN_JERK),
    ],
    "startled_recoil": [
        Beat(pose="recoil",     antennas="perked", duration=0.13, method=CARTOON, hold=0.3),
        Beat(pose="center",     antennas="alert",  duration=0.3,  method=MIN_JERK, hold=0.4),
        Beat(pose="center",     antennas="relaxed", duration=0.3, method=MIN_JERK),
    ],

    # ── Gaze shifts & look-aways ──────────────────────────
    "gaze_shift_L": [
        Beat(pose="gaze_L", antennas="alert", duration=0.3, method=MIN_JERK, hold=1.2),
        Beat(pose="center", antennas="relaxed", duration=0.4, method=MIN_JERK),
    ],
    "gaze_shift_R": [
        Beat(pose="gaze_R", antennas="alert", duration=0.3, method=MIN_JERK, hold=1.2),
        Beat(pose="center", antennas="relaxed", duration=0.4, method=MIN_JERK),
    ],
    "look_away_L": [
        Beat(pose="look_away_L", antennas="relaxed", duration=0.3, method=MIN_JERK, hold=1.5),
    ],
    "look_away_R": [
        Beat(pose="look_away_R", antennas="relaxed", duration=0.3, method=MIN_JERK, hold=1.5),
    ],

    # ── Curious peeks (lateral) ───────────────────────────
    "curious_peek_L": [
        Beat(pose="peek_L", antennas="curious_L", duration=0.22, method=CARTOON, hold=0.9),
        Beat(pose="center", antennas="relaxed",   duration=0.35, method=MIN_JERK),
    ],
    "curious_peek_R": [
        Beat(pose="peek_R", antennas="curious_R", duration=0.22, method=CARTOON, hold=0.9),
        Beat(pose="center", antennas="relaxed",   duration=0.35, method=MIN_JERK),
    ],

    # ── Weight shifts (body only) ─────────────────────────
    "weight_shift_L": [
        Beat(body_yaw=0.07, duration=0.5, method=MIN_JERK, hold=1.0),
        Beat(body_yaw=0.0,  duration=0.5, method=MIN_JERK),
    ],
    "weight_shift_R": [
        Beat(body_yaw=-0.07, duration=0.5, method=MIN_JERK, hold=1.0),
        Beat(body_yaw=0.0,   duration=0.5, method=MIN_JERK),
    ],

    # ── Quick idle tics ───────────────────────────────────
    "preen_beat": [
        Beat(antennas="flick_L", duration=0.1, method=CARTOON),
        Beat(antennas="flick_R", duration=0.1, method=CARTOON),
        Beat(antennas="alert",   duration=0.15, method=MIN_JERK),
    ],

    # ── Life gestures (rare, personality punctuation) ─────
    "yawn": [
        Beat(pose="look_up",   antennas="droop",   duration=0.4, method=MIN_JERK, hold=1.0),
        Beat(pose="center",    antennas="alert",   duration=0.25, method=CARTOON, hold=0.3),
        Beat(pose="center",    antennas="relaxed", duration=0.4, method=EASE_IN_OUT),
    ],
    "stretch": [
        Beat(pose="stretch_up", antennas="perked", body_yaw=0.1, duration=0.6, method=MIN_JERK, hold=1.5),
        Beat(pose="center",     antennas="relaxed", body_yaw=0.0, duration=0.6, method=MIN_JERK),
    ],
    "scratch": [
        Beat(pose="tilt_L", antennas="flick_L", duration=0.15, method=CARTOON, hold=0.1),
        Beat(pose="tilt_L", antennas="flick_R", duration=0.12, method=CARTOON, hold=0.1),
        Beat(pose="tilt_L", antennas="flick_L", duration=0.12, method=CARTOON, hold=0.15),
        Beat(pose="center", antennas="relaxed", duration=0.3,  method=MIN_JERK),
    ],
    "sneeze": [
        Beat(pose="nod_down", antennas="droop", duration=0.1, method=CARTOON),
        Beat(pose="pull_back", antennas="perked", duration=0.1, method=CARTOON, hold=0.2),
        Beat(pose="center", antennas="relaxed", duration=0.3, method=MIN_JERK),
    ],
    "shake_off": [
        Beat(pose=None, body_yaw=0.15, duration=0.1, method=CARTOON),
        Beat(pose=None, body_yaw=-0.15, duration=0.1, method=CARTOON),
        Beat(pose=None, body_yaw=0.1,  duration=0.08, method=CARTOON),
        Beat(pose=None, body_yaw=0.0,  duration=0.2, method=MIN_JERK),
    ],
    "self_groom_check": [
        Beat(pose="tilt_L", antennas="relaxed", duration=0.2, method=MIN_JERK, hold=0.4),
        Beat(pose="center", antennas="relaxed", duration=0.3, method=MIN_JERK),
    ],
    "look_up": [
        Beat(pose="look_up", antennas="relaxed", duration=0.4, method=MIN_JERK, hold=3.5),
        Beat(pose="center",  antennas="relaxed", duration=0.5, method=MIN_JERK),
    ],
    "measuring_bob": [
        Beat(pose="lean_in",  duration=0.15, method=CARTOON),
        Beat(pose="pull_back", duration=0.15, method=CARTOON),
        Beat(pose="lean_in",  duration=0.15, method=CARTOON),
        Beat(pose="center",   duration=0.25, method=MIN_JERK),
    ],
}


# ── Rarity tier assignment ─────────────────────────────────
# Controls how often each gesture can fire within its state's pool.
TIER: dict[str, str] = {
    # common: background aliveness
    "gaze_shift_L": "common", "gaze_shift_R": "common",
    "weight_shift_L": "common", "weight_shift_R": "common",
    "preen_beat": "common",
    "ear_flick_L": "common", "ear_flick_R": "common",

    # uncommon: definite but not surprising
    "head_tilt_L": "uncommon", "head_tilt_R": "uncommon",
    "double_tilt": "uncommon",
    "curious_peek_L": "uncommon", "curious_peek_R": "uncommon",
    "slow_blink": "uncommon",
    "both_perk": "uncommon",
    "lean_in": "uncommon",

    # rare: noticeable personality
    "settling_sigh": "rare",
    "look_up": "rare",
    "measuring_bob": "rare",
    "alert_freeze": "rare",
    "self_groom_check": "rare",

    # very rare: special moments
    "yawn": "very_rare",
    "stretch": "very_rare",
    "scratch": "very_rare",
    "sneeze": "very_rare",
    "shake_off": "very_rare",
    "startled_recoil": "very_rare",
    "pull_back": "very_rare",
    "look_away_L": "very_rare",  # these are used in thinking state mostly
    "look_away_R": "very_rare",
    "sharp_nod": "common",  # in speaking state
}


# ── State → gesture pool ───────────────────────────────────
# Each state samples from the gestures listed here, respecting TIER cooldowns.
IDLE_GESTURES = [
    "gaze_shift_L", "gaze_shift_R",
    "weight_shift_L", "weight_shift_R",
    "preen_beat",
    "head_tilt_L", "head_tilt_R",
    "double_tilt",
    "curious_peek_L", "curious_peek_R",
    "slow_blink",
    "both_perk",
    "settling_sigh", "look_up", "measuring_bob", "alert_freeze",
    "self_groom_check",
    "yawn", "stretch", "scratch", "sneeze", "shake_off",
    "startled_recoil",
]

LISTENING_GESTURES = [
    "ear_flick_L", "ear_flick_R",
    "head_tilt_L", "head_tilt_R",
    "lean_in",
]

THINKING_GESTURES = [
    "look_away_L", "look_away_R",
    "slow_blink",
]

SPEAKING_GESTURES = [
    "sharp_nod",
    "weight_shift_L", "weight_shift_R",
    "ear_flick_L", "ear_flick_R",
    "head_tilt_L", "head_tilt_R",
]


