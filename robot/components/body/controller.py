"""BodyController: drives the Reachy Mini based on pipeline state.

Architecture:
    Pose    — head-only state (yaw/pitch/roll + x/y/z) — in poses.py
    Beat    — one atomic move: Pose + antennas + body_yaw + timing + method
    Gesture — named list of Beats — in gestures.py
    Pool    — rarity-tiered scheduler — in scheduler.py
    State   — picks from a pool, plays gestures, handles interruption

Public methods (safe for notebook / standalone test):
    play_beat(beat)             — execute one Beat
    play_gesture(name, *args)   — execute a named gesture
    orient(yaw_deg, pitch_deg)  — body-aware blended turn
    return_to_center()          — go to CENTER pose
    list_gestures(), list_poses(), list_antennas() — introspection

In-pipeline use: pass a state_bus, call start()/stop(). Animators react to state
changes via _watch_state; gesture/pose methods are interruptible via _alive().
"""

import logging
import random
import threading
from queue import Empty

from robot.core import Bus, Component, StateChange

from .gestures import (
    GESTURES, TIER, Beat, MIN_JERK,
    IDLE_GESTURES, LISTENING_GESTURES, THINKING_GESTURES, SPEAKING_GESTURES,
)
from .helpers import make_pose, rand_signed, min_duration, split_body_head
from .poses import POSES, ANTENNAS, Pose
from .scheduler import GesturePool

logger = logging.getLogger(__name__)


