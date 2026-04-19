"""Blender MCP socket server — command queue dispatch.

Provides the timer interval constants and :class:`BlenderMCPServer` class used
by the Blender addon to poll a pending command queue and route each command
through the terrain package's ``COMMAND_HANDLERS`` dispatch table.

Design rules
------------
* **No bpy import at module scope.** This file must stay importable outside
  Blender (tests, CI, headless tooling). ``COMMAND_HANDLERS`` is also
  bpy-free at collection time because ``veilbreakers_terrain.handlers``
  registers each handler via ``importlib`` inside a ``try/except``.
* **Stateless dispatch.** Each call to :meth:`execute_command` is
  independent; the queue state is a plain list that the addon owns.
* **Fail-soft on unknown commands.** Rather than raising, the server returns
  an error dict so the Blender side can log + surface it to the UI.

Public surface
--------------
* ``TIMER_INTERVAL_MS`` / ``TIMER_INTERVAL_S`` — timer poll intervals.
* :class:`BlenderMCPServer` — the server with:
    - :meth:`execute_command` (the one callers should use)
    - :meth:`enqueue` / :meth:`_process_commands` (addon-facing polling API)

Usage from the addon
--------------------
    server = BlenderMCPServer()
    bpy.app.timers.register(server._process_commands, persistent=True)
    # ...later, when a request arrives over the MCP socket:
    server.enqueue({"command": "terrain_generate_cave", "params": {...}})
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

TIMER_INTERVAL_MS: int = 10
TIMER_INTERVAL_S: float = 0.01


class BlenderMCPServer:
    """Minimal socket server with a real COMMAND_HANDLERS dispatcher.

    The server owns a FIFO queue of pending command dicts and a parallel
    list of result dicts. The addon registers :meth:`_process_commands` as
    a ``bpy.app.timers`` callback; the timer drains the queue on the main
    thread (Blender's bpy API is not thread-safe off the main thread).
    """

    def __init__(self, handlers: Optional[Dict[str, Callable]] = None) -> None:
        """Create a new server.

        Parameters
        ----------
        handlers:
            Optional explicit dispatch table. When ``None`` (default) the
            server resolves ``veilbreakers_terrain.handlers.COMMAND_HANDLERS``
            lazily on first use — keeping imports clean at module-load time.
        """
        self._handlers: Optional[Dict[str, Callable]] = handlers
        self._queue: List[Dict[str, Any]] = []
        self._results: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Handler table access
    # ------------------------------------------------------------------
    def _resolve_handlers(self) -> Dict[str, Callable]:
        """Return the active dispatch table, importing lazily if needed."""
        if self._handlers is not None:
            return self._handlers
        # Lazy import so this module stays importable without the rest of
        # the package being eagerly wired up.
        from veilbreakers_terrain.handlers import COMMAND_HANDLERS
        self._handlers = COMMAND_HANDLERS
        return self._handlers

    # ------------------------------------------------------------------
    # Queue API (addon-facing)
    # ------------------------------------------------------------------
    def enqueue(self, request: Dict[str, Any]) -> None:
        """Append a request to the pending queue.

        Expected request shape::

            {"command": "<handler_key>", "params": {...}}

        The addon socket handler calls this when a new MCP command arrives.
        """
        if not isinstance(request, dict):
            raise TypeError(f"enqueue expects a dict, got {type(request).__name__}")
        self._queue.append(request)

    def drain_results(self) -> List[Dict[str, Any]]:
        """Pop and return all currently collected results."""
        out = self._results
        self._results = []
        return out

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def execute_command(
        self, command: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Dispatch one command and return a structured result dict.

        Parameters
        ----------
        command:
            Key into ``COMMAND_HANDLERS`` (e.g. ``"terrain_generate_cave"``).
        params:
            Handler kwargs. ``None`` is treated as ``{}``.

        Returns
        -------
        dict
            On success::

                {"status": "ok", "command": command, "result": <handler_return>}

            On unknown command::

                {"status": "error", "error": "unknown_command", "command": command}

            On handler exception::

                {"status": "error", "error": "handler_exception",
                 "exception_type": "ValueError", "message": "..."}
        """
        if params is None:
            params = {}
        handlers = self._resolve_handlers()
        fn = handlers.get(command)
        if fn is None:
            logger.warning("BlenderMCPServer: unknown command %r", command)
            return {
                "status": "error",
                "error": "unknown_command",
                "command": command,
            }
        try:
            result = fn(params)
        except Exception as exc:  # noqa: BLE001 — dispatch boundary
            logger.exception("BlenderMCPServer: handler %r raised", command)
            return {
                "status": "error",
                "error": "handler_exception",
                "command": command,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        return {"status": "ok", "command": command, "result": result}

    # ------------------------------------------------------------------
    # Timer callback
    # ------------------------------------------------------------------
    def _process_commands(self) -> float:
        """Drain the pending queue and return the timer poll interval.

        Blender's ``bpy.app.timers`` expects the callback to return either
        ``None`` (stop) or ``float`` seconds-until-next-poll. We always
        return :data:`TIMER_INTERVAL_S` (0.01 = 10 ms) so the poll runs
        every 10 ms until the addon explicitly unregisters the timer.
        """
        while self._queue:
            request = self._queue.pop(0)
            command = request.get("command", "")
            params = request.get("params", {}) or {}
            self._results.append(self.execute_command(command, params))
        # 0.01 seconds = 10 ms poll interval. See TIMER_INTERVAL_S.
        return TIMER_INTERVAL_S


__all__ = [
    "BlenderMCPServer",
    "TIMER_INTERVAL_MS",
    "TIMER_INTERVAL_S",
]
