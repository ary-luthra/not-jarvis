"""Gesture pool with rarity-tier cooldowns.

Each tier has a minimum cooldown. A gesture can only be picked again after
at least `min_cooldown[tier]` seconds have passed since it last fired. This
gives rare gestures their special quality — you can't have a yawn every 10s.
"""

import random
import time


# Per-tier cooldown (seconds). Gesture can fire again after min_cooldown has elapsed
# since its last firing. max_cooldown is advisory — drives the probability boost
# as time approaches it.
RARITY_TIERS: dict[str, tuple[float, float]] = {
    "common":    (3.0,   12.0),
    "uncommon":  (15.0,  40.0),
    "rare":      (60.0,  150.0),
    "very_rare": (180.0, 360.0),
}


class GesturePool:
    """Weighted picker with per-tier cooldowns.

    Usage:
        pool = GesturePool(["yawn", "ear_flick_L", ...], tier_map={"yawn": "very_rare", ...})
        name = pool.pick(time.time())   # may return None if nothing is eligible
    """

    def __init__(self, names: list[str], tier_map: dict[str, str]):
        self.names = list(names)
        self.tier_map = tier_map
        self._last_fired: dict[str, float] = {n: 0.0 for n in self.names}

    def pick(self, now: float | None = None) -> str | None:
        """Return an eligible gesture name, weighted by time-since-last-fired. None if nothing eligible."""
        now = now if now is not None else time.time()
        eligible: list[tuple[str, float]] = []

        for name in self.names:
            tier = self.tier_map.get(name, "common")
            min_cd, max_cd = RARITY_TIERS.get(tier, (3.0, 12.0))
            since = now - self._last_fired[name]
            if since < min_cd:
                continue
            # Weight grows from 1.0 at min_cd to ~3.0 at max_cd (and beyond).
            # Rare gestures that haven't fired in a while get amplified.
            progress = (since - min_cd) / max(0.01, max_cd - min_cd)
            weight = 1.0 + 2.0 * min(1.0, progress)
            eligible.append((name, weight))

        if not eligible:
            return None

        names, weights = zip(*eligible)
        return random.choices(names, weights=weights, k=1)[0]

    def mark_fired(self, name: str, now: float | None = None):
        """Record that a gesture just fired."""
        self._last_fired[name] = now if now is not None else time.time()

    def reset(self):
        """Clear all cooldowns (e.g., on state re-entry if you want fresh picks)."""
        self._last_fired = {n: 0.0 for n in self.names}
