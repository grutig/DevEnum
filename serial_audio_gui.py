#!/usr/bin/env python3
"""
Serial & Audio Device Viewer — for radio amateurs
Card-based UI with physical/virtual port classification.

devenum
Linux serial and audio ports gui enumerator
rel 0.2.2

part of i8zse hampack project (https://www.i8zse.it/hampack/)

Copyright (c) 2025 I8ZSE, Giorgio L. Rutigliano
(www.i8zse.it, www.i8zse.eu, www.giorgiorutigliano.it)

This is free software released under LGPL License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import gettext
import os
import re
import subprocess
import tkinter as tk
from tkinter import ttk

import serial.tools.list_ports
import sounddevice as sd

# -----------------------------------------------------------------------------
#  Internationalisation
#  Strings marked with _() are extracted by pybabel and compiled into .mo files
#  under  locales/<lang>/LC_MESSAGES/serial_audio_gui.mo
# -----------------------------------------------------------------------------
APP_NAME   = "serial_audio_gui"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
LOCALE_DIR = os.path.join(SCRIPT_DIR, "locales")

def _setup_i18n() -> callable:
    """
    Return the translation callable _().
    Falls back to identity (English) when no .mo file is found.
    The locale is taken from the environment (LANG / LC_ALL / LC_MESSAGES).
    Override with:  LANGUAGE=it python serial_audio_gui.py
    """
    try:
        t = gettext.translation(APP_NAME, LOCALE_DIR)
        return t.gettext
    except FileNotFoundError:
        return gettext.gettext   # identity – English strings are already the source

_ = _setup_i18n()


# -----------------------------------------------------------------------------
#  Colour palette  (no theme engine required)
# -----------------------------------------------------------------------------
C: dict[str, str] = {
    "bg"          : "#F4F3EF",   # window background
    "card_bg"     : "#FFFFFF",
    "card_border" : "#E0DED8",
    "section_fg"  : "#8C8A82",

    # side-bar accent colours and badge fills
    "ext_bar"     : "#1D9E75",   # teal green  – external physical (USB)
    "int_bar"     : "#378ADD",   # blue        – internal physical (PCI/UART)
    "virt_bar"    : "#7F77DD",   # violet      – virtual ports

    "ext_bg"      : "#E1F5EE",
    "ext_fg"      : "#0F6E56",
    "int_bg"      : "#E6F1FB",
    "int_fg"      : "#185FA5",
    "virt_bg"     : "#EEEDFE",
    "virt_fg"     : "#534AB7",
    "ok_bg"       : "#EAF3DE",
    "ok_fg"       : "#3B6D11",
    "warn_bg"     : "#FAEEDA",
    "warn_fg"     : "#854F0B",
    "gray_bg"     : "#EFEDE8",
    "gray_fg"     : "#5F5E5A",

    "label_fg"    : "#6B6964",
    "mono_fg"     : "#1E1E1C",
    "title_fg"    : "#1E1E1C",
}


# -----------------------------------------------------------------------------
#  Serial-port helpers
# -----------------------------------------------------------------------------

def _process_of(device: str) -> str:
    """
    Return "name (PID XXXX)" of the process that currently holds *device* open,
    or an empty string when the port is free or when the tools are unavailable.
    Requires: fuser (package psmisc) and ps (standard).
    """
    try:
        raw = subprocess.check_output(
            ["fuser", device], stderr=subprocess.DEVNULL, text=True
        ).strip()
        pids = raw.split()
        if not pids:
            return ""
        pid  = pids[0]
        comm = subprocess.check_output(
            ["ps", "-p", pid, "-o", "comm="],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return f"{comm} (PID {pid})"
    except Exception:
        return ""


def _irq_and_addr(device: str) -> tuple[str, str]:
    """
    Return (IRQ, I/O address) for /dev/ttySx ports via setserial.
    Returns ("—", "—") when setserial is unavailable or the port is not present.
    """
    irq = addr = "—"
    try:
        out = subprocess.check_output(
            ["setserial", "-g", device], stderr=subprocess.DEVNULL, text=True
        )
        m = re.search(r"irq:\s*(\d+)", out)
        if m:
            irq = m.group(1)
        m = re.search(r"uart_base:\s*(0x[\dA-Fa-f]+)", out) or \
            re.search(r"port:\s*(0x[\dA-Fa-f]+)", out)
        if m:
            addr = m.group(1)
    except Exception:
        pass
    return irq, addr


def classify_port(port) -> dict:
    """
    Inspect a *serial.tools.list_ports.ListPortInfo* object and return a dict:

        kind     : "physical_ext" | "physical_int" | "virtual"
        subtype  : human-readable label (already in the UI language via _())
        in_use   : bool
        process  : str  – "name (PID N)" when in_use, else ""
        extra    : dict – kind-specific fields:
                       physical_ext  → {"location": str}
                       physical_int  → {"irq": str, "addr": str}
                       virtual PTY   → {"master": str}
    """
    dev  = port.device
    hwid = (port.hwid        or "").upper()
    desc = (port.description or "").lower()

    result: dict = dict(
        kind    = "virtual",
        subtype = _("Virtual"),
        in_use  = False,
        process = "",
        extra   = {},
    )

    # -- VIRTUAL: pseudo-terminals (/dev/pts/N) -------------------------------
    if dev.startswith("/dev/pts/"):
        result["subtype"] = _("PTY (pseudo-terminal)")
        proc = _process_of(dev)
        if proc:
            result["in_use"]  = True
            result["process"] = proc
        result["extra"]["master"] = "/dev/ptmx"
        return result

    # -- VIRTUAL: legacy BSD pty (/dev/ttypN) --------------------------------
    if re.match(r"/dev/ttyp\d+", dev):
        result["subtype"] = _("PTY (legacy BSD)")
        return result

    # -- VIRTUAL: explicitly marked in HWID or description -------------------
    if "VIRTUAL" in hwid or "virtual" in desc or "socat" in desc:
        result["subtype"] = _("Virtual pair (socat / tty0tty)")
        return result

    # -- VIRTUAL: ttyUSB/ttyACM without a real USB VID -----------------------
    if port.vid is None and re.match(r"/dev/tty(USB|ACM)\d+", dev):
        result["subtype"] = _("Virtual (no VID)")
        return result

    # -- PHYSICAL EXTERNAL: USB-to-serial or USB CDC -------------------------
    if re.match(r"/dev/tty(USB|ACM)\d+", dev) and port.vid is not None:
        proc = _process_of(dev)
        result.update(
            kind    = "physical_ext",
            subtype = _("External USB"),
            in_use  = bool(proc),
            process = proc,
            extra   = {"location": port.location or "—"},
        )
        return result

    # -- PHYSICAL INTERNAL: on-board or ISA/PCI RS-232 (/dev/ttySN) ----------
    if re.match(r"/dev/ttyS\d+", dev):
        irq, addr = _irq_and_addr(dev)
        proc = _process_of(dev)
        result.update(
            kind    = "physical_int",
            subtype = _("Internal RS-232"),
            in_use  = bool(proc),
            process = proc,
            extra   = {"irq": irq, "addr": addr},
        )
        return result

    # -- PHYSICAL INTERNAL: add-in PCI/PCIe serial card ----------------------
    if "PCI" in hwid or re.match(r"/dev/ttyPCI\d+", dev):
        result.update(kind="physical_int", subtype=_("Internal PCI/PCIe"))
        return result

    # -- PHYSICAL EXTERNAL: Bluetooth RFCOMM ---------------------------------
    if re.match(r"/dev/rfcomm\d+", dev) or "BLU" in hwid:
        result.update(kind="physical_ext", subtype=_("Bluetooth"))
        return result

    # -- PHYSICAL EXTERNAL: generic USB with VID -----------------------------
    if port.vid is not None:
        result.update(kind="physical_ext", subtype=_("External USB (generic)"))
        return result

    # -- Fallback: treat as virtual -------------------------------------------
    return result


# -----------------------------------------------------------------------------
#  Reusable widgets
# -----------------------------------------------------------------------------

class Badge(tk.Label):
    """Pill-shaped coloured label used for status and type indicators."""

    def __init__(self, parent, text: str, bg: str, fg: str, **kw):
        super().__init__(
            parent, text=text, bg=bg, fg=fg,
            padx=7, pady=2,
            font=("TkDefaultFont", 9, "bold"),
            relief="flat", bd=0,
            **kw,
        )


class SectionLabel(tk.Frame):
    """Bold section heading with a trailing horizontal rule."""

    def __init__(self, parent, text: str, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        tk.Label(
            self, text=text,
            bg=C["bg"], fg=C["section_fg"],
            font=("TkDefaultFont", 8, "bold"),
        ).pack(side="left", padx=(0, 8))
        tk.Frame(self, height=1, bg=C["card_border"]).pack(
            side="left", fill="x", expand=True,
        )


class MetaGrid(tk.Frame):
    """Two-column key → value grid displayed inside a card."""

    def __init__(self, parent, rows: list[tuple[str, str]], **kw):
        super().__init__(parent, bg=C["card_bg"], **kw)
        for i, (key, val) in enumerate(rows):
            col = (i % 2) * 2
            row = i // 2
            tk.Label(
                self, text=key,
                bg=C["card_bg"], fg=C["label_fg"],
                font=("TkDefaultFont", 9), anchor="w", width=16,
            ).grid(row=row, column=col, sticky="w", padx=(0, 2))
            tk.Label(
                self, text=str(val),
                bg=C["card_bg"], fg=C["mono_fg"],
                font=("TkFixedFont", 9), anchor="w",
            ).grid(row=row, column=col + 1, sticky="w", padx=(0, 20))


class ScrollFrame(tk.Frame):
    """
    A Frame with an internal Canvas + Scrollbar that expands to fill its parent.
    Children should be packed into *self.inner*.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        vsb    = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win_id, width=e.width),
        )

        # Mouse-wheel scrolling (Linux: Button-4 / Button-5)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        canvas.bind_all("<Button-4>", lambda _e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda _e: canvas.yview_scroll( 1, "units"))


