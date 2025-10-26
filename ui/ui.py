import curses
import time
from .status_client import StatusClient

class ConsoleUI:
    """
    Curses-based interactive dashboard to inspect and control the HID daemon.
    Navigation levels: root -> services -> characteristics -> char_detail
    """
    def __init__(self):
        self.client = StatusClient()
        self.level = "root"  # root, services, characteristics, char_detail
        self.selected_index = 0
        self.selected_service = None
        self.selected_char = None

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)

        while True:
            stdscr.erase()
            status = self.client.get_status()

            stdscr.addstr(0, 0, "=== HID Peripheral Monitor (Client) ===")
            stdscr.addstr(1, 0, f"Peripheral: {'ON' if status.get('is_on') else 'OFF'}")
            connected = status.get('connected_devices', [])
            stdscr.addstr(2, 0, f"Connected devices: {', '.join(connected) or 'None'}")

            if self.level == "root":
                self._draw_root(stdscr)
            elif self.level == "services":
                self._draw_services(stdscr, status)
            elif self.level == "characteristics":
                self._draw_characteristics(stdscr)
            elif self.level == "char_detail":
                self._draw_char_detail(stdscr)

            stdscr.addstr(curses.LINES-1, 0,
                          "Arrows: navigate | Enter: select/toggle | Backspace: back | q: quit")
            stdscr.refresh()

            try:
                key = stdscr.getch()
                if key == ord('q'):
                    break
                elif key == curses.KEY_DOWN:
                    self.selected_index += 1
                elif key == curses.KEY_UP:
                    self.selected_index -= 1
                elif key == 10:  # Enter
                    if self.level == "root":
                        if self.selected_index % 2 == 0:
                            # Toggle peripheral
                            self.client.toggle()
                        else:
                            self.level = "services"
                            self.selected_index = 0
                    elif self.level == "services":
                        services = status.get('services', [])
                        if services:
                            self.selected_service = services[self.selected_index % len(services)]
                            self.level = "characteristics"
                            self.selected_index = 0
                    elif self.level == "characteristics":
                        chars = self.selected_service.get('characteristics', [])
                        if chars:
                            self.selected_char = chars[self.selected_index % len(chars)]
                            self.level = "char_detail"
                    elif self.level == "char_detail":
                        # Toggle notifications for this characteristic
                        uuid = self.selected_char.get('uuid')
                        enable = not self.selected_char.get('notifying', False)
                        self.client.set_notify(uuid, enable)
                elif key == 127 or key == curses.KEY_BACKSPACE:
                    if self.level == "char_detail":
                        self.level = "characteristics"
                        self.selected_index = 0
                    elif self.level == "characteristics":
                        self.level = "services"
                        self.selected_index = 0
                    elif self.level == "services":
                        self.level = "root"
                        self.selected_index = 0
            except Exception:
                pass

            time.sleep(0.2)

    def _draw_root(self, stdscr):
        options = ["Toggle Peripheral", "View Services"]
        for i, opt in enumerate(options):
            marker = ">" if i == self.selected_index % len(options) else " "
            stdscr.addstr(4 + i, 0, f"{marker} {opt}")

    def _draw_services(self, stdscr, status):
        services = status.get('services', [])
        for i, svc in enumerate(services):
            marker = ">" if i == self.selected_index % max(1, len(services)) else " "
            stdscr.addstr(4 + i, 0,
                          f"{marker} Service {svc.get('uuid')} "
                          f"({len(svc.get('characteristics', []))} chars)")

    def _draw_characteristics(self, stdscr):
        chars = self.selected_service.get('characteristics', [])
        for i, ch in enumerate(chars):
            marker = ">" if i == self.selected_index % max(1, len(chars)) else " "
            val = ch.get('value', [])
            notify = ch.get('notifying', False)
            stdscr.addstr(4 + i, 0,
                          f"{marker} Char {ch.get('uuid')} {ch.get('name')} "
                          f"Val={val} Notifying={notify}")

    def _draw_char_detail(self, stdscr):
        ch = self.selected_char
        stdscr.addstr(4, 0, "Characteristic Detail")
        stdscr.addstr(5, 0, f"Name: {ch.get('name')}")
        stdscr.addstr(6, 0, f"UUID: {ch.get('uuid')}")
        stdscr.addstr(7, 0, f"Value: {ch.get('value')}")
        stdscr.addstr(8, 0, f"Notifying: {ch.get('notifying')} (Enter to toggle)")
        stdscr.addstr(9, 0, f"Flags: {ch.get('flags', [])}")
        row = 11
        for desc in ch.get('descriptors', []):
            stdscr.addstr(row, 2, f"Descriptor {desc.get('uuid')} Val={desc.get('value')}")
            row += 1

if __name__ == '__main__':
    ConsoleUI().run()
