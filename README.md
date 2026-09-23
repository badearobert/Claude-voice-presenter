# Claude voice presenter

Remaps a Logitech R400 presenter clicker so its buttons drive [Claude Code](https://claude.com/claude-code)'s `/voice` mode - letting you present, navigate, and dictate hands-free with a presenter you probably already own.

It's a single Python script (`presenter_voice.py`) that uses only `ctypes` (Python's standard library - nothing extra to install) to call the Windows API directly (`SetWindowsHookEx` / `keybd_event`), the same low-level mechanism any keyboard remapping tool uses.

## Requirements

- Windows
- Python 3 (standard library only, no dependencies)
- A Logitech R400 presenter (or similar clicker with Previous/Next/Play/black-screen buttons)

## Run

```
python presenter_voice.py
```

Active immediately - no key press needed to start using it.

## What it does

| Button | While ACTIVE |
|---|---|
| Previous (Page Up) | Up arrow |
| Next (Page Down) | Down arrow |
| Play (F5 / Esc), single tap | Toggle speak |
| `.` (black screen), single tap | Enter |
| `.` (black screen), double-tap | Delete the last word (approximation - deletes the last 6 characters) |
| Play (F5 / Esc), double-tap | Delete everything (cancels the speak toggle from the first tap) |

`Ctrl+Alt+P` enables/disables the whole remap (beep + console message). When inactive, your keyboard works 100% normally.

If you switch windows while speak is ON, it auto-turns off instead of leaking Space into whatever now has focus.

`Ctrl+C` in the console (or closing the window) stops the script.

## Notes / limitations

- The presenter's buttons are momentary click switches, not real keyboard keys - a physical press only ever produces one instant down+up pair, so there's no way to detect a genuine "hold." Every gesture above is built out of discrete taps within a short time window instead.
- "Delete a word" is an approximation (a fixed chunk of Backspace presses, not real word-boundary detection) since the script can't read the target app's actual text.
- "Delete everything" jumps to the end of the input and brute-forces Backspace, since many terminal/CLI inputs (including Claude Code's prompt) don't support text selection at all.
- A Backspace stops `/voice` from listening (confirmed even with a real keyboard, no script involved), and just holding Space afterward doesn't resume it - it needs a genuine release-then-press with real time in between. So both delete gestures release Space, wait, delete, wait, then re-press Space to restart listening, instead of leaving Space held through the Backspace burst.
- Tunable timings (double-tap window, debounce delay, backspace counts, the retoggle gap) are constants at the top of `presenter_voice.py`.