# -----------------------------------------------------------------------------
#  Serial card
# -----------------------------------------------------------------------------

_KIND_BAR_COLOR: dict[str, str] = {
    "physical_ext" : C["ext_bar"],
    "physical_int" : C["int_bar"],
    "virtual"      : C["virt_bar"],
}
_KIND_BADGE: dict[str, tuple[str, str]] = {
    "physical_ext" : (C["ext_bg"],  C["ext_fg"]),
    "physical_int" : (C["int_bg"],  C["int_fg"]),
    "virtual"      : (C["virt_bg"], C["virt_fg"]),
}


def make_serial_card(parent, port, info: dict) -> tk.Frame:
    """Build and return a fully populated serial-port card widget."""
    bar_color        = _KIND_BAR_COLOR.get(info["kind"], C["virt_bar"])
    badge_bg, badge_fg = _KIND_BADGE.get(info["kind"], _KIND_BADGE["virtual"])

    outer = tk.Frame(parent, bg=bar_color, bd=0)
    inner = tk.Frame(outer,  bg=C["card_bg"], bd=0)
    inner.pack(side="left", fill="both", expand=True, padx=(3, 0))

    # Header row: device path  ·  type badge  ·  status badge
    header = tk.Frame(inner, bg=C["card_bg"])
    header.pack(fill="x", padx=10, pady=(8, 3))

    tk.Label(
        header, text=port.device,
        bg=C["card_bg"], fg=C["title_fg"],
        font=("TkFixedFont", 11, "bold"),
    ).pack(side="left")

    badges = tk.Frame(header, bg=C["card_bg"])
    badges.pack(side="right")

    Badge(badges, text=info["subtype"], bg=badge_bg, fg=badge_fg).pack(
        side="left", padx=2,
    )
    if info["in_use"]:
        Badge(badges, text=_("In use"),
              bg=C["warn_bg"], fg=C["warn_fg"]).pack(side="left", padx=2)
    else:
        Badge(badges, text=_("Available"),
              bg=C["ok_bg"],   fg=C["ok_fg"]).pack(side="left", padx=2)

    # Key-value grid
    rows: list[tuple[str, str]] = [
        (_("Driver / Descr."), port.description or "—"),
        (_("HWID"),            port.hwid         or "—"),
    ]
    if port.vid is not None:
        vid_pid = (
            f"{port.vid:04X}:{port.pid:04X}"
            if port.pid is not None
            else f"{port.vid:04X}:—"
        )
        rows.append((_("VID:PID"), vid_pid))
    if port.serial_number:
        rows.append((_("Serial No."), port.serial_number))

    if info["kind"] == "physical_ext":
        rows.append((_("USB location"), info["extra"].get("location", "—")))
    elif info["kind"] == "physical_int":
        rows.append((_("IRQ"),         info["extra"].get("irq",  "—")))
        rows.append((_("I/O address"), info["extra"].get("addr", "—")))

    if info["kind"] == "virtual" and "master" in info["extra"]:
        rows.append((_("PTY master"), info["extra"]["master"]))

    if info["in_use"] and info["process"]:
        rows.append((_("Process"), info["process"]))

    MetaGrid(inner, rows).pack(fill="x", padx=10, pady=(0, 8))
    return outer


