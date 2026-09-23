"""
presenter_voice.py
Remaps a Logitech R400 presenter for use with /voice. Uses only ctypes (part of
the Python standard library, nothing extra to install beyond Python itself) to
call the Windows API directly (SetWindowsHookEx / keybd_event) - the same
low-level mechanism any keyboard remapping tool uses.

Run with:  python presenter_voice.py

Active by default - no key press needed to start using it.
Ctrl+Alt+P  = enable/disable the whole remap (beep + console message)

Buttons, while ACTIVE:
    Previous (Page Up)                    -> Up arrow
    Next (Page Down)                      -> Down arrow
    .  (black screen)      tap            -> Enter (sent ~0.5s after the tap,
                                              to leave time for a second tap)
                            double-tap     -> delete the last word (instead
                                              of sending Enter)
    Play (F5 / Esc)        tap            -> toggle speak (first tap holds
                                              Space down, second tap releases
                                              it - push-to-talk without
                                              holding the button physically)
                            double-tap     -> delete everything (cancels the
                                              speak toggle from the first tap
                                              of the pair)

While speak is ON, if you switch to a different window, speak auto-turns OFF
(Space stops being sent) instead of leaking into whatever now has focus.

The buttons on this presenter are momentary click switches, not real
keyboard keys - a physical press only ever produces one instant
down+up pair, no matter how long you hold your finger on it (confirmed by
logging raw event timestamps: down and up land ~15ms apart every time). So
there is no way to detect a genuine "hold" here - every gesture above is
built out of discrete taps within a short time window instead.

"Delete a word" is an approximation (a fixed chunk of Backspace presses, not
real word-boundary detection - this script has no way to read the target
app's actual text). "Delete everything" jumps to the end of the input and
brute-forces Backspace enough times to clear it, since many terminal/CLI
inputs (including Claude Code's prompt) don't support text selection at all
- Ctrl+A/select-all or Shift+Home/End silently do nothing there.

When INACTIVE: nothing is intercepted, your keyboard works 100% normally.

To stop the script: Ctrl+C in the console (or close the window).
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time
import winsound

# ---------------------------------------------------------------------------
# Tunable settings - edit these to adjust timing/behavior.
# ---------------------------------------------------------------------------

# two taps within this window count as a double-tap instead of two independent
# single taps (used by the Play button)
DOUBLE_TAP_WINDOW = 0.4

# how long the "." (black screen / Enter) button waits after a tap before
# actually sending Enter, to leave time for a second tap to arrive (which
# deletes the last word instead of submitting)
PERIOD_DEBOUNCE_WINDOW = 0.5

# how many Backspace presses approximate "one word" (no way to read the
# target app's actual word boundaries, so this is a fixed-size guess)
WORD_CHUNK_BACKSPACES = 6

# generous upper bound of Backspace presses for "delete everything"
DELETE_ALL_BACKSPACES = 500

# gap kept between releasing Space and pressing it again when a delete
# gesture has to interrupt an active /voice session (see RETOGGLE_GAP usage
# below) - confirmed by testing that a single Backspace stops /voice
# listening even with a real keyboard, no script involved, and that just
# holding Space continuously afterward does NOT resume it; only a real
# release-then-press edge with actual time in between does, matching how
# long a manual re-tap of the button takes
RETOGGLE_GAP = 0.15

# use_last_error=True is required, otherwise GetLastError() always reads back 0
# and 64-bit HANDLE/pointer return values get silently truncated to 32 bits
# unless argtypes/restype are declared explicitly (both were the actual cause
# of the earlier "WinError 0 / module not found" crash).
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HHOOK = wintypes.HANDLE
LRESULT = ctypes.c_ssize_t

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.restype = HHOOK
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    LowLevelKeyboardProc,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.keybd_event.restype = None
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
user32.GetMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []

PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
kernel32.SetConsoleCtrlHandler.argtypes = [PHANDLER_ROUTINE, wintypes.BOOL]

WM_QUIT = 0x0012
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1

# --- Win32 constants ---
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
KEYEVENTF_KEYUP = 0x0002

VK_PRIOR = 0x21       # Page Up
VK_NEXT = 0x22        # Page Down
VK_UP = 0x26
VK_DOWN = 0x28
VK_END = 0x23
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_BACK = 0x08
VK_ESCAPE = 0x1B
VK_F5 = 0x74
VK_OEM_PERIOD = 0xBE  # the "." key
VK_CONTROL = 0x11
VK_MENU = 0x12        # Alt
VK_P = 0x50

# simple remap (press -> press, release -> release): Previous / Next only
SIMPLE_REMAP = {
    VK_PRIOR: VK_UP,
    VK_NEXT: VK_DOWN,
}

# the Play button alternates sending F5 or Esc for each physical click - both
# count as the same logical button
PLAY_KEYS = {VK_F5, VK_ESCAPE}

active = True
space_held = False
_space_thread = None
_space_stop_event = None


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def send_key(vk, key_up):
    flags = KEYEVENTF_KEYUP if key_up else 0
    user32.keybd_event(vk, 0, flags, None)


def key_is_down(vk):
    return (user32.GetAsyncKeyState(vk) & 0x8000) != 0


def start_holding_space():
    # A single synthetic keydown does NOT auto-repeat the way a real held key
    # does - apps that detect "held" via repeated keydown events (typical for
    # console/terminal input) never see it as held. So we generate the repeat
    # ourselves, just like the OS does for a physically-held key.
    #
    # keybd_event is global, not targeted at a specific window - it goes to
    # whatever has focus. If the user alt-tabs away while speak is ON, the
    # repeated Space would otherwise leak into the newly-focused window. So
    # we remember which window was focused when this started, and
    # auto-release Space the moment focus moves elsewhere.
    global _space_thread, _space_stop_event, space_held
    _space_stop_event = threading.Event()
    target_hwnd = user32.GetForegroundWindow()

    def repeat():
        global space_held
        send_key(VK_SPACE, key_up=False)
        while not _space_stop_event.wait(0.03):
            if user32.GetForegroundWindow() != target_hwnd:
                send_key(VK_SPACE, key_up=True)
                space_held = False
                print("Presenter /voice: speak OFF (auto, window changed)")
                winsound.Beep(300, 80)
                return
            send_key(VK_SPACE, key_up=False)

    _space_thread = threading.Thread(target=repeat, daemon=True)
    _space_thread.start()


def stop_holding_space():
    global _space_thread, _space_stop_event
    if _space_stop_event is not None:
        _space_stop_event.set()
    if _space_thread is not None:
        _space_thread.join(timeout=0.5)
    send_key(VK_SPACE, key_up=True)
    _space_thread = None
    _space_stop_event = None


def delete_one_word():
    for _ in range(WORD_CHUNK_BACKSPACES):
        send_key(VK_BACK, key_up=False)
        send_key(VK_BACK, key_up=True)
        time.sleep(0.01)


def _delete_all_backspaces():
    # Many terminal/CLI inputs (readline-style, including Claude Code's
    # prompt) don't support text selection at all - Shift+Home/End or
    # Ctrl+A/select-all silently do nothing there. So instead of
    # select+delete, jump to the very end of the input (Ctrl+End) and then
    # brute-force Backspace enough times to guarantee everything is gone,
    # regardless of what selection/select-all bindings the app does or
    # doesn't support.
    send_key(VK_CONTROL, key_up=False)
    send_key(VK_END, key_up=False)
    send_key(VK_END, key_up=True)
    send_key(VK_CONTROL, key_up=True)

    for _ in range(DELETE_ALL_BACKSPACES):
        send_key(VK_BACK, key_up=False)
        send_key(VK_BACK, key_up=True)
        time.sleep(0.001)


def send_delete_all():
    # Runs on its own thread (not inline in the hook callback): a low-level
    # keyboard hook that blocks for too long (default ~300ms) can get
    # silently removed by Windows, and 500 Backspace presses take ~0.5s.
    threading.Thread(target=_delete_all_backspaces, daemon=True).start()


_play_last_tap_time = 0.0
_play_pre_tap_space_state = None


def _play_tap():
    global _play_last_tap_time, _play_pre_tap_space_state, space_held

    now = time.time()
    if _play_last_tap_time and (now - _play_last_tap_time) <= DOUBLE_TAP_WINDOW:
        # second tap of a double-tap: undo the first tap's speak toggle,
        # then delete everything instead
        target_state = _play_pre_tap_space_state
        if space_held:
            stop_holding_space()
            space_held = False

        def worker():
            global space_held
            # a genuine release-then-press edge with real time in between is
            # required on both sides of the Backspace burst - see
            # RETOGGLE_GAP
            time.sleep(RETOGGLE_GAP)
            _delete_all_backspaces()
            if target_state:
                time.sleep(RETOGGLE_GAP)
                start_holding_space()
                space_held = True

        threading.Thread(target=worker, daemon=True).start()
        print("Presenter /voice: deleted everything (double-tap)")
        winsound.Beep(400, 100)
        _play_last_tap_time = 0.0
    else:
        _play_pre_tap_space_state = space_held
        space_held = not space_held
        if space_held:
            start_holding_space()
        else:
            stop_holding_space()
        _play_last_tap_time = now
        print(f"Presenter /voice: speak {'ON' if space_held else 'OFF'}")


# Enter submits the /voice input immediately - by the time a second tap's
# keyup would arrive, the text (and any chance to delete from it) is already
# gone. So unlike Play's tap/double-tap (which can act on the first tap and
# undo it), this one has to wait: hold off sending Enter for
# PERIOD_DEBOUNCE_WINDOW after each tap, and only commit once no further tap
# arrived in that window - one tap then submits, two (or more) delete the
# last word instead.

_period_tap_count = 0
_period_debounce_timer = None


def _period_key_up():
    global _period_tap_count, _period_debounce_timer

    _period_tap_count += 1
    if _period_debounce_timer is not None:
        _period_debounce_timer.cancel()
    _period_debounce_timer = threading.Timer(PERIOD_DEBOUNCE_WINDOW, _period_commit)
    _period_debounce_timer.daemon = True
    _period_debounce_timer.start()


def _period_commit():
    global _period_tap_count, _period_debounce_timer, space_held

    count = _period_tap_count
    _period_tap_count = 0
    _period_debounce_timer = None
    if count == 1:
        if space_held:
            # Enter submits the input - leaving Space held after that just
            # keeps talking into a freshly-submitted/empty box, confusing.
            stop_holding_space()
            space_held = False
            print("Presenter /voice: speak OFF (auto, Enter sent)")
        send_key(VK_RETURN, key_up=False)
        send_key(VK_RETURN, key_up=True)
    else:
        # A Backspace stops /voice from listening even with a real keyboard,
        # no script involved - and just holding Space continuously
        # afterward does NOT resume it. A genuine release-then-press edge
        # with real time in between is needed on both sides of the
        # Backspace burst - see RETOGGLE_GAP.
        was_held = space_held
        if was_held:
            stop_holding_space()
            space_held = False

        def worker():
            global space_held
            if was_held:
                time.sleep(RETOGGLE_GAP)
            delete_one_word()
            if was_held:
                time.sleep(RETOGGLE_GAP)
                start_holding_space()
                space_held = True

        threading.Thread(target=worker, daemon=True).start()
        print("Presenter /voice: deleted last word (double-tap)")
        winsound.Beep(400, 100)


def reset_tap_state():
    global _play_last_tap_time, _play_pre_tap_space_state
    global _period_tap_count, _period_debounce_timer
    _play_last_tap_time = 0.0
    _play_pre_tap_space_state = None
    if _period_debounce_timer is not None:
        _period_debounce_timer.cancel()
    _period_tap_count = 0
    _period_debounce_timer = None


def hook_callback(n_code, w_param, l_param):
    global active, space_held

    if n_code >= 0:
        data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = data.vkCode
        is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = w_param in (WM_KEYUP, WM_SYSKEYUP)

        # Ctrl+Alt+P = toggle active/inactive (only on keydown, so it doesn't repeat while held)
        if is_down and vk == VK_P and key_is_down(VK_CONTROL) and key_is_down(VK_MENU):
            active = not active
            if not active:
                if space_held:
                    stop_holding_space()  # don't leave Space stuck down
                    space_held = False
                reset_tap_state()
            print(f"Presenter /voice: {'ACTIVE' if active else 'inactive'}")
            winsound.Beep(800, 100)
        elif active and vk in PLAY_KEYS:
            if is_up:
                _play_tap()
            return 1
        elif active and vk == VK_OEM_PERIOD:
            if is_up:
                _period_key_up()
            return 1
        elif active and vk in SIMPLE_REMAP:
            target = SIMPLE_REMAP[vk]
            if is_down:
                send_key(target, key_up=False)
                return 1
            if is_up:
                send_key(target, key_up=True)
                return 1

    return user32.CallNextHookEx(None, n_code, w_param, l_param)


def main():
    callback_ptr = LowLevelKeyboardProc(hook_callback)
    hook_id = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, callback_ptr, kernel32.GetModuleHandleW(None), 0
    )

    if not hook_id:
        raise ctypes.WinError(ctypes.get_last_error())

    # GetMessageW below blocks the main thread waiting for Windows to deliver
    # a message. A plain Ctrl+C (SIGINT) can't interrupt that wait - Python
    # only gets a chance to raise KeyboardInterrupt once a message actually
    # arrives, which is why Ctrl+C used to look "stuck". Registering a native
    # console control handler lets us post WM_QUIT directly into this
    # thread's queue the moment Ctrl+C is pressed, which makes GetMessageW
    # return immediately and end the loop cleanly.
    main_thread_id = kernel32.GetCurrentThreadId()

    def console_ctrl_handler(ctrl_type):
        if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
            user32.PostThreadMessageW(main_thread_id, WM_QUIT, 0, 0)
            return True
        return False

    handler_ptr = PHANDLER_ROUTINE(console_ctrl_handler)
    kernel32.SetConsoleCtrlHandler(handler_ptr, True)

    print("Presenter /voice remap started - ACTIVE.")
    print("Ctrl+Alt+P = enable/disable the whole remap. Ctrl+C here = quit.")
    print()
    print("Buttons while ACTIVE:")
    print("  Previous (Page Up)                 -> Up arrow")
    print("  Next (Page Down)                   -> Down arrow")
    print("  .  (black screen)    tap           -> Enter (~0.5s delay)")
    print("                       double-tap    -> delete the last word")
    print("  Play (F5 / Esc)      tap           -> toggle speak")
    print("                       double-tap    -> delete everything")
    print()
    print("Current tunable settings (edit them at the top of the script to change):")
    print(f"  DOUBLE_TAP_WINDOW      = {DOUBLE_TAP_WINDOW}s   (Play tap vs double-tap)")
    print(f"  PERIOD_DEBOUNCE_WINDOW = {PERIOD_DEBOUNCE_WINDOW}s   (delay before '.' sends Enter)")
    print(f"  WORD_CHUNK_BACKSPACES  = {WORD_CHUNK_BACKSPACES}     (Backspaces per 'deleted word')")
    print(f"  DELETE_ALL_BACKSPACES  = {DELETE_ALL_BACKSPACES}   (Backspaces sent by delete-all)")
    print()

    try:
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        if space_held:
            stop_holding_space()  # don't leave Space stuck down on exit
        kernel32.SetConsoleCtrlHandler(handler_ptr, False)
        user32.UnhookWindowsHookEx(hook_id)


if __name__ == "__main__":
    main()
