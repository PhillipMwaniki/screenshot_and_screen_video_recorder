#!/usr/bin/env python3
"""ScreenCap — a tray applet for screenshots and screen recordings (X11).

Run with no arguments to start the tray applet. While it is running, the same
command with an action flag talks to the running instance (handy for hotkeys):

    screencap.py --screenshot-full
    screencap.py --screenshot-area
    screencap.py --record-full      # toggles: starts, or stops if recording
    screencap.py --record-area      # toggles: starts, or stops if recording
    screencap.py --stop
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, XApp  # noqa: E402

APP_ID = "io.github.screencap"
CONFIG_PATH = Path(GLib.get_user_config_dir()) / "screencap" / "config.json"
LOG_PATH = Path(GLib.get_user_cache_dir()) / "screencap" / "ffmpeg.log"

DEFAULTS = {
    "screenshot_dir": str(Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or Path.home()) / "Screenshots"),
    "video_dir": str(Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS) or Path.home()) / "Screencasts"),
    "delay": 0,
    "fps": 30,
    "system_audio": False,
    "microphone": False,
    "copy_to_clipboard": True,
    "show_cursor": True,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def first_icon(*names):
    theme = Gtk.IconTheme.get_default()
    for name in names:
        if theme.has_icon(name):
            return name
    return names[-1]


def notify(summary, body="", icon="camera-photo"):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "ScreenCap", "-i", icon, summary, body])
    else:
        print(f"{summary}: {body}")


def timestamp():
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def root_size():
    root = Gdk.get_default_root_window()
    return root.get_width(), root.get_height()


def grab_screen(x=0, y=0, w=None, h=None):
    root = Gdk.get_default_root_window()
    if w is None or h is None:
        w, h = root.get_width(), root.get_height()
    return Gdk.pixbuf_get_from_window(root, x, y, w, h)


class AreaSelector(Gtk.Window):
    """Full-screen overlay over a frozen screenshot; drag to select a rectangle."""

    def __init__(self, on_done, hint):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.on_done = on_done
        self.hint = hint
        self.frozen = grab_screen()
        self.start = None
        self.rect = None  # (x, y, w, h)

        w, h = root_size()
        self.move(0, 0)
        self.set_default_size(w, h)
        self.set_app_paintable(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)
        self.connect("key-press-event", self._key)
        self.connect("map-event", self._grab)

    def _grab(self, *_):
        window = self.get_window()
        window.set_cursor(Gdk.Cursor.new_from_name(window.get_display(), "crosshair"))
        seat = window.get_display().get_default_seat()
        # Retry briefly: the grab can fail if the tray menu still holds it.
        def try_grab(attempts=[20]):
            status = seat.grab(window, Gdk.SeatCapabilities.ALL, True, None, None, None)
            attempts[0] -= 1
            return status != Gdk.GrabStatus.SUCCESS and attempts[0] > 0
        if try_grab():
            GLib.timeout_add(50, try_grab)

    def _finish(self, rect):
        self.get_window().get_display().get_default_seat().ungrab()
        self.destroy()
        # Let the X server repaint without the overlay before capturing.
        GLib.timeout_add(150, lambda: (self.on_done(rect, self.frozen), False)[1])

    def _draw(self, _widget, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.frozen, 0, 0)
        cr.paint()
        w, h = root_size()
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.set_fill_rule(1)  # EVEN_ODD: dim everything except the selection
        cr.rectangle(0, 0, w, h)
        if self.rect:
            cr.rectangle(*self.rect)
        cr.fill()
        if self.rect:
            x, y, rw, rh = self.rect
            cr.set_source_rgba(0.2, 0.6, 1.0, 1)
            cr.set_line_width(2)
            cr.rectangle(x + 0.5, y + 0.5, rw, rh)
            cr.stroke()
            self._label(cr, f"{rw} × {rh}", x, max(y - 28, 4))
        else:
            self._label(cr, self.hint, w / 2 - 180, 24)

    def _label(self, cr, text, x, y):
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(14)
        ext = cr.text_extents(text)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.rectangle(x, y, ext.width + 16, 24)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x + 8, y + 17)
        cr.show_text(text)

    def _press(self, _w, ev):
        if ev.button == 3:
            self._finish(None)
        elif ev.button == 1:
            self.start = (int(ev.x_root), int(ev.y_root))
            self.rect = None

    def _motion(self, _w, ev):
        if self.start:
            x0, y0 = self.start
            x1, y1 = int(ev.x_root), int(ev.y_root)
            self.rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            self.queue_draw()

    def _release(self, _w, ev):
        if ev.button == 1 and self.start:
            rect = self.rect
            self.start = None
            if rect and rect[2] > 4 and rect[3] > 4:
                self._finish(rect)
            else:
                self.rect = None
                self.queue_draw()

    def _key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self._finish(None)
        elif ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            # Enter with no selection = whole screen
            self._finish(self.rect or (0, 0, *root_size()))


class Recorder:
    """Wraps an ffmpeg x11grab process."""

    def __init__(self, cfg, on_exit):
        self.cfg = cfg
        self.on_exit = on_exit
        self.proc = None
        self.path = None
        self.started = 0.0

    @property
    def active(self):
        return self.proc is not None

    def start(self, rect):
        x, y, w, h = rect
        # libx264 + yuv420p needs even dimensions
        w, h = w - (w % 2), h - (h % 2)
        out_dir = Path(self.cfg["video_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"Screencast_{timestamp()}.mp4"

        display = os.environ.get("DISPLAY", ":0")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-thread_queue_size", "512",
            "-f", "x11grab",
            "-draw_mouse", "1" if self.cfg["show_cursor"] else "0",
            "-framerate", str(self.cfg["fps"]),
            "-video_size", f"{w}x{h}",
            "-i", f"{display}+{x},{y}",
        ]
        audio_inputs = []
        if self.cfg["system_audio"]:
            sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True).stdout.strip()
            if sink:
                audio_inputs.append(f"{sink}.monitor")
        if self.cfg["microphone"]:
            audio_inputs.append("default")
        for src in audio_inputs:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", src]

        if len(audio_inputs) == 2:
            cmd += ["-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest[a]",
                    "-map", "0:v", "-map", "[a]"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if audio_inputs:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        cmd.append(str(self.path))

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_PATH, "w")
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        log.close()
        self.started = time.monotonic()
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self.proc.pid, self._exited)

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.write(b"q")  # graceful stop so the mp4 is finalized
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self.proc.send_signal(signal.SIGINT)

    def elapsed(self):
        s = int(time.monotonic() - self.started)
        return f"{s // 60:02d}:{s % 60:02d}"

    def _exited(self, _pid, status):
        path, self.proc = self.path, None
        ok = path.exists() and path.stat().st_size > 0
        self.on_exit(path if ok else None, status)


class ScreenCapApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = load_config()
        self.recorder = Recorder(self.cfg, self._recording_finished)
        self.icon = None
        self.tick_id = 0
        self.busy = False  # an area selection / countdown is in progress
        for flag, desc in [
            ("screenshot-full", "Take a full-screen screenshot"),
            ("screenshot-area", "Select an area and take a screenshot"),
            ("record-full", "Start/stop recording the full screen"),
            ("record-area", "Select an area and start/stop recording"),
            ("stop", "Stop the current recording"),
        ]:
            self.add_main_option(flag, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, desc, None)

    # ---- lifecycle -------------------------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # tray-only app: stay alive with no windows
        self.idle_icon = first_icon("applets-screenshooter", "camera-photo", "image-x-generic")
        self.rec_icon = first_icon("media-record", "media-record-symbolic", "process-stop")
        self.icon = XApp.StatusIcon()
        self.icon.set_name("screencap")
        self.icon.set_icon_name(self.idle_icon)
        self.icon.set_tooltip_text("ScreenCap")
        self.icon.connect("activate", self._on_icon_activate)
        self._rebuild_menu()

    def do_command_line(self, command_line):
        opts = command_line.get_options_dict().end().unpack()
        if opts.get("stop"):
            self.stop_recording()
        elif opts.get("screenshot-full"):
            self.screenshot_full()
        elif opts.get("screenshot-area"):
            self.screenshot_area()
        elif opts.get("record-full"):
            self.toggle_record(area=False)
        elif opts.get("record-area"):
            self.toggle_record(area=True)
        return 0

    # ---- menu ------------------------------------------------------------

    def _rebuild_menu(self):
        menu = Gtk.Menu()
        recording = self.recorder.active

        def item(label, cb, sensitive=True):
            mi = Gtk.MenuItem.new_with_mnemonic(label)
            mi.connect("activate", lambda *_: cb())
            mi.set_sensitive(sensitive)
            menu.append(mi)
            return mi

        def check(label, key):
            mi = Gtk.CheckMenuItem.new_with_mnemonic(label)
            mi.set_active(self.cfg[key])
            mi.connect("toggled", lambda w: self._set(key, w.get_active()))
            mi.set_sensitive(not recording)
            menu.append(mi)

        if recording:
            self.stop_item = item(f"_Stop recording ({self.recorder.elapsed()})", self.stop_recording)
            menu.append(Gtk.SeparatorMenuItem())
        item("Screenshot — _full screen", self.screenshot_full, not recording)
        item("Screenshot — select _area", self.screenshot_area, not recording)
        menu.append(Gtk.SeparatorMenuItem())
        item("Record — f_ull screen", lambda: self.toggle_record(False), not recording)
        item("Record — select a_rea", lambda: self.toggle_record(True), not recording)
        menu.append(Gtk.SeparatorMenuItem())

        opts = Gtk.Menu()
        opts_item = Gtk.MenuItem.new_with_mnemonic("_Options")
        opts_item.set_submenu(opts)
        menu.append(opts_item)
        outer = menu
        menu = opts  # let check()/radio helpers append into the submenu
        check("Record _system audio", "system_audio")
        check("Record _microphone", "microphone")
        check("Show _cursor in recordings", "show_cursor")
        check("Copy screenshots to _clipboard", "copy_to_clipboard")
        menu.append(Gtk.SeparatorMenuItem())
        group = None
        for d in (0, 3, 5, 10):
            mi = Gtk.RadioMenuItem.new_with_label_from_widget(group, f"Delay: {d}s" if d else "Delay: none")
            group = group or mi
            mi.set_active(self.cfg["delay"] == d)
            mi.connect("toggled", lambda w, d=d: w.get_active() and self._set("delay", d))
            menu.append(mi)
        menu.append(Gtk.SeparatorMenuItem())
        group = None
        for fps in (15, 30, 60):
            mi = Gtk.RadioMenuItem.new_with_label_from_widget(group, f"{fps} fps")
            group = group or mi
            mi.set_active(self.cfg["fps"] == fps)
            mi.set_sensitive(not recording)
            mi.connect("toggled", lambda w, f=fps: w.get_active() and self._set("fps", f))
            menu.append(mi)
        menu = outer

        menu.append(Gtk.SeparatorMenuItem())
        item("Open _screenshots folder", lambda: self._open(self.cfg["screenshot_dir"]))
        item("Open _videos folder", lambda: self._open(self.cfg["video_dir"]))
        menu.append(Gtk.SeparatorMenuItem())
        item("_Quit", self._quit)
        menu.show_all()
        self.icon.set_primary_menu(menu)
        self.icon.set_secondary_menu(menu)
        self.menu = menu

    def _on_icon_activate(self, _icon, button, _time):
        # Middle-click (or left-click while recording) stops a recording quickly.
        if self.recorder.active and button in (1, 2):
            self.stop_recording()

    def _set(self, key, value):
        self.cfg[key] = value
        save_config(self.cfg)

    def _open(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(Path(path).as_uri(), None)

    def _quit(self):
        if self.recorder.active:
            self._quit_after_stop = True
            self.stop_recording()
        else:
            self.quit()

    # ---- helpers ---------------------------------------------------------

    def _after_delay(self, fn, use_delay=True):
        """Run fn after the menu has closed plus the configured delay."""
        delay = self.cfg["delay"] if use_delay else 0
        self.busy = True
        if delay <= 0:
            GLib.timeout_add(250, lambda: (self._run(fn), False)[1])
            return
        remaining = [delay]
        self.icon.set_label(str(delay))

        def tick():
            remaining[0] -= 1
            if remaining[0] <= 0:
                self.icon.set_label("")
                self._run(fn)
                return False
            self.icon.set_label(str(remaining[0]))
            return True
        GLib.timeout_add_seconds(1, tick)

    def _run(self, fn):
        self.busy = False
        fn()

    # ---- screenshots -----------------------------------------------------

    def screenshot_full(self):
        if self.busy:
            return
        self._after_delay(lambda: self._save_shot(grab_screen()))

    def screenshot_area(self):
        if self.busy:
            return
        # Area mode: select first (screen is frozen), delay doesn't apply.
        self.busy = True

        def done(rect, frozen):
            self.busy = False
            if rect:
                x, y, w, h = rect
                self._save_shot(frozen.new_subpixbuf(x, y, w, h).copy())
        GLib.timeout_add(250, lambda: (AreaSelector(done, "Drag to select · Enter = full screen · Esc = cancel").show_all(), False)[1])

    def _save_shot(self, pixbuf):
        out_dir = Path(self.cfg["screenshot_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"Screenshot_{timestamp()}.png"
        pixbuf.savev(str(path), "png", [], [])
        if self.cfg["copy_to_clipboard"]:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_image(pixbuf)
        notify("Screenshot saved", str(path), str(path))

    # ---- recording -------------------------------------------------------

    def toggle_record(self, area):
        if self.recorder.active:
            self.stop_recording()
            return
        if self.busy:
            return
        if area:
            self.busy = True

            def done(rect, _frozen):
                self.busy = False
                if rect:
                    self._after_delay(lambda: self._start_recording(rect))
            GLib.timeout_add(250, lambda: (AreaSelector(done, "Drag to select area to record · Esc = cancel").show_all(), False)[1])
        else:
            self._after_delay(lambda: self._start_recording((0, 0, *root_size())))

    def _start_recording(self, rect):
        if not shutil.which("ffmpeg"):
            notify("ffmpeg not found", "Install it with: sudo apt install ffmpeg", "dialog-error")
            return
        self.recorder.start(rect)
        self.icon.set_icon_name(self.rec_icon)
        self.icon.set_label("00:00")
        self.icon.set_tooltip_text("Recording — click to stop")
        self.tick_id = GLib.timeout_add_seconds(1, self._tick)
        self._rebuild_menu()

    def _tick(self):
        if not self.recorder.active:
            return False
        self.icon.set_label(self.recorder.elapsed())
        self.stop_item.set_label(f"Stop recording ({self.recorder.elapsed()})")
        return True

    def stop_recording(self):
        if self.recorder.active:
            self.icon.set_tooltip_text("Finishing recording…")
            self.recorder.stop()

    def _recording_finished(self, path, status):
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = 0
        self.icon.set_icon_name(self.idle_icon)
        self.icon.set_label("")
        self.icon.set_tooltip_text("ScreenCap")
        self._rebuild_menu()
        if path:
            notify("Recording saved", str(path), "video-x-generic")
        else:
            notify("Recording failed", f"See {LOG_PATH}", "dialog-error")
        if getattr(self, "_quit_after_stop", False):
            self.quit()


def main():
    app = ScreenCapApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (app._quit(), True)[1])
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
