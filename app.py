"""
InputGlow - a stream overlay that shows your keys and mouse.

How it works:
  1. Reads keyboard and mouse with Windows Raw Input (read-only copy of input).
  2. Serves the overlay page on http://localhost:8765 for an OBS Browser Source.

It never touches game memory, never injects code, and never sends input.
"""

import asyncio
import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from aiohttp import WSMsgType, web

HOST = "127.0.0.1"   # localhost only, never exposed to your network
PORT = 8765

DEFAULTS = {
    "color": "#2ec5ff",
    "rgb": False,
    "corner": "bottom-left",  # bottom-left | bottom-right | top-left | top-right
    "size": 100,             # percent
    "laser": True,
    "sensitivity": 0.25,     # laser movement per mouse count
    "fade": True,
    "fadeSeconds": 3,
}

# Only these keys are ever sent to the overlay (the left 30% of the keyboard).
# Everything else you type is ignored, so passwords and chat never leave the app.
VK_NAMES = {
    0x1B: "esc", 0x09: "tab", 0x14: "caps", 0x20: "space",
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
}
for _c in "12345QWERTASDFGZXCVB":
    VK_NAMES[ord(_c)] = _c.lower()
VK_F8 = 0x77  # privacy hotkey


def resource_dir() -> Path:
    """Folder with the web files (works for the script and the built .exe)."""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(base) / "web"


