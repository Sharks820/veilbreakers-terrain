"""Blender MCP socket server stub.

Provides the timer interval constants and BlenderMCPServer class used by
the addon to poll the command queue.
"""

from __future__ import annotations

TIMER_INTERVAL_MS: int = 10
TIMER_INTERVAL_S: float = 0.01


class BlenderMCPServer:
    """Minimal socket server stub for the Blender addon command queue."""

    def _process_commands(self) -> float:
        """Process pending MCP commands and return the timer poll interval.

        Returns
        -------
        float
            Poll interval in seconds (0.01 = 10 ms).
        """
        return 0.01
