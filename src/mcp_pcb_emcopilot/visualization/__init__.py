"""PCB design visualization — pure-Python SVG rendering.

Provides board layout, stackup cross-section, net highlight, and annotation
overlays.  Zero external dependencies (SVG is just XML text).
"""

from .annotator import Annotator
from .board_renderer import BoardRenderer
from .stackup_renderer import StackupRenderer

__all__ = ["BoardRenderer", "StackupRenderer", "Annotator"]
