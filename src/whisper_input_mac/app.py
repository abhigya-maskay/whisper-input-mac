from Cocoa import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
)


def build_menu(status_item):
    menu = NSMenu.alloc().init()
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Whisper Input", "terminate:", "q"
    )
    menu.addItem_(quit_item)
    status_item.setMenu_(menu)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
        NSVariableStatusItemLength
    )
    status_item.button().setTitle_("🎙")
    build_menu(status_item)

    app.run()


if __name__ == "__main__":
    main()