def settings_file() -> Path:
    """settings.json sits next to the script or the .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "settings.json"
    return Path(__file__).resolve().parent / "settings.json"


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        saved = json.loads(settings_file().read_text(encoding="utf-8"))
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        settings_file().write_text(json.dumps(s, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Could not save settings: {e}")


class Hub:
    """Collects input from the reader threads and sends it to every overlay."""

    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self.settings = load_settings()
        self.hidden = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self._lock = threading.Lock()
        self._dx = 0
        self._dy = 0

    # Called from reader threads -------------------------------------------
    def emit(self, msg: dict) -> None:
        if self.loop and self.queue:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)

    def add_move(self, dx: int, dy: int) -> None:
        with self._lock:
            self._dx += dx
            self._dy += dy

    def toggle_hidden(self) -> None:
        self.hidden = not self.hidden
        with self._lock:
            self._dx = self._dy = 0
        print("Overlay hidden (F8 to show)" if self.hidden else "Overlay showing")
        self.emit({"t": "hidden", "v": self.hidden})

    # Async side -------------------------------------------------------------
    async def send_all(self, msg: dict) -> None:
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    async def pump(self) -> None:
        while True:
            msg = await self.queue.get()
            await self.send_all(msg)

    async def flush_mouse(self) -> None:
        """Mice can report 1000+ times a second, so bundle moves at 60 per second."""
        while True:
            await asyncio.sleep(1 / 60)
            with self._lock:
                dx, dy = self._dx, self._dy
                self._dx = self._dy = 0
            if (dx or dy) and not self.hidden:
                await self.send_all({"t": "move", "dx": dx, "dy": dy})


# ---------------------------------------------------------------------------
# Keyboard and mouse: Windows Raw Input
# ---------------------------------------------------------------------------
def raw_input_thread(hub: Hub) -> None:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WM_INPUT = 0x00FF
    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE, RIM_TYPEKEYBOARD = 0, 1
    RIDEV_INPUTSINK = 0x00000100   # receive input even when the game has focus
    RI_KEY_BREAK = 0x01            # key released
    MOUSE_MOVE_ABSOLUTE = 0x01

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT),
                    ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD),
                    ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]

    class _BTNS(ctypes.Structure):
        _fields_ = [("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT)]

    class _BTNU(ctypes.Union):
        _fields_ = [("ulButtons", wt.ULONG), ("s", _BTNS)]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [("usFlags", wt.USHORT), ("u", _BTNU),
                    ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG),
                    ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG)]

    class RAWKEYBOARD(ctypes.Structure):
        _fields_ = [("MakeCode", wt.USHORT), ("Flags", wt.USHORT),
                    ("Reserved", wt.USHORT), ("VKey", wt.USHORT),
                    ("Message", wt.UINT), ("ExtraInformation", wt.ULONG)]

    class _RAWDATA(ctypes.Union):
        _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("data", _RAWDATA)]

    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    user32.CreateWindowExW.restype = wt.HWND
    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
    user32.RegisterRawInputDevices.restype = wt.BOOL
    user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, wt.LPVOID,
                                       ctypes.POINTER(wt.UINT), wt.UINT]
    user32.GetRawInputData.restype = wt.UINT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = wt.BOOL
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE

    header_size = ctypes.sizeof(RAWINPUTHEADER)
    held: set[str] = set()
    mouse_buttons = {0x0001: ("ml", True), 0x0002: ("ml", False),
                     0x0004: ("mr", True), 0x0008: ("mr", False),
                     0x0010: ("mm", True), 0x0020: ("mm", False)}

    def handle_keyboard(kb) -> None:
        down = not (kb.Flags & RI_KEY_BREAK)
        if kb.VKey == VK_F8:
            if down and "f8" not in held:
                held.add("f8")
                hub.toggle_hidden()
            elif not down:
                held.discard("f8")
            return
        name = VK_NAMES.get(kb.VKey)
        if not name:
            return  # not shown on the overlay, so it is never sent
        if down and name in held:
            return  # Windows repeats held keys, only send the first press
        if down:
            held.add(name)
        else:
            held.discard(name)
        if not hub.hidden:
            hub.emit({"t": "key", "k": name, "d": down})

    def handle_mouse(m) -> None:
        if not (m.usFlags & MOUSE_MOVE_ABSOLUTE) and (m.lLastX or m.lLastY):
            hub.add_move(m.lLastX, m.lLastY)
        flags = m.u.s.usButtonFlags
        if flags and not hub.hidden:
            for bit, (btn, down) in mouse_buttons.items():
                if flags & bit:
                    hub.emit({"t": "mouse", "b": btn, "d": down})

    @WNDPROC
    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            size = wt.UINT(0)
            user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), header_size)
            buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(RAWINPUT)))
            if user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), header_size) != 0xFFFFFFFF:
                ri = RAWINPUT.from_buffer_copy(buf)
                if ri.header.dwType == RIM_TYPEKEYBOARD:
                    handle_keyboard(ri.data.keyboard)
                elif ri.header.dwType == RIM_TYPEMOUSE:
                    handle_mouse(ri.data.mouse)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = hinst
    wc.lpszClassName = "InputGlowRawInput"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        print("Could not start the input reader (RegisterClass failed).")
        return
    # A hidden window that is never shown. It only receives input messages.
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "InputGlow", 0,
                                  0, 0, 0, 0, None, None, hinst, None)

    devices = (RAWINPUTDEVICE * 2)(
        RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd),  # keyboard
        RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd),  # mouse
    )
    if not user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        print(f"Could not register for input (error {ctypes.get_last_error()}).")
        return

    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
ALLOWED_HOSTS = {f"{HOST}:{PORT}", f"localhost:{PORT}"}


def is_trusted(request: web.Request) -> bool:
    """Block websites from connecting to the local server and reading your input."""
    if request.host not in ALLOWED_HOSTS:
        return False  # stops DNS rebinding tricks
    origin = request.headers.get("Origin")
    return origin is None or origin in ALLOWED_ORIGINS


CHOICES = {
    "corner": {"bottom-left", "bottom-right", "top-left", "top-right"},
}
RANGES = {"size": (50, 200), "sensitivity": (0.05, 1.0), "fadeSeconds": (1, 30)}


def validate_setting(key, value):
    """Return a safe value for a setting, or None to ignore it."""
    if key not in DEFAULTS:
        return None
    if key == "color":
        ok = isinstance(value, str) and len(value) == 7 and value.startswith("#") and \
            all(c in "0123456789abcdefABCDEF" for c in value[1:])
        return value.lower() if ok else None
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if isinstance(DEFAULTS[key], bool):
        return value if isinstance(value, bool) else None
    if key in RANGES and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = RANGES[key]
        value = min(hi, max(lo, value))
        return int(value) if isinstance(DEFAULTS[key], int) else float(value)
    return None


def make_app(hub: Hub) -> web.Application:
    web_dir = resource_dir()

    async def page(request: web.Request, name: str) -> web.StreamResponse:
        if request.host not in ALLOWED_HOSTS:
            raise web.HTTPForbidden()
        return web.FileResponse(web_dir / name, headers={"Cache-Control": "no-store"})

    async def settings_page(request):
        return await page(request, "settings.html")

    async def overlay_page(request):
        return await page(request, "overlay.html")

    fonts = {"Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf"}

    async def font_file(request: web.Request):
        name = request.match_info["name"]
        if request.host not in ALLOWED_HOSTS or name not in fonts:
            raise web.HTTPNotFound()
        return web.FileResponse(web_dir / "fonts" / name,
                                headers={"Cache-Control": "max-age=86400"})

    async def ws_handler(request: web.Request):
        if not is_trusted(request):
            raise web.HTTPForbidden(text="Only the local overlay can connect.")
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        hub.clients.add(ws)
        await ws.send_str(json.dumps({"t": "hello", "settings": hub.settings,
                                      "hidden": hub.hidden}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("t") == "settings" and isinstance(data.get("settings"), dict):
                    for k, v in data["settings"].items():
                        clean = validate_setting(k, v)
                        if clean is not None:
                            hub.settings[k] = clean
                    save_settings(hub.settings)
                    await hub.send_all({"t": "settings", "settings": hub.settings})
                elif data.get("t") == "hide":
                    hub.toggle_hidden()
        finally:
            hub.clients.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/", settings_page)
    app.router.add_get("/overlay", overlay_page)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/fonts/{name}", font_file)
    return app


async def main() -> None:
    hub = Hub()
    hub.loop = asyncio.get_running_loop()
    hub.queue = asyncio.Queue()

    runner = web.AppRunner(make_app(hub), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, HOST, PORT).start()
    except OSError:
        print(f"Port {PORT} is busy. Is InputGlow already open?")
        return

    if sys.platform == "win32":
        threading.Thread(target=raw_input_thread, args=(hub,), daemon=True).start()
    else:
        print("Keyboard and mouse reading only works on Windows. Server runs for testing.")
    asyncio.create_task(hub.pump())
    asyncio.create_task(hub.flush_mouse())

    overlay_url = f"http://localhost:{PORT}/overlay"
    settings_url = f"http://localhost:{PORT}/"
    print()
    print("  InputGlow is running")
    print("  -------------------------------------------")
    print(f"  OBS link:  {overlay_url}")
    print("  In OBS: add a Browser Source, paste the link,")
    print("  and set the size to 1920 x 1080.")
    print()
    print(f"  Settings:  {settings_url}")
    print("  Press F8 any time to hide or show the overlay.")
    print("  Close this window to stop.")
    print()

    if "--no-browser" not in sys.argv:
        webbrowser.open(settings_url)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
