import curses
import time
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from status_client import StatusClient


class ConsoleUI:
    """
    Curses-based interactive dashboard to inspect and control the HID daemon.
    Navigation levels: root -> services -> characteristics -> char_detail
    """

    def __init__(self):
        # Ensure D-Bus uses GLib main loop for async calls/signals
        DBusGMainLoop(set_as_default=True)

        self.loop_context = GLib.MainContext.default()

        self.client = None
        self.service_available = False
        self.error_msg = ""

        self._connect_client(initial=True)

        self.level = "root"  # root, services, characteristics, char_detail
        self.selected_index = 0
        self.selected_service = None
        self.selected_char = None

        # Reconnect throttling
        self._last_retry = 0
        self._retry_interval = 2.0  # seconds

    def _connect_client(self, initial=False):
        try:
            self.client = StatusClient()
            self.service_available = True
            self.error_msg = ""
            if not initial:
                # Reset selection when service comes back
                self.level = "root"
                self.selected_index = 0
                self.selected_service = None
                self.selected_char = None
        except Exception as e:
            self.client = None
            self.service_available = False
            self.error_msg = str(e)

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        curses.curs_set(0)
        stdscr.timeout(100)  # poll input every 100ms

        while True:
            # Pump GLib events without blocking (needed for D-Bus)
            self.loop_context.iteration(False)

            stdscr.erase()

            # Attempt reconnect if service currently unavailable (throttled)
            now = time.time()
            if not self.service_available and (now - self._last_retry) > self._retry_interval:
                self._last_retry = now
                self._connect_client(initial=False)

            # Fetch status if service is available
            status = {}
            if self.service_available and self.client:
                try:
                    status = self.client.get_status()
                except Exception as e:
                    # Mark service down, keep error for display, and attempt reconnect later
                    self.service_available = False
                    self.error_msg = str(e)

            # Header
            stdscr.addstr(0, 0, "=== HID Peripheral Monitor (Client) ===")
            if not self.service_available:
                stdscr.addstr(1, 0, "Service not running", curses.A_BOLD)
                # Keep the error on one line to avoid wrapping making UI messy
                stdscr.addstr(2, 0, f"(Error: {self._one_line(self.error_msg)})")
            else:
                stdscr.addstr(1, 0, f"Peripheral: {'ON' if status.get('is_on') else 'OFF'}")
                connected = status.get('connected_devices', []) or []
                stdscr.addstr(2, 0, f"Connected devices: {', '.join(connected) or 'None'}")

            # Draw current level
            if self.level == "root":
                self._draw_root(stdscr)
            elif self.level == "services" and self.service_available:
                self._draw_services(stdscr, status)
            elif self.level == "characteristics" and self.service_available:
                self._draw_characteristics(stdscr)
            elif self.level == "char_detail" and self.service_available:
                self._draw_char_detail(stdscr)

            # Footer
            try:
                stdscr.addstr(
                    curses.LINES - 1,
                    0,
                    "Arrows: navigate | Enter: select/toggle | Backspace: back | q: quit",
                )
            except curses.error:
                pass  # terminal too small

            stdscr.refresh()

            # Handle input
            try:
                key = stdscr.getch()
                if key == ord("q"):
                    break
                elif key == curses.KEY_DOWN:
                    self._move_selection(1, status)
                elif key == curses.KEY_UP:
                    self._move_selection(-1, status)
                elif key == 10:  # Enter
                    if not self.service_available:
                        continue  # disable actions if service is down
                    self._handle_enter(status)
                elif key in (8, 127, curses.KEY_BACKSPACE):
                    self._handle_back()
            except Exception:
                # Swallow unexpected UI errors to keep the TUI alive
                pass

    def _move_selection(self, delta, status):
        self.selected_index = max(0, self.selected_index + delta)
        # Clamp within current list size to avoid index errors
        if self.level == "services":
            n = len(status.get("services", []))
            if n:
                self.selected_index %= n
        elif self.level == "characteristics" and self.selected_service:
            n = len(self.selected_service.get("characteristics", []))
            if n:
                self.selected_index %= n

    def _handle_enter(self, status):
        if self.level == "root":
            if (self.selected_index % 2) == 0:
                # Toggle Peripheral
                try:
                    self.client.toggle()
                except Exception as e:
                    self.service_available = False
                    self.error_msg = str(e)
            else:
                # View Services
                self.level = "services"
                self.selected_index = 0
        elif self.level == "services":
            services = status.get("services", [])
            if services:
                self.selected_service = services[self.selected_index % len(services)]
                self.level = "characteristics"
                self.selected_index = 0
        elif self.level == "characteristics":
            chars = self.selected_service.get("characteristics", []) if self.selected_service else []
            if chars:
                self.selected_char = chars[self.selected_index % len(chars)]
                self.level = "char_detail"
        elif self.level == "char_detail":
            uuid = self.selected_char.get("uuid")
            enable = not self.selected_char.get("notifying", False)
            try:
                self.client.set_notify(uuid, enable)
            except Exception as e:
                self.service_available = False
                self.error_msg = str(e)

    def _handle_back(self):
        if self.level == "char_detail":
            self.level = "characteristics"
            self.selected_index = 0
        elif self.level == "characteristics":
            self.level = "services"
            self.selected_index = 0
        elif self.level == "services":
            self.level = "root"
            self.selected_index = 0

    def _draw_root(self, stdscr):
        options = ["Toggle Peripheral", "View Services"]
        for i, opt in enumerate(options):
            marker = ">" if i == (self.selected_index % len(options)) else " "
            if not self.service_available:
                stdscr.addstr(4 + i, 0, f"{marker} {opt} (unavailable)")
            else:
                stdscr.addstr(4 + i, 0, f"{marker} {opt}")

    def _draw_services(self, stdscr, status):
        services = status.get("services", [])
        if not services:
            stdscr.addstr(4, 0, "No services available")
            return
        for i, svc in enumerate(services):
            marker = ">" if i == (self.selected_index % len(services)) else " "
            stdscr.addstr(
                4 + i,
                0,
                f"{marker} Service {svc.get('uuid')} "
                f"({len(svc.get('characteristics', []))} chars)",
            )

    def _draw_characteristics(self, stdscr):
        chars = self.selected_service.get("characteristics", []) if self.selected_service else []
        if not chars:
            stdscr.addstr(4, 0, "No characteristics available")
            return
        for i, ch in enumerate(chars):
            marker = ">" if i == (self.selected_index % len(chars)) else " "
            val = ch.get("value", [])
            notify = ch.get("notifying", False)
            name = ch.get("name") or ""
            stdscr.addstr(
                4 + i,
                0,
                f"{marker} Char {ch.get('uuid')} {name} Val={val} Notifying={notify}",
            )

    def _draw_char_detail(self, stdscr):
        ch = self.selected_char or {}
        stdscr.addstr(4, 0, "Characteristic Detail")
        stdscr.addstr(5, 0, f"Name: {ch.get('name')}")
        stdscr.addstr(6, 0, f"UUID: {ch.get('uuid')}")
        stdscr.addstr(7, 0, f"Value: {ch.get('value')}")
        stdscr.addstr(8, 0, f"Notifying: {ch.get('notifying')} (Enter to toggle)")
        stdscr.addstr(9, 0, f"Flags: {ch.get('flags', [])}")
        row = 11
        for desc in ch.get("descriptors", []):
            stdscr.addstr(row, 2, f"Descriptor {desc.get('uuid')} Val={desc.get('value')}")
            row += 1

    @staticmethod
    def _one_line(msg, max_len=180):
        s = str(msg).replace("\n", " ").replace("\r", " ")
        return s[:max_len]


if __name__ == "__main__":
    ConsoleUI().run()