"""zwlr_virtual_pointer_v1 client — the pywayland-postmortem discipline.

Port of the validated uxlib ``pointer.py`` core (laptop rig, 8/0 twice on
ai-legion): synthetic input over the wlroots virtual-pointer protocol, no
root, no uinput group.

Teardown is single-owner and deterministic (coredump 3407471 et al.):
pywayland arms ``ffi.gc(ptr, wl_proxy_destroy)`` on every proxy, so a
pointer dropped without ``close()`` lets GC finalizers race
``wl_display_disconnect`` — when the display's finalizer wins, later proxy
finalizers destroy against the freed wl_map and the process takes SIGSEGV
inside ``wl_map_insert_at``. Therefore:

- ``close()`` destroys every proxy in creation order (pointer → manager →
  registry → display.disconnect), idempotently;
- ``__del__`` routes the forgot-to-close path through the same sequence;
- operational rule: a FRESH pointer per use, explicit ``close()`` before
  drop, never share one pywayland connection across uses.

The Wayland object graph is injected (``session_factory``): unit tests
drive fake proxies and assert the destroy order; the default factory binds
a real session via pywayland (``ux`` extra + the zwlr protocol module —
see ``pywayland_session``).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Protocol

__all__ = [
    "BTN_LEFT",
    "BTN_MIDDLE",
    "BTN_RIGHT",
    "ClickProxy",
    "PointerSession",
    "SessionFactory",
    "VirtualPointer",
    "pywayland_session",
]

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

_PRESSED = 1
_RELEASED = 0

_BUTTON_SETTLE_S = 0.05


class ClickProxy(Protocol):
    """The zwlr_virtual_pointer_v1 proxy surface this client uses."""

    def motion_absolute(
        self, time_ms: int, x: int, y: int, screen_w: int, screen_h: int
    ) -> None: ...

    def button(self, time_ms: int, button: int, state: int) -> None: ...

    def frame(self) -> None: ...


class PointerSession(Protocol):
    """One owned Wayland session: display, registry, manager, pointer.

    Implementations expose each object's destroy/disconnect so
    ``VirtualPointer.close`` can drive the exact creation-order teardown —
    this is the interface the postmortem's fake-proxy tests assert on.
    """

    @property
    def pointer(self) -> ClickProxy: ...

    def flush(self) -> None:
        """Flush the display connection."""
        ...

    def destroy_pointer(self) -> None: ...

    def destroy_manager(self) -> None: ...

    def destroy_registry(self) -> None: ...

    def disconnect_display(self) -> None: ...


SessionFactory = Callable[[], PointerSession]


class VirtualPointer:
    """A synthetic Wayland pointer bound to one session, torn down in order."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._closed = False
        factory = session_factory if session_factory is not None else pywayland_session
        self._session: PointerSession = factory()

    def move_to(self, x: int, y: int, screen_w: int, screen_h: int) -> None:
        pointer = self._session.pointer
        pointer.motion_absolute(self._now_ms(), x, y, screen_w, screen_h)
        pointer.frame()
        self._session.flush()

    def click(self, button: int = BTN_LEFT) -> None:
        pointer = self._session.pointer
        pointer.button(self._now_ms(), button, _PRESSED)
        pointer.frame()
        self._session.flush()
        time.sleep(_BUTTON_SETTLE_S)
        pointer.button(self._now_ms(), button, _RELEASED)
        pointer.frame()
        self._session.flush()

    def click_at(
        self, x: int, y: int, screen_w: int, screen_h: int, button: int = BTN_LEFT
    ) -> None:
        self.move_to(x, y, screen_w, screen_h)
        time.sleep(_BUTTON_SETTLE_S)
        self.click(button)

    def close(self) -> None:
        """Destroy every object in creation order, then disconnect — idempotently.

        pointer → manager → registry → display.disconnect: no proxy may
        outlive its factory, and no cffi finalizer stays armed past the
        display teardown.
        """
        if self._closed:
            return
        self._closed = True
        self._session.destroy_pointer()
        self._session.destroy_manager()
        self._session.destroy_registry()
        self._session.disconnect_display()

    def __del__(self) -> None:
        # Forgot-to-close safety net: same deterministic teardown, never
        # propagating (even logging can fail at interpreter teardown).
        with contextlib.suppress(Exception):
            self.close()

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000) & 0xFFFFFFFF


def pywayland_session() -> PointerSession:
    """Bind a real session: display → registry → manager → pointer.

    Rig integration point: needs the ``ux`` extra (pywayland) AND the
    generated zwlr_virtual_pointer_unstable_v1 protocol module. The
    validated bindings live in omarchy-cashu's uxlib (tests/ux/uxlib/
    generated); vendoring them into tollgate-lab is the follow-up that
    lands with the laptop-local rig. Until then this raises with the
    exact missing piece — the VM rig clicks via ydotool inside the guest.
    """
    try:
        import pywayland  # type: ignore[import-not-found]  # noqa: F401 — probe for the extra

        del pywayland
    except ImportError as exc:
        raise ImportError(
            "pywayland is not installed; install the 'ux' extra "
            "(pip install 'tollgate-lab[ux]') to use the virtual-pointer backend"
        ) from exc
    raise ImportError(
        "the zwlr_virtual_pointer_unstable_v1 protocol module is not vendored yet — "
        "port uxlib's generated binding with the laptop-local rig (see module docstring); "
        "the VM rig uses the ydotool click backend"
    )