class BodyController(Component):
    def __init__(self, mini, state_bus: Bus | None = None):
        super().__init__("body")
        self.mini = mini
        self._state_bus = state_bus
        self._state_q = state_bus.subscribe() if state_bus is not None else None
        self._current_state = "idle"
        self._state_changed = threading.Event()

        self._pools = {
            "idle":      GesturePool(IDLE_GESTURES, TIER),
            "listening": GesturePool(LISTENING_GESTURES, TIER),
            "thinking":  GesturePool(THINKING_GESTURES, TIER),
            "speaking":  GesturePool(SPEAKING_GESTURES, TIER),
        }

    # ── Introspection ─────────────────────────────────────
    def list_gestures(self) -> list[str]:
        return list(GESTURES.keys())

    def list_poses(self) -> list[str]:
        return list(POSES.keys())

    def list_antennas(self) -> list[str]:
        return list(ANTENNAS.keys())

    # ── Motion runner ─────────────────────────────────────
    def play_beat(self, beat: Beat):
        """Execute one Beat. Respects _alive() for interruption."""
        if not self._alive():
            return

        pose_arg = self._resolve_pose(beat.pose)
        antennas_arg = self._resolve_antennas(beat.antennas)

        # Duration: explicit > auto-from-amplitude > floor
        if beat.duration is not None:
            duration = beat.duration
        else:
            amp_deg = _pose_amp_deg(pose_arg) if pose_arg is not None else 0
            amp_m = _pose_amp_m(pose_arg) if pose_arg is not None else 0
            duration = min_duration(amp_deg, amp_m)

        head_arg = make_pose(*pose_arg) if pose_arg is not None else None

        try:
            self.mini.goto_target(
                head=head_arg,
                antennas=antennas_arg,
                body_yaw=beat.body_yaw,
                duration=duration,
                method=beat.method or MIN_JERK,
            )
        except Exception:
            logger.exception("[body] goto_target failed")

        if beat.hold > 0:
            self._sleep(beat.hold)

    def play_gesture(self, name: str, *args) -> bool:
        """Play a named gesture from GESTURES. Returns False if interrupted."""
        if name not in GESTURES:
            raise KeyError(f"Unknown gesture: {name}. Options: {list(GESTURES.keys())}")
        beats = GESTURES[name]
        if callable(beats):
            beats = beats(*args)
        for beat in beats:
            if not self._alive():
                return False
            self.play_beat(beat)
        return True

    def orient(self, target_yaw_deg: float, pitch_deg: float = 0):
        """Turn to face a target yaw (degrees, world frame).

        One coordinated SDK call: head target is the full world angle, body_yaw
        is the body's share (0 for small turns, up to 50% for large ones). The
        solver interpolates both channels together. A natural "head leads" feel
        emerges because the head has a larger angle to cover in the same time.
        """
        _, body_yaw_rad, _ = split_body_head(target_yaw_deg)
        abs_yaw = abs(target_yaw_deg)
        duration = max(0.3, abs_yaw * 0.018)
        try:
            self.mini.goto_target(
                head=make_pose(yaw=target_yaw_deg, pitch=pitch_deg),
                body_yaw=body_yaw_rad,
                duration=duration,
                method=MIN_JERK,
            )
        except Exception:
            logger.exception("[body] orient failed")

    def return_to_center(self, duration: float = 0.4):
        """Reset head + antennas + body to neutral."""
        try:
            self.mini.goto_target(
                head=make_pose(*POSES["center"]),
                antennas=ANTENNAS["relaxed"],
                body_yaw=0.0,
                duration=duration,
                method=MIN_JERK,
            )
        except Exception:
            logger.exception("[body] return_to_center failed")

    # ── Pose / antenna resolution ─────────────────────────
    def _resolve_pose(self, spec) -> Pose | None:
        if spec is None:
            return None
        if isinstance(spec, str):
            if spec not in POSES:
                raise KeyError(f"Unknown pose: {spec}. Options: {list(POSES.keys())}")
            return POSES[spec]
        if isinstance(spec, Pose):
            return spec
        raise TypeError(f"pose must be str or Pose, got {type(spec).__name__}")

    def _resolve_antennas(self, spec) -> list[float] | None:
        if spec is None:
            return None
        if isinstance(spec, str):
            if spec not in ANTENNAS:
                raise KeyError(f"Unknown antennas: {spec}. Options: {list(ANTENNAS.keys())}")
            return list(ANTENNAS[spec])
        if isinstance(spec, (list, tuple)) and len(spec) == 2:
            return list(spec)
        raise TypeError(f"antennas must be str or [L, R], got {spec!r}")

    # ── Component lifecycle (used in pipeline) ────────────
    def run(self):
        if self._state_q is None:
            logger.warning("[body] started without state_bus — nothing to drive")
            return

        watcher = threading.Thread(target=self._watch_state, daemon=True, name="body-watch")
        watcher.start()

        self.return_to_center()

        while self.running:
            self._state_changed.clear()
            state = self._current_state
            animator = self._animator_for(state)
            try:
                animator()
            except Exception:
                logger.exception(f"[body] animator {state} crashed")
                if self._sleep(0.5):
                    continue

    def _watch_state(self):
        while self.running:
            try:
                event = self._state_q.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(event, StateChange) and event.state != self._current_state:
                old = self._current_state
                self._current_state = event.state
                self._state_changed.set()
                try:
                    self.mini.cancel_move()
                except Exception:
                    pass
                logger.debug(f"[body] {old} → {event.state}")

    # ── Animators ─────────────────────────────────────────
    def _animator_for(self, state: str):
        return {
            "idle":      self._animate_idle,
            "listening": self._animate_listening,
            "thinking":  self._animate_thinking,
            "speaking":  self._animate_speaking,
        }.get(state, self._animate_idle)

    def _animate_idle(self):
        pool = self._pools["idle"]
        # Settle to a clean baseline on entry — so any in-flight gesture
        # (mid-flick antennas, partial tilt) resolves smoothly to neutral.
        try:
            self.mini.goto_target(
                head=make_pose(*POSES["center"]),
                antennas=ANTENNAS["relaxed"],
                duration=0.5, method=MIN_JERK, body_yaw=0.0,
            )
        except Exception:
            logger.exception("[body] idle entry failed")

        while self._alive():
            if self._sleep(random.uniform(4.0, 9.0)):
                return
            name = pool.pick()
            if name is None or not self._alive():
                continue
            pool.mark_fired(name)
            self.play_gesture(name)

    def _animate_listening(self):
        pool = self._pools["listening"]
        # Open with lean-in pose (one-off, not a full gesture)
        try:
            self.mini.goto_target(
                head=make_pose(*POSES["lean_in"]),
                antennas=ANTENNAS["alert"],
                duration=0.3, method=MIN_JERK,
            )
        except Exception:
            logger.exception("[body] listening entry failed")

        while self._alive():
            if self._sleep(random.uniform(2.0, 4.5)):
                return
            name = pool.pick()
            if name is None or not self._alive():
                continue
            pool.mark_fired(name)
            self.play_gesture(name)

    def _animate_thinking(self):
        pool = self._pools["thinking"]
        # Open with a look-away (random direction)
        first = random.choice(["look_away_L", "look_away_R"])
        pool.mark_fired(first)
        self.play_gesture(first)

        while self._alive():
            if self._sleep(random.uniform(2.5, 5.0)):
                return
            # Small "almost had it" eye-dart: 3-5° yaw shift, fast
            yaw = rand_signed(3, 5)
            try:
                self.mini.goto_target(
                    head=make_pose(yaw=yaw, pitch=-6),
                    duration=0.2, method=MIN_JERK, body_yaw=None,
                )
            except Exception:
                logger.exception("[body] thinking dart failed")

    def _animate_speaking(self):
        pool = self._pools["speaking"]
        try:
            self.mini.goto_target(
                head=make_pose(*POSES["center"]),
                antennas=ANTENNAS["relaxed"],
                duration=0.3, method=MIN_JERK, body_yaw=0.0,
            )
        except Exception:
            logger.exception("[body] speaking entry failed")

        while self._alive():
            roll = random.random()
            if roll < 0.4:
                # Stillness
                if self._sleep(random.uniform(3.0, 5.5)):
                    return
                continue
            if self._sleep(random.uniform(1.5, 3.5)):
                return
            name = pool.pick()
            if name is None or not self._alive():
                continue
            pool.mark_fired(name)
            self.play_gesture(name)

    # ── Interruption helpers ──────────────────────────────
    def _alive(self) -> bool:
        """True if we should keep running in the current animator."""
        return self.running and not self._state_changed.is_set()

    def _sleep(self, duration: float) -> bool:
        """Interruptible sleep. Returns True if interrupted by state change."""
        return self._state_changed.wait(timeout=duration)

    def stop(self):
        super().stop()
        try:
            self.mini.cancel_move()
            self.return_to_center(duration=0.8)
        except Exception:
            pass


# ── Helpers for auto-duration from pose amplitude ────────────
def _pose_amp_deg(pose: Pose) -> float:
    return max(abs(pose.yaw), abs(pose.pitch), abs(pose.roll))


def _pose_amp_m(pose: Pose) -> float:
    return max(abs(pose.x), abs(pose.y), abs(pose.z))
