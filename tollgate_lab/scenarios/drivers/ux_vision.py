"""Template vision — OpenCV match over guest screencopy grabs.

Port of the validated uxlib ``vfind`` (Sikuli-style TM_CCOEFF_NORMED
matching, center-of-best-match, threshold gate, ambiguity refusal) plus a
``GuestVision`` service that pulls screenshots over an exec channel (grim
inside the guest, cat'd back byte-clean) and retries until a template is
visible — the assertion IS the wait.

``cv2`` is imported lazily inside ``find``: the module stays importable on
hosts without OpenCV (unit tests inject their own vision fakes), and the
real matcher only needs the ``ux`` extra on the rig.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tollgate_lab.scenarios.drivers.ux_channel import (
    DEFAULT_GUEST_ENV,
    ExecChannel,
    grim_pull_command,
    wait_until,
)

__all__ = [
    "AmbiguousMatch",
    "GuestVision",
    "Match",
    "TemplateNotFound",
    "TemplateVision",
    "find",
]

DEFAULT_THRESHOLD = 0.80
DEFAULT_AMBIGUITY_MARGIN = 0.05

Region = tuple[int, int, int, int]  # x1, y1, x2, y2

_shot_counter = itertools.count(1)


@dataclass(frozen=True)
class Match:
    """A located UI element: center coordinates + match confidence."""

    x: int
    y: int
    confidence: float


# Names are ported verbatim from the validated uxlib vfind (Sikuli-style
# assertion vocabulary) — renaming would break parity with the reference.
class AmbiguousMatch(AssertionError):  # noqa: N818
    """Two candidates matched too closely to pick one — refuse to guess."""

    def __init__(self, template: str, best: Match, runner_up: Match, margin: float) -> None:
        super().__init__(
            f"template {template!r} is ambiguous: best {best.confidence:.3f} at "
            f"({best.x},{best.y}) vs runner-up {runner_up.confidence:.3f} at "
            f"({runner_up.x},{runner_up.y}); gap {best.confidence - runner_up.confidence:.3f} "
            f"< margin {margin:.3f} — refuse to guess"
        )
        self.template = template
        self.best = best
        self.runner_up = runner_up


class TemplateNotFound(AssertionError):  # noqa: N818 — ported name, see AmbiguousMatch
    """Raised when a template does not match the screenshot well enough."""

    def __init__(self, template: str, best: Match | None, threshold: float) -> None:
        got = f"best={best.confidence:.3f} at ({best.x},{best.y})" if best else "no match"
        super().__init__(f"template {template!r} not found (threshold {threshold:.2f}, {got})")
        self.template = template
        self.best = best
        self.threshold = threshold


def find(
    screenshot: Path | str,
    template: Path | str,
    threshold: float = DEFAULT_THRESHOLD,
    region: Region | None = None,
    margin: float = DEFAULT_AMBIGUITY_MARGIN,
) -> Match | None:
    """Best match's center if confidence >= threshold, else None.

    ``region`` crops the search first (x1, y1, x2, y2); returned
    coordinates are always full-screenshot coordinates. ``margin`` is the
    required confidence gap to the runner-up outside the best's
    neighborhood — two identical-looking widgets within the margin raise
    AmbiguousMatch instead of clicking one of them.
    """
    import cv2  # type: ignore[import-not-found]  # lazy: the ux extra provides it on the rig

    screen = cv2.imread(str(screenshot), cv2.IMREAD_COLOR)
    tmpl = cv2.imread(str(template), cv2.IMREAD_COLOR)
    if screen is None:
        raise FileNotFoundError(f"cannot read screenshot {screenshot}")
    if tmpl is None:
        raise FileNotFoundError(f"cannot read template {template}")
    off_x = off_y = 0
    if region is not None:
        x1, y1, x2, y2 = region
        off_x, off_y = x1, y1
        screen = screen[y1:y2, x1:x2]
    th, tw = tmpl.shape[:2]
    if th >= screen.shape[0] or tw >= screen.shape[1]:
        return None
    result = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    best = Match(
        x=int(max_loc[0] + tw // 2 + off_x),
        y=int(max_loc[1] + th // 2 + off_y),
        confidence=float(max_val),
    )
    if margin > 0.0:
        suppressed = result.copy()
        sy0 = max(0, max_loc[1] - th)
        sy1 = min(suppressed.shape[0], max_loc[1] + 2 * th)
        sx0 = max(0, max_loc[0] - tw)
        sx1 = min(suppressed.shape[1], max_loc[0] + 2 * tw)
        suppressed[sy0:sy1, sx0:sx1] = -1.0
        _, second_val, _, second_loc = cv2.minMaxLoc(suppressed)
        if max_val - second_val < margin:
            runner = Match(
                x=int(second_loc[0] + tw // 2 + off_x),
                y=int(second_loc[1] + th // 2 + off_y),
                confidence=float(second_val),
            )
            raise AmbiguousMatch(str(template), best, runner, margin)
    return best


class TemplateVision(Protocol):
    """Retrying visibility of a named template on the client's screen."""

    def wait_visible(self, template: str, *, timeout_s: float = 10.0) -> Match:
        """Block until the template is visible; raise with evidence."""
        ...


class GuestVision:
    """TemplateVision over grim-in-guest pulls + local cv2 matching.

    ``park`` (optional) moves the guest cursor off-panel before each grab
    — the cursor occludes templates (vm.py parks at a corner before grim).
    """

    def __init__(
        self,
        exec_channel: ExecChannel,
        templates_dir: Path | str,
        *,
        guest_env: str = DEFAULT_GUEST_ENV,
        shot_dir: Path | str = "/tmp/tollgate-lab-ux",
        threshold: float = DEFAULT_THRESHOLD,
        park: Callable[[], None] | None = None,
    ) -> None:
        self._exec = exec_channel
        self._templates = Path(templates_dir)
        self._guest_env = guest_env
        self._shot_dir = Path(shot_dir)
        self._threshold = threshold
        self._park = park

    def screenshot(self) -> Path:
        if self._park is not None:
            self._park()
        self._shot_dir.mkdir(parents=True, exist_ok=True)
        dest = self._shot_dir / f"shot-{next(_shot_counter):03d}.png"
        data = self._exec.run_bytes(grim_pull_command(self._guest_env))
        dest.write_bytes(data)
        if dest.stat().st_size < 1000:
            raise RuntimeError(f"guest screenshot too small ({dest.stat().st_size}B)")
        return dest

    def find(self, template: str, shot: Path | None = None) -> Match | None:
        photo = shot or self.screenshot()
        return find(photo, self._templates / template, self._threshold)

    def wait_visible(self, template: str, *, timeout_s: float = 10.0) -> Match:
        def probe() -> Match | None:
            return self.find(template)

        def evidence() -> str:
            shot = self.screenshot()
            loose = find(shot, self._templates / template, 0.0, margin=0.0)
            hint = (
                f"best {loose.confidence:.3f} at ({loose.x},{loose.y})"
                if loose
                else "no candidate anywhere"
            )
            return f"{template}: {hint}; last screenshot {shot}"

        return wait_until(
            probe, timeout_s=timeout_s, describe=f"{template} visible in guest", evidence=evidence
        )
