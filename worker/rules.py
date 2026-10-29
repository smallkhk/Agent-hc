"""Turns per-sample pass/fail into warning and violation events with grace periods."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    type: str
    severity: str  # info | warning | violation
    score: float | None = None


class EscalatingRule:
    """Continuous failure for warn_sec → one warning; for violation_sec → one violation.

    A pass resets the episode. Either step can be disabled with None.
    Thresholds are plain attributes so a /handcam config change applies to running sessions.
    """

    def __init__(self, warn_sec: float | None, violation_sec: float | None) -> None:
        self.warn_sec = warn_sec
        self.violation_sec = violation_sec
        self.failing_since: float | None = None
        self.warned = False
        self.violated = False

    def update(self, failing: bool, now: float, event_type: str, score: float | None = None) -> list[Event]:
        if not failing:
            self.reset()
            return []
        if self.failing_since is None:
            self.failing_since = now
        elapsed = now - self.failing_since
        events: list[Event] = []
        if self.violation_sec is not None and not self.violated and elapsed >= self.violation_sec:
            self.violated = self.warned = True
            events.append(Event(event_type, "violation", score))
        elif self.warn_sec is not None and not self.warned and elapsed >= self.warn_sec:
            self.warned = True
            events.append(Event(event_type, "warning", score))
        return events

    def reset(self) -> None:
        self.failing_since = None
        self.warned = self.violated = False

    def elapsed(self, now: float) -> float:
        return 0.0 if self.failing_since is None else now - self.failing_since
