"""Runtime configuration for the thumbnail engine.

The engine is framework-independent, so it does not read application settings
directly. The embedding application sets these values once at startup; QuickBBS
does so from ``thumbnails.apps.ThumbnailsConfig.ready()``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineConfig:
    """Tunable engine behavior that the embedding application controls.

    Attributes:
        macintosh_optimizations: Whether the macOS-accelerated backends
            (Core Image, AVFoundation, PDFKit) may be selected automatically.
            Only the auto-selecting backend names ("auto", "corevideo", "pdf")
            consult this; an explicit request such as "coreimage" is never
            gated by it. Defaults to True so that standalone use gets the
            fastest available backend without configuration.
    """

    macintosh_optimizations: bool = True


config = EngineConfig()