# -----------------------------------------------------------------------------
#  Audio card
# -----------------------------------------------------------------------------

def make_audio_card(parent, idx: int, dev: dict) -> tk.Frame:
    """Build and return a fully populated audio-device card widget."""
    def_in  = sd.default.device[0]
    def_out = sd.default.device[1]

    outer = tk.Frame(parent, bg=C["int_bar"], bd=0)
    inner = tk.Frame(outer,  bg=C["card_bg"], bd=0)
    inner.pack(side="left", fill="both", expand=True, padx=(3, 0))

    # Header
    header = tk.Frame(inner, bg=C["card_bg"])
    header.pack(fill="x", padx=10, pady=(8, 3))

    name = dev["name"]
    if len(name) > 42:
        name = name[:40] + "…"
    tk.Label(
        header, text=f"{idx}: {name}",
        bg=C["card_bg"], fg=C["title_fg"],
        font=("TkDefaultFont", 10, "bold"),
    ).pack(side="left")

    badges = tk.Frame(header, bg=C["card_bg"])
    badges.pack(side="right")

    is_in  = (idx == def_in)
    is_out = (idx == def_out)
    if is_in and is_out:
        Badge(badges, text=_("Default I/O"),
              bg=C["ok_bg"],  fg=C["ok_fg"]).pack(side="left", padx=2)
    elif is_in:
        Badge(badges, text=_("Default IN"),
              bg=C["int_bg"], fg=C["int_fg"]).pack(side="left", padx=2)
    elif is_out:
        Badge(badges, text=_("Default OUT"),
              bg=C["ext_bg"], fg=C["ext_fg"]).pack(side="left", padx=2)

    # Channel / sample-rate pills
    io_row = tk.Frame(inner, bg=C["card_bg"])
    io_row.pack(fill="x", padx=10, pady=(0, 4))

    n_in  = dev["max_input_channels"]
    n_out = dev["max_output_channels"]
    sr    = int(dev["default_samplerate"])

    if n_in > 0:
        Badge(io_row,
              text=f"▶ {n_in} {_('In')}",
              bg=C["int_bg"], fg=C["int_fg"]).pack(side="left", padx=(0, 4))
    if n_out > 0:
        Badge(io_row,
              text=f"◀ {n_out} {_('Out')}",
              bg=C["ext_bg"], fg=C["ext_fg"]).pack(side="left", padx=(0, 4))

    tk.Label(
        io_row, text=f"{sr:,} Hz".replace(",", "."),
        bg=C["card_bg"], fg=C["label_fg"],
        font=("TkDefaultFont", 9),
    ).pack(side="right")

    # Latency + host API
    rows: list[tuple[str, str]] = [
        (_("Low input lat."),   f"{dev['default_low_input_latency']:.4f} s"),
        (_("Low output lat."),  f"{dev['default_low_output_latency']:.4f} s"),
        (_("High input lat."),  f"{dev['default_high_input_latency']:.4f} s"),
        (_("High output lat."), f"{dev['default_high_output_latency']:.4f} s"),
        (_("Host API"),         sd.query_hostapis(dev["hostapi"])["name"]),
    ]
    MetaGrid(inner, rows).pack(fill="x", padx=10, pady=(0, 8))
    return outer


