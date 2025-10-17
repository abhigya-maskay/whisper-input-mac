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


def add_warning_badge(icon: NSImage, size: float = 18.0) -> NSImage:
    """
    Add a red warning badge to an icon.

    Args:
        icon: Base icon to add badge to
        size: Size of the icon (default 18.0)

    Returns:
        New NSImage with red badge overlay
    """
    # Create a new image for the composite
    badged_image = NSImage.alloc().initWithSize_(NSSize(size, size))
    badged_image.lockFocus()

    # Draw the original icon
    icon.drawInRect_fromRect_operation_fraction_(
        ((0, 0), (size, size)),
        ((0, 0), icon.size()),
        2,  # NSCompositeSourceOver
        1.0
    )

    # Draw red badge in top-right corner
    badge_size = size * 0.35
    badge_x = size - badge_size - 1
    badge_y = size - badge_size - 1
    badge_rect = ((badge_x, badge_y), (badge_size, badge_size))

    # Red fill
    NSColor.colorWithRed_green_blue_alpha_(0.9, 0.2, 0.2, 1.0).setFill()
    badge = NSBezierPath.bezierPathWithOvalInRect_(badge_rect)
    badge.fill()

    # Optional: Add exclamation mark in badge
    # For now, just a solid red dot is clear enough

    badged_image.unlockFocus()
    # Note: We don't set as template because the red badge needs color
    logger.debug("Added warning badge to icon")
    return badged_image
