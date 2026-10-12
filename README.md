# ScreenCap

A tray applet for Linux Mint / Cinnamon (X11) that takes screenshots and records the screen, either full screen or a selected area.

- **Screenshots** are saved as PNGs to `~/Pictures/Screenshots` and copied to the clipboard.
- **Recordings** are saved as MP4 (H.264) to `~/Videos/Screencasts`, with optional system audio and/or microphone.
- **Area selection** freezes the screen. Drag to select, press Enter for the full screen, or press Esc (or right-click) to cancel.
- **Options** (in the tray menu) cover the capture delay (0/3/5/10 s), 15/30/60 fps, the cursor, audio sources, and whether the recording timer appears in the panel. Settings are saved to `~/.config/screencap/config.json`.

## Requirements
`python3-gi`, `gir1.2-xapp-1.0`, `ffmpeg`, `pulseaudio-utils`/`pipewire-pulse` (all preinstalled on Mint).

## Run
```sh
./screencap.py          # start the tray applet
./install.sh            # add menu entry, autostart, and hotkeys
./install.sh --uninstall
```

## Hotkeys (set by install.sh)
| Keys | Action |
|---|---|
| Super+Shift+S | Screenshot area |
| Super+Shift+F | Screenshot full screen |
| Super+Shift+R | Record area (press again to stop) |
| Super+Shift+V | Record full screen (press again to stop) |

While recording, the tray icon turns into a record icon with a timer. Click it, or choose **Stop recording**, to finish.

The same actions work from a terminal while the applet is running: `screencap.py --screenshot-area | --screenshot-full | --record-area | --record-full | --stop`.

If a recording fails, the ffmpeg log is at `~/.cache/screencap/ffmpeg.log`.