# -----------------------------------------------------------------------------
#  Main application window
# -----------------------------------------------------------------------------

class SerialAudioApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(_("Serial & Audio Device Viewer"))
        self.geometry("600x400")
        self.minsize(500, 300)
        self.configure(bg=C["bg"])

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",     background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["bg"], padding=[14, 6],
                        font=("TkDefaultFont", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", C["card_bg"])],
                  foreground=[("selected", C["title_fg"])])

        # Window title bar
        top = tk.Frame(self, bg=C["bg"], pady=8)
        top.pack(fill="x", padx=12)
        tk.Label(
            top, text=_("Serial & Audio Device Viewer"),
            bg=C["bg"], fg=C["title_fg"],
            font=("TkDefaultFont", 13, "bold"),
        ).pack(side="left")

        # Notebook with two tabs
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self._serial_tab = tk.Frame(nb, bg=C["bg"])
        self._audio_tab  = tk.Frame(nb, bg=C["bg"])
        nb.add(self._serial_tab, text=_("  Serial Ports  "))
        nb.add(self._audio_tab,  text=_("  Audio Devices  "))

        self._build_serial_tab()
        self._build_audio_tab()

    # -- Serial tab ------------------------------------------------------------

    def _build_serial_tab(self) -> None:
        toolbar = tk.Frame(self._serial_tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=4, pady=(8, 4))

        self._serial_count = tk.StringVar(value="")
        tk.Label(
            toolbar, textvariable=self._serial_count,
            bg=C["bg"], fg=C["section_fg"],
            font=("TkDefaultFont", 9),
        ).pack(side="left")

        self._serial_filter = tk.StringVar(value="all")
        filters = [
            ("all",          _("All")),
            ("physical_ext", _("External USB")),
            ("physical_int", _("Internal")),
            ("virtual",      _("Virtual")),
        ]
        for val, lbl in filters:
            tk.Radiobutton(
                toolbar, text=lbl,
                variable=self._serial_filter, value=val,
                bg=C["bg"], fg=C["label_fg"],
                selectcolor=C["bg"], activebackground=C["bg"],
                font=("TkDefaultFont", 9),
                command=self.refresh_serial,
            ).pack(side="left", padx=6)

        tk.Button(
            toolbar, text="↺ " + _("Refresh"),
            command=self.refresh_serial,
            bg=C["card_bg"], fg=C["title_fg"],
            relief="flat", bd=1, padx=10, pady=3,
            font=("TkDefaultFont", 9),
        ).pack(side="right")

        self._serial_scroll = ScrollFrame(self._serial_tab, bg=C["bg"])
        self._serial_scroll.pack(fill="both", expand=True, padx=4)
        self.refresh_serial()

    def refresh_serial(self) -> None:
        frame = self._serial_scroll.inner
        for w in frame.winfo_children():
            w.destroy()

        ports   = serial.tools.list_ports.comports()
        active  = self._serial_filter.get()
        buckets: dict[str, list] = {
            "physical_ext": [],
            "physical_int": [],
            "virtual":      [],
        }
        for p in ports:
            info = classify_port(p)
            buckets[info["kind"]].append((p, info))

        sections = [
            ("physical_ext", _("Physical · External (USB)")),
            ("physical_int", _("Physical · Internal (RS-232 / PCI)")),
            ("virtual",      _("Virtual · Software (PTY / socat)")),
        ]
        shown = 0
        for kind, label in sections:
            if active not in ("all", kind):
                continue
            items = buckets[kind]
            if not items:
                continue
            SectionLabel(frame, label).pack(fill="x", padx=4, pady=(10, 4))
            for p, info in items:
                make_serial_card(frame, p, info).pack(fill="x", padx=4, pady=3)
                shown += 1

        if shown == 0:
            tk.Label(
                frame, text=_("No serial ports found."),
                bg=C["bg"], fg=C["section_fg"],
                font=("TkDefaultFont", 10),
            ).pack(pady=30)

        total = sum(len(v) for v in buckets.values())
        self._serial_count.set(
            _("{n} port(s) found").format(n=total)
        )

    # -- Audio tab -------------------------------------------------------------

    def _build_audio_tab(self) -> None:
        toolbar = tk.Frame(self._audio_tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=4, pady=(8, 4))

        self._audio_count = tk.StringVar(value="")
        tk.Label(
            toolbar, textvariable=self._audio_count,
            bg=C["bg"], fg=C["section_fg"],
            font=("TkDefaultFont", 9),
        ).pack(side="left")

        self._audio_filter = tk.StringVar(value="all")
        filters = [
            ("all", _("All")),
            ("in",  _("Input only")),
            ("out", _("Output only")),
        ]
        for val, lbl in filters:
            tk.Radiobutton(
                toolbar, text=lbl,
                variable=self._audio_filter, value=val,
                bg=C["bg"], fg=C["label_fg"],
                selectcolor=C["bg"], activebackground=C["bg"],
                font=("TkDefaultFont", 9),
                command=self.refresh_audio,
            ).pack(side="left", padx=6)

        tk.Button(
            toolbar, text="↺ " + _("Refresh"),
            command=self.refresh_audio,
            bg=C["card_bg"], fg=C["title_fg"],
            relief="flat", bd=1, padx=10, pady=3,
            font=("TkDefaultFont", 9),
        ).pack(side="right")

        self._audio_scroll = ScrollFrame(self._audio_tab, bg=C["bg"])
        self._audio_scroll.pack(fill="both", expand=True, padx=4)
        self.refresh_audio()

    def refresh_audio(self) -> None:
        frame = self._audio_scroll.inner
        for w in frame.winfo_children():
            w.destroy()

        devices = sd.query_devices()
        active  = self._audio_filter.get()
        shown   = 0

        for idx, dev in enumerate(devices):
            if active == "in"  and dev["max_input_channels"]  == 0:
                continue
            if active == "out" and dev["max_output_channels"] == 0:
                continue
            make_audio_card(frame, idx, dev).pack(fill="x", padx=4, pady=3)
            shown += 1

        if shown == 0:
            tk.Label(
                frame, text=_("No audio devices found."),
                bg=C["bg"], fg=C["section_fg"],
                font=("TkDefaultFont", 10),
            ).pack(pady=30)

        self._audio_count.set(
            _("{n} device(s) found").format(n=len(devices))
        )


# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = SerialAudioApp()
    app.mainloop()
