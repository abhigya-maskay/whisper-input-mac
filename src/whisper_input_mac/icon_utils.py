import logging
from Cocoa import NSImage, NSBezierPath, NSColor, NSSize

logger = logging.getLogger(__name__)


def create_idle_icon(size: float = 18.0) -> NSImage:
    """Create idle state icon: circle with mic glyph."""
    image = NSImage.alloc().initWithSize_(NSSize(size, size))
    image.lockFocus()

    # Draw circle
    circle = NSBezierPath.bezierPathWithOvalInRect_(
        ((0, 0), (size, size))
    )
    NSColor.blackColor().setStroke()
    circle.setLineWidth_(1.5)
    circle.stroke()

    # Draw simplified mic glyph (vertical line with dot)
    mic_path = NSBezierPath.alloc().init()
    mid = size / 2
    mic_path.moveToPoint_((mid, size * 0.3))
    mic_path.lineToPoint_((mid, size * 0.65))
    mic_path.setLineWidth_(1.5)
    NSColor.blackColor().setStroke()
    mic_path.stroke()

    # Dot for mic head
    dot = NSBezierPath.bezierPathWithOvalInRect_(
        ((mid - 2, size * 0.2), (4, 4))
    )
    NSColor.blackColor().setFill()
    dot.fill()

    image.unlockFocus()
    image.setTemplate_(True)
    logger.debug("Created idle icon")
    return image


def create_recording_icon(size: float = 18.0) -> NSImage:
    """Create recording state icon: solid waveform block."""
    image = NSImage.alloc().initWithSize_(NSSize(size, size))
    image.lockFocus()

    # Draw waveform-like bars
    bar_width = 2.0
    bar_height_multiplier = [0.5, 0.8, 1.0, 0.8, 0.5]
    spacing = (size - len(bar_height_multiplier) * bar_width) / (len(bar_height_multiplier) + 1)

    NSColor.blackColor().setFill()
    for i, multiplier in enumerate(bar_height_multiplier):
        x = spacing + i * (bar_width + spacing)
        height = size * multiplier * 0.7
        y = (size - height) / 2

        bar = NSBezierPath.bezierPathWithRect_(((x, y), (bar_width, height)))
        bar.fill()

    image.unlockFocus()
    image.setTemplate_(True)
    logger.debug("Created recording icon")
    return image


def create_busy_icon(size: float = 18.0) -> NSImage:
    """Create busy state icon: stroked ring."""
    image = NSImage.alloc().initWithSize_(NSSize(size, size))
    image.lockFocus()

    # Draw ring (circle outline)
    margin = 3.0
    ring_rect = ((margin, margin), (size - 2 * margin, size - 2 * margin))
    ring = NSBezierPath.bezierPathWithOvalInRect_(ring_rect)
    ring.setLineWidth_(2.0)
    NSColor.blackColor().setStroke()
    ring.stroke()

    image.unlockFocus()
    image.setTemplate_(True)
    logger.debug("Created busy icon")
    return image
