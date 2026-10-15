#!/usr/bin/env python3
"""Desktop dashboard (laptop screen) + Windows-style volume/brightness OSD.

Dashboard: a full-screen bento grid drawn as an override-redirect window at
the bottom of the stacking order, so i3 never manages it — it shows on an
empty workspace and any app covers it.

OSD: this long-running process also owns the D-Bus name dev.dashboard.Osd.
i3's volume/brightness/mic keys call i3/osd.sh, which forwards the key here.
Handling keys in one process means key-repeat can't pile up a backlog of
scripts, bursts are merged, and the popup updates in place.

Cheap by design:
  * dashboard polls only while visible (i3 IPC says when the eDP workspace
    is empty); otherwise every timer is stopped
  * reads /proc, /sys, cgroup files and D-Bus in-process, no tool spawns
  * audio refreshes on `pactl subscribe` events, not on a timer
  * background jobs are single-flight, so slow refreshes never pile up

Uses system python3 because it needs PyGObject (python3-gi).
Debug: DASHBOARD_FORCE_VISIBLE=1, DASHBOARD_FAST=1 (short intervals).
"""

import calendar
import collections
import ctypes
import glob
import itertools
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
OUTPUT = os.environ.get("DASHBOARD_OUTPUT", "eDP")
WALLPAPER = f"{HOME}/.config/i3/duneworm.jpg"
AUDIO_SWITCH = f"{HOME}/.config/rofi/scripts/audio-switch.sh"
BT_HEADPHONES = f"{HOME}/.config/polybar/polybar-scripts/bluetooth-click.sh"
NET_MENU = f"{HOME}/.local/bin/networkmanager_dmenu"
BAR_HEIGHT = 34  # polybar, bottom of the screen
DASH_WS = "0"    # the dashboard's own workspace (i3: $mod+0); no apps allowed there

FORCE_VISIBLE = os.environ.get("DASHBOARD_FORCE_VISIBLE") == "1"
FAST = os.environ.get("DASHBOARD_FAST") == "1"
PREVIEW = os.environ.get("DASHBOARD_PREVIEW") == "1"  # e.g. under xvfb-run for screenshots
EVERY = {"system": 2, "net": 1, "services": 10, "toggles": 5, "agents": 3, "servers": 5, "hogs": 5}
if FAST:
    EVERY = {k: 0.2 for k in EVERY}

# Supabase projects are discovered, not configured: every `supabase start`
# labels its containers with the project id and workdir, and the services
# poll (already running `docker ps`) reads them. Projects seen once are
# remembered here so they keep a row (and can be started) after they stop.
SUPABASE_SEEN = f"{HOME}/.cache/dashboard/supabase-projects.json"


def load_seen_projects():
    """{project id: workdir}, dropping projects whose folder is gone."""
    try:
        with open(SUPABASE_SEEN) as f:
            seen = json.load(f)
    except (OSError, ValueError):
        return {}
    return {p: w for p, w in seen.items() if os.path.isfile(f"{w}/supabase/config.toml")}


def save_seen_projects(seen):
    try:
        os.makedirs(os.path.dirname(SUPABASE_SEEN), exist_ok=True)
        with open(SUPABASE_SEEN, "w") as f:
            json.dump(seen, f, indent=1)
    except OSError:
        pass
POSTGRES = [
    (f"Postgres {p.split('/')[-2]}", f"postgresql@{p.split('/')[-2]}-{p.split('/')[-1]}.service")
    for p in sorted(glob.glob("/etc/postgresql/*/*"))
]

# Graphite dark palette (keep in sync with dashboard.css, dunstrc, polybar)
C = {
    "fg": "#ececef", "dim": "#8b8b94", "green": "#6fdc9b", "orange": "#f4b860",
    "red": "#f47174", "blue": "#8ab4f8", "track": "#2e2e33", "tile": "#18181b",
    "canvas": "#0c0c0e",
}
MB = 1048576

# Symbolic (SVG) icons from the Adwaita theme: they render smoothly at any
# size and take their colour from CSS `color`, unlike Nerd Font glyphs.
G = {
    "vol3": "audio-volume-high-symbolic", "vol2": "audio-volume-medium-symbolic",
    "vol1": "audio-volume-low-symbolic", "mute": "audio-volume-muted-symbolic",
    "sun": "display-brightness-symbolic",
    "mic": "audio-input-microphone-symbolic", "mic_off": "microphone-sensitivity-muted-symbolic",
    "wifi": "network-wireless-signal-excellent-symbolic", "wifi_off": "network-wireless-disabled-symbolic",
    "bt": "bluetooth-active-symbolic", "bt_off": "bluetooth-disabled-symbolic",
    "bell_off": "notifications-disabled-symbolic", "bell": "preferences-system-notifications-symbolic",
    "headphones": "audio-headphones-symbolic",
}


def icon(name, size, *classes):
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return css(img, *classes)


# ── small utilities ──────────────────────────────────────────────────────────

def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rounded_rect(cr, x, y, w, h, r):
    """Add a rounded-rectangle path (cairo has no built-in for it)."""
    r = max(0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


RADIUS = 14  # tiles and the OSD; keep in sync with dashboard.css


def human(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def rate(bps):
    mbit = bps * 8 / 1e6
    return f"{mbit:.1f}" if mbit < 100 else f"{mbit:.0f}"


def run(*cmd, timeout=10):
    """Blocking; only call from worker threads. subprocess.run reaps the child."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ok(*cmd, timeout=600):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def spawn(*argv):
    """Fire-and-forget. GLib double-forks, so no zombies are left behind."""
    try:
        GLib.spawn_async(list(argv), flags=GLib.SpawnFlags.SEARCH_PATH
                         | GLib.SpawnFlags.STDOUT_TO_DEV_NULL | GLib.SpawnFlags.STDERR_TO_DEV_NULL)
    except GLib.Error:
        pass


def notify(title, body=""):
    spawn("notify-send", "-a", "dashboard", title, body)


_prctl = ctypes.CDLL("libc.so.6", use_errno=True).prctl  # loaded here, never in a forked child


def die_with_parent():
    """preexec_fn: the kernel SIGTERMs the child when the dashboard exits, so a
    restart never orphans `pactl subscribe` (each one holds a PipeWire client
    slot; ~60 orphans and nothing else can connect). Must only be used for
    children started from the main thread: the signal fires when the forking
    *thread* exits."""
    _prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def later(ms, fn):
    """Run fn once after ms (GLib timeouts repeat if the callback is truthy)."""
    GLib.timeout_add(ms, lambda: fn() and False)


class Job:
    """Run fn in a thread and pass its result to done() on the GTK thread.
    Single-flight: a kick while running just queues one more run."""

    def __init__(self, fn, done):
        self.fn, self.done = fn, done
        self.running = self.again = False

    def kick(self):
        if self.running:
            self.again = True
            return
        self.running = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            result = self.fn()
        except Exception as e:  # keep the process alive; log and move on
            print("dashboard job failed:", repr(e), flush=True)
            result = None
        GLib.idle_add(self._finish, result)

    def _finish(self, result):
        self.running = False
        if result is not None:
            self.done(result)
        if self.again:
            self.again = False
            self.kick()
        return False


class Every:
    """A GLib timer that can be paused and resumed."""

    def __init__(self, seconds, fn):
        self.ms, self.fn, self.id = int(seconds * 1000), fn, 0

    def start(self):
        if not self.id:
            self.fn()
            self.id = GLib.timeout_add(self.ms, self._tick)

    def stop(self):
        if self.id:
            GLib.source_remove(self.id)
            self.id = 0

    def _tick(self):
        self.fn()
        return True


# ── D-Bus (in-process, no tool spawns) ───────────────────────────────────────

SYSTEM_BUS = Gio.bus_get_sync(Gio.BusType.SYSTEM)
SESSION_BUS = Gio.bus_get_sync(Gio.BusType.SESSION)


def dbus_get(bus, name, path, iface, prop):
    try:
        reply = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", (iface, prop)), GLib.VariantType("(v)"),
                              Gio.DBusCallFlags.NONE, 1000, None)
        return reply.unpack()[0]
    except GLib.Error:
        return None


def dbus_set(bus, name, path, iface, prop, value):
    bus.call(name, path, "org.freedesktop.DBus.Properties", "Set",
             GLib.Variant("(ssv)", (iface, prop, value)), None,
             Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 10000, None, None, None)


NM = "org.freedesktop.NetworkManager"
WIFI = (SYSTEM_BUS, NM, "/org/freedesktop/NetworkManager", NM, "WirelessEnabled")
BLUETOOTH = (SYSTEM_BUS, "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered")
PROFILE = (SYSTEM_BUS, "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
           "net.hadess.PowerProfiles", "ActiveProfile")
DND = (SESSION_BUS, "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
       "org.dunstproject.cmd0", "pauseLevel")


# ── hardware: backlight + volume ─────────────────────────────────────────────

class Backlight:
    """Writes /sys directly (user is in the video group). Percent is
    perceptual (squared), and 0% is a dim-but-on floor, never black."""
    DIR = "/sys/class/backlight/amdgpu_bl1"
    EXP, FLOOR = 2, 1500

    def __init__(self):
        with open(f"{self.DIR}/max_brightness") as f:
            self.max = int(f.read())

    def raw(self):
        with open(f"{self.DIR}/brightness") as f:
            return int(f.read())

    def pct(self):
        frac = max(0, self.raw() - self.FLOOR) / (self.max - self.FLOOR)
        return round(frac ** (1 / self.EXP) * 100)

    def set_pct(self, pct):
        pct = max(0, min(100, pct))
        raw = self.FLOOR + round((pct / 100) ** self.EXP * (self.max - self.FLOOR))
        try:
            with open(f"{self.DIR}/brightness", "w") as f:
                f.write(str(raw))
        except OSError:  # not writable? fall back to logind via brightnessctl
            spawn("brightnessctl", "-d", "amdgpu_bl1", "-q", "set", str(raw))
        return pct


class Volume:
    """Merges key-repeat bursts into one pactl change, then reports back."""

    def __init__(self, on_result):
        self.pending = 0
        self.lock = threading.Lock()
        self.job = Job(self._apply, on_result)

    def step(self, delta):
        with self.lock:
            self.pending += delta
        self.job.kick()

    def _apply(self):
        with self.lock:
            delta, self.pending = self.pending, 0
        if delta:
            cur = int((re.findall(r"(\d+)%", run("pactl", "get-sink-volume", "@DEFAULT_SINK@")) or [0])[0])
            target = max(0, min(153, cur + delta))
            if delta > 0:
                run("pactl", "set-sink-mute", "@DEFAULT_SINK@", "0")
            run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{target}%")
        vol = int((re.findall(r"(\d+)%", run("pactl", "get-sink-volume", "@DEFAULT_SINK@")) or [0])[0])
        muted = "yes" in run("pactl", "get-sink-mute", "@DEFAULT_SINK@")
        return vol, muted


# ── i3 IPC ───────────────────────────────────────────────────────────────────

class I3:
    MAGIC = b"i3-ipc"

    def __init__(self):
        self.path = os.environ.get("I3SOCK") or run("i3", "--get-socketpath")
        self.req = socket.socket(socket.AF_UNIX)
        self.req.connect(self.path)

    @classmethod
    def send(cls, sock, kind, payload=""):
        data = payload.encode()
        sock.sendall(cls.MAGIC + struct.pack("<II", len(data), kind) + data)

    @staticmethod
    def recv(sock):
        head = sock.recv(14, socket.MSG_WAITALL)
        length, kind = struct.unpack("<II", head[6:])
        return kind, (sock.recv(length, socket.MSG_WAITALL) if length else b"")

    def ask(self, kind):
        self.send(self.req, kind)
        return json.loads(self.recv(self.req)[1])

    def focused_rect(self):
        """Workspace area (excludes polybar) of the focused monitor."""
        ws = next(w for w in self.ask(1) if w["focused"])
        return ws["rect"]

    def watch(self, on_visible):
        """Workspace 0 belongs to the dashboard: call on_visible(bool) when it
        is shown/hidden, and move any app that lands there back out."""
        self.events = socket.socket(socket.AF_UNIX)
        self.events.connect(self.path)
        self.send(self.events, 2, json.dumps(["workspace", "window", "output"]))
        self.recv(self.events)
        self.on_visible, self.visible, self.pending = on_visible, None, 0
        self.last_ws = "1"  # where evicted apps go: the last workspace used before 0
        GLib.io_add_watch(self.events.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_event)
        self._check()

    def _on_event(self, *_):
        self.recv(self.events)
        if not self.pending:
            self.pending = GLib.timeout_add(40, self._check)  # coalesce event bursts
        return True

    def _check(self):
        self.pending = 0
        workspaces = self.ask(1)
        focused = next((w for w in workspaces if w["focused"]), None)
        if focused and focused["name"] != DASH_WS:
            self.last_ws = focused["name"]
        if any(w["name"] == DASH_WS for w in workspaces):
            self._evict(self.ask(4))
        shown = any(w["name"] == DASH_WS and w["visible"] and w["output"] == OUTPUT for w in workspaces)
        if shown != self.visible:
            self.visible = shown
            self.on_visible(shown)
        return False

    def _evict(self, tree):
        """Move app windows off workspace 0 (to the last workspace) and follow them.
        A shown scratchpad window is left alone, it's just passing over."""
        stack, ws0 = [tree], None
        while stack and ws0 is None:
            n = stack.pop()
            if n.get("type") == "workspace" and n.get("name") == DASH_WS:
                ws0 = n
            stack.extend(n.get("nodes", []))
        if not ws0:
            return
        # Every app window (leaf) on ws 0 except the dashboard itself; tiled
        # windows can be nested in split containers next to it.
        cons, stack = [], list(ws0.get("nodes", []))
        while stack:
            c = stack.pop()
            if c.get("window"):
                if (c.get("window_properties") or {}).get("class") != "Dashboard":
                    cons.append(c)
            else:
                stack.extend(c.get("nodes", []))
        cons += [f for f in ws0.get("floating_nodes", []) if f.get("scratchpad_state", "none") == "none"]
        if cons:
            cmds = [f'[con_id={c["id"]}] move container to workspace number {self.last_ws}' for c in cons]
            self.send(self.req, 0, "; ".join(cmds + [f"workspace number {self.last_ws}"]))
            self.recv(self.req)


# ── data sources ─────────────────────────────────────────────────────────────

def meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            info[k] = int(v.split()[0]) / 1024
    return info


class CpuSampler:
    def __init__(self):
        self.prev = self._read()

    @staticmethod
    def _read():
        with open("/proc/stat") as f:
            vals = list(map(int, f.readline().split()[1:]))
        return vals[3] + vals[4], sum(vals)

    def percent(self):
        idle, total = self._read()
        pidle, ptotal = self.prev
        self.prev = (idle, total)
        dt = total - ptotal
        return 0.0 if dt == 0 else 100 * (1 - (idle - pidle) / dt)


def uptime_text():
    with open("/proc/uptime") as f:
        s = int(float(f.read().split()[0]))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"up {d}d {h}h" if d else f"up {h}h {m}m"


def os_name():
    try:
        with open("/etc/os-release") as f:
            return dict(l.rstrip().split("=", 1) for l in f if "=" in l).get("PRETTY_NAME", "").strip('"')
    except OSError:
        return ""


def default_iface():
    with open("/proc/net/route") as f:
        for line in f.readlines()[1:]:
            parts = line.split()
            if parts[1] == "00000000":
                return parts[0]
    return None


class NetSampler:
    def __init__(self, keep=90):
        self.prev = None
        self.down = collections.deque([0.0] * keep, maxlen=keep)
        self.up = collections.deque([0.0] * keep, maxlen=keep)

    def sample(self):
        iface = default_iface()
        if not iface:
            self.prev = None
            return None, 0.0, 0.0
        try:
            with open(f"/sys/class/net/{iface}/statistics/rx_bytes") as f:
                rx = int(f.read())
            with open(f"/sys/class/net/{iface}/statistics/tx_bytes") as f:
                tx = int(f.read())
        except OSError:
            return iface, 0.0, 0.0
        now = time.monotonic()
        d = u = 0.0
        if self.prev and self.prev[0] == iface and now > self.prev[3]:
            dt = now - self.prev[3]
            d, u = (rx - self.prev[1]) / dt, (tx - self.prev[2]) / dt
        self.prev = (iface, rx, tx, now)
        self.down.append(d)
        self.up.append(u)
        return iface, d, u


def wifi_quality(iface):
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if line.strip().startswith(f"{iface}:"):
                    return min(1.0, float(line.split()[2].rstrip(".")) / 70)
    except (OSError, ValueError, IndexError):
        pass
    return None


def local_ip():
    try:  # UDP connect sends nothing; it just picks the outgoing address
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "—"


def container_mb(cid):
    """Like `docker stats`: cgroup usage minus reclaimable file cache."""
    base = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope"
    try:
        with open(f"{base}/memory.current") as f:
            cur = int(f.read())
        with open(f"{base}/memory.stat") as f:
            inactive = next((int(l.split()[1]) for l in f if l.startswith("inactive_file ")), 0)
        return max(0, cur - inactive) / MB
    except OSError:
        return 0.0


def services_snapshot():
    units = ["docker.service", "containerd.service"] + [u for _, u in POSTGRES]
    out = run("systemctl", "show", "-p", "Id,ActiveState,MemoryCurrent", *units)
    state = {}
    for block in out.split("\n\n"):
        kv = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        mem = kv.get("MemoryCurrent", "")
        state[kv.get("Id")] = (kv.get("ActiveState") == "active", int(mem) / MB if mem.isdigit() else 0.0)
    supabase = {}
    if state.get("docker.service", (False,))[0]:
        out = run("docker", "ps", "--no-trunc", "--format",
                  '{{.ID}}\t{{.Label "com.supabase.cli.project"}}\t{{.Label "com.supabase.cli.workdir"}}')
        for line in out.splitlines():
            cid, proj, workdir = (line.split("\t") + ["", ""])[:3]
            if proj:
                mb, wd = supabase.get(proj, (0.0, ""))
                supabase[proj] = (mb + container_mb(cid), wd or workdir)
    return state, supabase


# AI coding agents, by process name (comm). Shown in the Agents tile.
AGENTS = {"claude": "Claude Code", "codex": "Codex", "opencode": "OpenCode",
          "aider": "Aider", "gemini": "Gemini CLI", "cursor-agent": "Cursor Agent"}
TERMINALS = {"kitty", "alacritty", "wezterm-gui", "gnome-terminal-", "code", "cursor"}
HZ = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def read_procs():
    """{pid: (comm, ppid, cpu ticks, start ticks, rss bytes)} straight from /proc."""
    procs = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                s = f.read()
            with open(f"/proc/{d}/statm") as f:
                rss = int(f.read().split()[1]) * PAGE
        except (OSError, IndexError, ValueError):
            continue
        comm = s[s.index("(") + 1:s.rindex(")")]
        rest = s[s.rindex(")") + 2:].split()
        procs[int(d)] = (comm, int(rest[1]), int(rest[11]) + int(rest[12]), int(rest[19]), rss)
    return procs


def memory_hogs(n=5):
    """Top n apps by memory, [(name, mb)]. Processes are grouped by executable
    so Firefox's many content processes count as one app. Uses PSS where we can
    read it (shared pages split fairly, so groups aren't double-counted), RSS
    for other users' processes."""
    apps, pids, me = collections.Counter(), collections.defaultdict(list), os.getpid()
    for pid, (comm, _ppid, _cpu, start, rss) in read_procs().items():
        if not rss or pid == me:
            continue  # kernel threads
        try:
            name = os.readlink(f"/proc/{pid}/exe").removesuffix(" (deleted)")
        except OSError:  # sandboxed (e.g. Firefox content) or another user's
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    name = f.read().split(b"\0")[0].decode(errors="replace") or comm
            except OSError:
                name = comm
        name = os.path.basename(name).removesuffix("-bin").removesuffix(".exe")
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                rss = next(int(l.split()[1]) * 1024 for l in f if l.startswith("Pss:"))
        except (OSError, StopIteration, ValueError):
            pass
        apps[name] += rss
        pids[name].append((pid, start))
    return [(name, b / MB, pids[name]) for name, b in apps.most_common(n)]


def age_text(seconds):
    m = int(seconds // 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h < 24 else f"{h // 24}d {h % 24}h"


class AgentWatch:
    """Running agents with project, age, memory and working/idle (CPU use of
    the agent's whole process tree, including tools it has spawned)."""
    BUSY = 0.03  # share of one core

    def __init__(self):
        self.prev, self.prev_t = {}, None

    def snapshot(self):
        procs, now = read_procs(), time.monotonic()
        kids = collections.defaultdict(list)
        for pid, p in procs.items():
            kids[p[1]].append(pid)
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        found, ticks_now = [], {}
        for pid, (comm, ppid, _t, start, _r) in procs.items():
            if comm not in AGENTS or procs.get(ppid, ("",))[0] == comm:
                continue  # not an agent, or a child of the same agent (wrapper)
            try:
                with open(f"/proc/{pid}/cmdline") as f:
                    if "app-server" in f.read():
                        continue  # Codex's background daemon, not a session
            except OSError:
                continue
            tree, stack = [], [pid]
            while stack:
                q = stack.pop()
                tree.append(q)
                stack.extend(kids.get(q, []))
            ticks = sum(procs[q][2] for q in tree)
            ticks_now[pid] = ticks
            busy = (self.prev_t is not None and pid in self.prev
                    and (ticks - self.prev[pid]) / HZ / (now - self.prev_t) > self.BUSY)
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                cwd = ""
            found.append({"pid": pid, "start": start, "name": AGENTS[comm], "cwd": cwd, "project": project_name(cwd),
                          "age": up - start / HZ, "mb": sum(procs[q][4] for q in tree) / MB, "busy": busy})
        self.prev, self.prev_t = ticks_now, now
        # Stable order (oldest first) so rows aren't rebuilt when busy/idle flips.
        return sorted(found, key=lambda a: -a["age"])


# ── dev servers ──────────────────────────────────────────────────────────────

# Your own processes listening on TCP ports, minus desktop apps that happen to.
NOT_SERVERS = {"kdeconnectd", "spotify", "firefox", "firefox-bin", "code", "Discord", "slack",
               "signal-desktop", "steam", "copyq", "syncthing", "chrome", "electron", "obsidian",
               "zoom", "Isolated Web Co", "gvfsd", "easyeffects", "pipewire", "wireplumber"} | set(AGENTS)
# Processes a dev server is wrapped in; stopping walks up through these.
RUNNERS = {"node", "npm", "npm exec", "pnpm", "yarn", "bun", "deno", "npx", "sh", "uv", "python", "python3",
           "turbo", "nodemon", "tsx", "esbuild"}
SERVER_KINDS = (("next", "Next.js"), ("vite", "Vite"), ("astro", "Astro"), ("nuxt", "Nuxt"),
                ("remix", "Remix"), ("wrangler", "Wrangler"), ("webpack", "Webpack"), ("uvicorn", "Uvicorn"),
                ("gunicorn", "Gunicorn"), ("flask", "Flask"), ("runserver", "Django"), ("jupyter", "Jupyter"),
                ("http.server", "HTTP server"), ("storybook", "Storybook"), ("expo", "Expo"))


def _listening_inodes():
    """{socket inode: port} for TCP sockets *you* are listening on."""
    uid, found = os.getuid(), {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                next(f)
                for line in f:
                    p = line.split()
                    if p[3] == "0A" and int(p[7]) == uid:  # 0A = LISTEN
                        found[p[9]] = int(p[1].rsplit(":", 1)[1], 16)
        except (OSError, StopIteration):
            pass
    return found


def servers_snapshot():
    inodes = _listening_inodes()
    if not inodes:
        return []
    uid, procs = os.getuid(), read_procs()
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    by_pid = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        try:
            if os.stat(f"/proc/{d}").st_uid != uid or procs.get(pid, ("",))[0] in NOT_SERVERS:
                continue
            for fd in os.listdir(f"/proc/{d}/fd"):
                link = os.readlink(f"/proc/{d}/fd/{fd}")
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    by_pid.setdefault(pid, set()).add(inodes[link[8:-1]])
        except OSError:
            continue
    out = []
    for pid, ports in by_pid.items():
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                cmd = f.read().replace("\0", " ")
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        comm = procs.get(pid, ("?",))[0]
        kind = next((k for key, k in SERVER_KINDS if key in cmd.lower()), comm.split(" ")[0].capitalize())
        out.append({"pid": pid, "start": procs[pid][3] if pid in procs else -1,
                    "name": kind, "project": project_name(cwd), "cwd": cwd, "cmd": cmd.strip(),
                    "ports": sorted(ports), "age": up - procs[pid][3] / HZ if pid in procs else 0,
                    "mb": procs[pid][4] / MB if pid in procs else 0})
    return sorted(out, key=lambda s: s["ports"][0])


def stop_tree(pid, walk_up=True):
    """SIGTERM a process and everything it started (then SIGKILL stragglers).
    For servers, first walk up through wrappers like `npm run dev` so the
    whole job stops, never past a shell, terminal or agent."""
    procs = read_procs()
    root = pid
    while walk_up and root in procs:
        parent = procs[root][1]
        pcomm = procs.get(parent, ("",))[0]
        if parent <= 1 or not (pcomm in RUNNERS or pcomm.startswith("next-server")):
            break
        root = parent
    kids = collections.defaultdict(list)
    for p, info in procs.items():
        kids[info[1]].append(p)
    tree, stack = [], [root]
    while stack:
        q = stack.pop()
        tree.append(q)
        stack.extend(kids.get(q, []))
    return kill_all(tree)


def same_process(pid, start):
    """True if pid is still the process that started at `start` (clock ticks)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            s = f.read()
        return int(s[s.rindex(")") + 2:].split()[19]) == start
    except (OSError, ValueError, IndexError):
        return False


def kill_procs(procs):
    """kill_all for [(pid, start ticks)] taken earlier: skips pids that exited
    and were reused by an unrelated process in the meantime."""
    return kill_all([pid for pid, start in procs if same_process(pid, start)])


def kill_all(tree):
    """SIGTERM, wait up to 3 s, then SIGKILL whatever is left."""
    for q in tree:
        try:
            os.kill(q, 15)
        except OSError:
            pass
    for _ in range(30):  # up to 3 s to exit cleanly
        if not any(os.path.exists(f"/proc/{q}") for q in tree):
            return True
        time.sleep(0.1)
    for q in tree:
        try:
            os.kill(q, 9)
        except OSError:
            pass
    return True


def project_name(cwd):
    if not cwd or cwd == HOME:
        return "~"
    parts = os.path.relpath(cwd, HOME).split(os.sep) if cwd.startswith(HOME) else cwd.split(os.sep)
    parts = [p for p in parts if p not in ("", "Code")]
    return "/".join(parts[-2:]) or "~"


def focus_agent(pid):
    """Focus the terminal window the agent runs in (worker thread)."""
    procs, p = read_procs(), pid
    while p in procs and p > 1 and procs[p][0] not in TERMINALS:
        p = procs[p][1]
    if p not in procs or p <= 1:
        return False
    stack, windows = [json.loads(run("i3-msg", "-t", "get_tree") or "{}")], []
    while stack:
        n = stack.pop()
        stack.extend(n.get("nodes", []) + n.get("floating_nodes", []))
        if n.get("window"):
            windows.append(n["window"])
    for w in windows:
        if run("xprop", "-id", str(w), "_NET_WM_PID").endswith(f"= {p}"):
            spawn("i3-msg", f"[id={w}] focus")
            return True
    return False


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _headphones_path():
    """bluez object path for the device bluetooth-click.sh toggles."""
    try:
        with open(BT_HEADPHONES) as f:
            mac = re.search(r'DEVICE="([0-9A-F:]{17})"', f.read(), re.I).group(1)
        return "/org/bluez/hci0/dev_" + mac.upper().replace(":", "_")
    except (OSError, AttributeError):
        return None


HEADPHONES = _headphones_path()


def headphones_state():
    if not HEADPHONES:
        return {"connected": False, "battery": None}
    connected = bool(dbus_get(SYSTEM_BUS, "org.bluez", HEADPHONES, "org.bluez.Device1", "Connected"))
    battery = dbus_get(SYSTEM_BUS, "org.bluez", HEADPHONES, "org.bluez.Battery1", "Percentage") if connected else None
    return {"connected": connected, "battery": battery}


def toggles_snapshot():
    conn = dbus_get(SYSTEM_BUS, NM, "/org/freedesktop/NetworkManager", NM, "PrimaryConnection")
    ssid = None
    if conn and conn != "/":
        ssid = dbus_get(SYSTEM_BUS, NM, conn, f"{NM}.Connection.Active", "Id")
    return {
        "wifi": bool(dbus_get(*WIFI)),
        "bt": bool(dbus_get(*BLUETOOTH)),
        "profile": dbus_get(*PROFILE) or "",
        "dnd": (dbus_get(*DND) or 0) > 0,
        "easyeffects": any(_comm(p) == "easyeffects" for p in os.listdir("/proc") if p.isdigit()),
        "ssid": ssid,
        "headphones": headphones_state(),
        "ip": local_ip(),
    }


def short_device_name(name, desc, kind):
    """'Ryzen HD Audio Controller Digital Microphone' -> 'Built-in', etc."""
    if name.startswith("bluez"):
        return desc  # Bluetooth devices: their own name ("WH-1000XM4")
    d = desc.lower()
    if "audiorelay" in name:  # AudioRelay app: phone used as the PC's mic
        return "AudioRelay"
    for key, short in (("virtual", "Virtual"), ("hdmi", "HDMI"), ("displayport", "Display"),
                       ("headphone", "Headphones"), ("headset", "Headset"),
                       ("digital microphone", "Built-in"), ("internal mic", "Built-in"),
                       ("speaker", "Speakers"), ("usb", "USB")):
        if key in d:
            return short
    return desc.replace("HD Audio Controller", "").strip() or ("Output" if kind == "output" else "Mic")


def audio_snapshot():
    info = json.loads(run("pactl", "-f", "json", "info") or "{}")
    keep = lambda s: not (s["name"].endswith(".monitor") or s["name"].startswith("easyeffects_"))
    sinks = [s for s in json.loads(run("pactl", "-f", "json", "list", "sinks") or "[]") if keep(s)]
    sources = [s for s in json.loads(run("pactl", "-f", "json", "list", "sources") or "[]") if keep(s)]
    dsink, dsrc = info.get("default_sink_name"), info.get("default_source_name")
    muted = next((s.get("mute", False) for s in sources if s["name"] == dsrc), False)
    return {
        "outputs": [(s["name"], s["description"]) for s in sinks], "output": dsink,
        "inputs": [(s["name"], s["description"]) for s in sources], "input": dsrc,
        "muted": muted,
    }


# ── widgets ──────────────────────────────────────────────────────────────────

def css(widget, *names):
    ctx = widget.get_style_context()
    for n in names:
        ctx.add_class(n)
    return widget


def label(text="", *classes, xalign=0.0):
    return css(Gtk.Label(label=text, xalign=xalign), *classes)


def set_class(widget, name, on):
    ctx = widget.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(name)


def tile(title=None, meta=None):
    box = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "tile")
    if title:
        head = css(Gtk.Box(spacing=10), "tile-head")
        head.pack_start(label(title, "tile-title"), True, True, 0)
        if meta is not None:
            head.pack_end(meta, False, False, 0)
        box.pack_start(head, False, False, 0)
    return box


class Meter(Gtk.Box):
    """Segmented, VU-style bar. Colour steps up with load."""
    SEG, GAP = 6, 3

    def __init__(self, name):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top = Gtk.Box()
        top.pack_start(label(name, "meter-name"), True, True, 0)
        self.value = label("", "num", xalign=1.0)
        top.pack_end(self.value, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(-1, 12)
        self.area.connect("draw", self._draw)
        self.frac = 0.0
        self.pack_start(top, False, False, 0)
        self.pack_start(self.area, False, False, 0)

    def set(self, frac, text):
        frac = max(0.0, min(1.0, frac))
        if self.value.get_text() != text:
            self.value.set_text(text)
        if abs(frac - self.frac) > 0.004:
            self.frac = frac
            self.area.queue_draw()

    def _draw(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        n = max(1, (w + self.GAP) // (self.SEG + self.GAP))
        lit = round(self.frac * n)
        hot = C["green"] if self.frac < 0.6 else C["orange"] if self.frac < 0.85 else C["red"]
        for i in range(n):
            cr.set_source_rgb(*rgb(hot if i < lit else C["track"]))
            rounded_rect(cr, i * (self.SEG + self.GAP), 0, self.SEG, h, 2)
            cr.fill()
        return False


class Row(Gtk.Button):
    """Full-width control row: status light · name · value. Click = action."""

    def __init__(self, name, on_click=None):
        super().__init__()
        css(self, "row")
        self.set_relief(Gtk.ReliefStyle.NONE)
        box = Gtk.Box(spacing=14)
        self.dot = css(Gtk.Box(), "dot", "off")
        self.dot.set_size_request(10, 10)
        self.dot.set_valign(Gtk.Align.CENTER)
        self.value = label("", "num", xalign=1.0)
        box.pack_start(self.dot, False, False, 0)
        box.pack_start(label(name, "row-name"), True, True, 0)
        box.pack_end(self.value, False, False, 0)
        self.add(box)
        self.state = "off"
        if on_click:
            self.connect("clicked", lambda *_: on_click())

    def show_state(self, state, value):
        if state != self.state:
            ctx = self.dot.get_style_context()
            ctx.remove_class(self.state)
            ctx.add_class(state)
            self.state = state
        if self.value.get_text() != value:
            self.value.set_text(value)


class KillRow(Gtk.Box):
    """A Row plus a ✕ stop button. First click arms it (red), a second click
    within 3 s stops the process, so nothing dies by accident."""

    def __init__(self, name, on_open, on_kill):
        super().__init__(spacing=6)
        self.row = Row(name, on_open)
        self.pack_start(self.row, True, True, 0)
        self.kill = css(Gtk.Button(), "kill")
        self.kill.set_relief(Gtk.ReliefStyle.NONE)
        self.kill.set_valign(Gtk.Align.CENTER)
        inner = Gtk.Box(spacing=6)
        inner.pack_start(icon("window-close-symbolic", 14), False, False, 0)
        self.kill_lbl = label("Stop?", "kill-label")  # shown only while armed
        self.kill_lbl.set_no_show_all(True)
        inner.pack_start(self.kill_lbl, False, False, 0)
        self.kill.add(inner)
        self.kill.set_tooltip_text("Stop")
        self.kill.connect("clicked", self._clicked)
        self.pack_end(self.kill, False, False, 0)
        self.on_kill, self.armed = on_kill, 0

    def _clicked(self, *_):
        if not self.armed:
            set_class(self.kill, "armed", True)
            self.kill_lbl.show()
            self.kill.set_tooltip_text("Click again to stop")
            self.armed = GLib.timeout_add(3000, self._disarm)
            return
        GLib.source_remove(self.armed)
        self._disarm()
        self.kill.set_sensitive(False)
        self.row.show_state("busy", "stopping…")
        self.on_kill()

    def _disarm(self):
        self.armed = 0
        set_class(self.kill, "armed", False)
        self.kill_lbl.hide()
        self.kill.set_tooltip_text("Stop")
        return False

    def show_state(self, state, value):
        if self.kill.get_sensitive():  # not while stopping
            self.row.show_state(state, value)


class ServiceRow(Row):
    """Row that starts/stops something slow in the background."""

    def __init__(self, dash, name, start, stop):
        super().__init__(name, self._toggle)
        self.dash, self.name, self.start, self.stop = dash, name, start, stop
        self.busy = self.on = False
        self.armed, self.last = 0, ("off", "")

    def _disarm(self):
        self.armed = 0
        Row.show_state(self, *self.last)
        return False

    def show_state(self, state, value):
        if state not in ("alert", "busy"):
            self.last = (state, value)
        if not self.armed or state == "alert":
            super().show_state(state, value)

    def _toggle(self):
        if self.busy:
            return
        if self.on and not self.armed:  # stopping takes a second click
            self.armed = GLib.timeout_add(3000, self._disarm)
            self.show_state("alert", "click again to stop")
            return
        if self.armed:
            GLib.source_remove(self.armed)
            self.armed = 0
        self.busy, want = True, not self.on
        self.show_state("busy", "starting…" if want else "stopping…")
        action = self.start if want else self.stop

        def done(success):
            self.busy = False
            notify(self.name, ("Started" if want else "Stopped") if success else "Failed — see journal")
            self.dash.services.kick()
        Job(action, done).kick()

    def update(self, on, value):
        self.on = on
        if not self.busy:
            self.show_state("on" if on else "off", value)


class ToggleTile(Gtk.Button):
    """Square quick-toggle: big glyph, name, state. Solid accent when on."""

    def __init__(self, name, glyph_on, glyph_off, on_click):
        super().__init__()
        css(self, "toggle")
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.glyphs = (glyph_on, glyph_off)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.glyph = icon(glyph_off, 22, "toggle-glyph")
        self.glyph.set_halign(Gtk.Align.START)
        self.state_lbl = label("", "toggle-state")
        box.pack_start(self.glyph, False, False, 0)
        box.pack_end(self.state_lbl, False, False, 0)
        box.pack_end(label(name, "toggle-name"), False, False, 0)
        self.add(box)
        self.on = False
        self.connect("clicked", lambda *_: on_click())

    def show_state(self, on, text):
        """Only touches what changed, so refreshes don't make it flicker."""
        if on != self.on or not self.glyph.get_icon_name()[0]:
            self.glyph.set_from_icon_name(self.glyphs[0 if on else 1], Gtk.IconSize.BUTTON)
            set_class(self, "on", on)
        self.on = on
        if self.state_lbl.get_text() != text:
            self.state_lbl.set_text(text)


# ── Windows-style OSD ────────────────────────────────────────────────────────

class Osd(Gtk.Window):
    """Compact bar at the bottom-centre of the focused monitor."""
    W, H, LIFT = 340, 60, 28

    def __init__(self, i3):
        super().__init__(type=Gtk.WindowType.POPUP)
        css(self, "osd")
        self.i3 = i3
        self.set_size_request(self.W, self.H)
        # Rounded corners: an RGBA window (picom composites it) whose corners
        # stay empty; the body is painted as a rounded rect in _paint_body.
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self._paint_body)
        self.alert = False
        box = Gtk.Box(spacing=16)
        css(box, "osd-box")
        self.glyph = icon(G["vol3"], 20, "osd-glyph")
        self.bar = Gtk.DrawingArea()
        self.bar.set_size_request(-1, 6)
        self.bar.set_valign(Gtk.Align.CENTER)
        self.bar.connect("draw", self._draw)
        self.text = label("", "osd-text")
        self.value = label("", "osd-value", xalign=1.0)
        self.value.set_size_request(40, -1)
        box.pack_start(self.glyph, False, False, 0)
        box.pack_start(self.bar, True, True, 0)
        box.pack_start(self.text, True, True, 0)
        box.pack_end(self.value, False, False, 0)
        self.add(box)
        box.show_all()
        self.frac, self.color, self.hide_id = 0.0, C["blue"], 0

    def level(self, glyph, frac, value, color=C["blue"]):
        self.glyph.set_from_icon_name(glyph, Gtk.IconSize.BUTTON)
        self.frac, self.color = frac, color
        self.bar.show()
        self.text.hide()
        self.value.set_text(value)
        self.bar.queue_draw()
        self._present(alert=False)

    def message(self, glyph, text, alert=False):
        self.glyph.set_from_icon_name(glyph, Gtk.IconSize.BUTTON)
        self.text.set_text(text)
        self.text.show()
        self.bar.hide()
        self.value.set_text("")
        self._present(alert)

    def _paint_body(self, _w, cr):
        cr.set_operator(0)  # CLEAR: transparent corners
        cr.paint()
        cr.set_operator(2)  # OVER
        w, h = self.get_allocated_width(), self.get_allocated_height()
        # 1px edge + lighter body, matching dunst, so it stands out on dark windows
        cr.set_source_rgb(*rgb(C["red"] if self.alert else "#4a4a52"))
        rounded_rect(cr, 0, 0, w, h, RADIUS)
        cr.fill()
        cr.set_source_rgb(*rgb(C["red"] if self.alert else "#26262b"))
        rounded_rect(cr, 1, 1, w - 2, h - 2, RADIUS - 1)
        cr.fill()
        return False

    def _present(self, alert):
        self.alert = alert
        set_class(self, "alert", alert)
        self.queue_draw()
        try:
            r = self.i3.focused_rect() if self.i3 else None
        except (OSError, StopIteration, ValueError):
            r = None
        if r is None:
            g = Gdk.Display.get_default().get_primary_monitor().get_geometry()
            r = {"x": g.x, "y": g.y, "width": g.width, "height": g.height - BAR_HEIGHT}
        self.move(r["x"] + (r["width"] - self.W) // 2, r["y"] + r["height"] - self.H - self.LIFT)
        if not self.get_visible():
            self.show()
        self.get_window().raise_()
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add(1500, self._hide)

    def _hide(self):
        self.hide_id = 0
        self.hide()
        return False

    def _draw(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(*rgb(C["track"]))
        rounded_rect(cr, 0, 0, w, h, h / 2)
        cr.fill()
        if self.frac > 0:
            cr.set_source_rgb(*rgb(self.color))
            rounded_rect(cr, 0, 0, max(h, w * self.frac), h, h / 2)
            cr.fill()
        return False


class PowerAuto:
    """Plugged in + battery full -> Performance; unplugged -> back to Balanced.

    Acts only when that condition flips, so picking a profile by hand
    afterwards sticks until the next plug/unplug."""
    UPOWER = "org.freedesktop.UPower"
    DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
    FULLY_CHARGED = 4

    def __init__(self, on_change=None):
        self.on_change = on_change
        self.full_on_ac = None
        self.pending = 0
        SYSTEM_BUS.signal_subscribe(self.UPOWER, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                    None, None, Gio.DBusSignalFlags.NONE, self._changed)
        self._evaluate()

    def _changed(self, *_):
        if not self.pending:
            self.pending = GLib.timeout_add(500, self._evaluate)

    def _evaluate(self):
        self.pending = 0
        on_battery = dbus_get(SYSTEM_BUS, self.UPOWER, "/org/freedesktop/UPower", self.UPOWER, "OnBattery")
        pct = dbus_get(SYSTEM_BUS, self.UPOWER, self.DEVICE, f"{self.UPOWER}.Device", "Percentage") or 0
        state = dbus_get(SYSTEM_BUS, self.UPOWER, self.DEVICE, f"{self.UPOWER}.Device", "State")
        if on_battery is None:
            return False
        full_on_ac = not on_battery and (pct >= 99.5 or state == self.FULLY_CHARGED)
        if full_on_ac != self.full_on_ac:
            first = self.full_on_ac is None
            self.full_on_ac = full_on_ac
            current = dbus_get(*PROFILE)
            if full_on_ac and current != "performance":
                dbus_set(*PROFILE, GLib.Variant("s", "performance"))
                spawn("notify-send", "-a", "power", "-u", "low", "Performance mode", "Plugged in and fully charged")
            elif on_battery and current == "performance" and not first:
                dbus_set(*PROFILE, GLib.Variant("s", "balanced"))
                spawn("notify-send", "-a", "power", "-u", "low", "Balanced mode", "Running on battery")
            if self.on_change:
                later(500, self.on_change)
        return False


class Keys:
    """D-Bus service dev.dashboard.Osd: i3/osd.sh forwards media keys here."""
    XML = """<node><interface name='dev.dashboard.Osd'>
      <method name='Key'><arg type='s' name='action' direction='in'/></method>
    </interface></node>"""

    def __init__(self, osd, backlight, on_brightness):
        self.osd, self.backlight, self.on_brightness = osd, backlight, on_brightness
        self.volume = Volume(self._show_volume)
        self.mic = Job(self._toggle_mic, self._show_mic)
        self.last = {}  # action -> time of last press, for tap vs hold
        node =Gio.DBusNodeInfo.new_for_xml(self.XML)
        SESSION_BUS.register_object("/dev/dashboard/Osd", node.interfaces[0], self._call, None, None)
        Gio.bus_own_name_on_connection(SESSION_BUS, "dev.dashboard.Osd",
                                       Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                                       None, None)

    def _call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Key":
            self.handle(params.unpack()[0])
        invocation.return_value(None)

    # A tap moves 5%; holding the key moves 1% per repeat. Repeats arrive every
    # 40 ms (xset: rate 25/s), far faster than anyone taps, so a press that
    # follows the previous one within REPEAT_GAP counts as a hold.
    TAP, HOLD, REPEAT_GAP = 5, 1, 0.12

    def _step(self, action):
        now = time.monotonic()
        held = now - self.last.get(action, 0) < self.REPEAT_GAP
        self.last[action] = now
        size = self.HOLD if held else self.TAP
        return size if action.endswith("-up") else -size

    def handle(self, action):
        if action in ("bright-up", "bright-down"):
            pct = self.backlight.set_pct(self.backlight.pct() + self._step(action))
            self.osd.level(G["sun"], pct / 100, str(pct), C["orange"])
            self.on_brightness(pct)
        elif action in ("vol-up", "vol-down"):
            self.volume.step(self._step(action))
        elif action == "mute":
            spawn("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle")
            later(60, self.volume.job.kick)
        elif action == "mic-mute":
            self.mic.kick()

    def _show_volume(self, result):
        vol, muted = result
        if muted:
            self.osd.level(G["mute"], min(vol, 153) / 153, "muted", C["dim"])
        else:
            glyph = G["vol3"] if vol >= 66 else G["vol2"] if vol >= 33 else G["vol1"]
            self.osd.level(glyph, min(vol, 153) / 153, str(vol))

    @staticmethod
    def _toggle_mic():
        run("pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle")
        return "yes" in run("pactl", "get-source-mute", "@DEFAULT_SOURCE@")

    def _show_mic(self, muted):
        if muted:
            self.osd.message(G["mic_off"], "Microphone muted", alert=True)
        else:
            self.osd.message(G["mic"], "Microphone on")


# ── the dashboard ────────────────────────────────────────────────────────────

class Dashboard(Gtk.Window):
    def __init__(self, geom, backlight):
        # A normal window that i3 assigns to workspace 0 (see i3/config). Being
        # a real window keeps workspace 0 alive, and i3 shows/hides it with the
        # workspace, so it never flashes through other windows.
        super().__init__(title="Dashboard")
        self.set_wmclass("dashboard", "Dashboard")
        self.w, self.h = geom[:2]
        self.set_default_size(self.w, self.h - BAR_HEIGHT)
        self.set_app_paintable(True)
        self.connect("draw", self._paint_canvas)
        self.connect("delete-event", lambda *_: True)  # $mod+Shift+q mustn't close it

        self.backlight = backlight
        self.cpu = CpuSampler()
        self.net = NetSampler()
        self.syncing = False  # set while code (not the user) changes widgets
        self.art_cache = None  # (w, h, cairo surface); the 4K source is only loaded to build it

        grid = css(Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                            column_spacing=10, row_spacing=10), "bento")
        grid.set_margin_top(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_bottom(10)  # i3 already keeps the window above polybar
        place = lambda w, c, r, cw, rh: grid.attach(w, c, r, cw, rh)
        place(self._build_art(), 0, 0, 7, 3)
        place(self._build_agents(), 0, 3, 7, 1)
        place(self._build_clock(), 7, 0, 3, 2)
        place(self._build_system(), 10, 0, 2, 2)
        place(self._build_network(), 7, 2, 5, 1)
        place(self._build_servers(), 7, 3, 5, 1)
        place(self._build_services(), 0, 4, 4, 2)
        place(self._build_audio(), 4, 4, 3, 2)
        place(self._build_controls(), 7, 4, 5, 2)
        self.add(grid)

        self.services = Job(services_snapshot, self._apply_services)
        self.toggles = Job(toggles_snapshot, self._apply_toggles)
        self.audio = Job(audio_snapshot, self._apply_audio)
        self.audio_dirty = True
        self.timers = [
            Every(EVERY["system"], self._refresh_system),
            Every(EVERY["net"], self._refresh_net),
            Every(EVERY["services"], self.services.kick),
            Every(EVERY["toggles"], self.toggles.kick),
            Every(EVERY["agents"], self.agents_job.kick),
            Every(EVERY["servers"], self.servers_job.kick),
            Every(EVERY["hogs"], lambda: self.tab == "hogs" and self.hogs_job.kick()),
        ]
        self.clock_id = 0
        self.visible = False
        self._watch_audio()

    def _paint_canvas(self, _w, cr):
        cr.set_source_rgb(*rgb(C["canvas"]))
        cr.paint()
        return False

    # visibility ------------------------------------------------------------
    def set_visible_state(self, visible):
        self.visible = visible
        # i3 unmaps the window with its workspace; this just pauses the work.
        set_class(self, "paused", not visible)
        if not visible:
            self.net.prev = None  # next rate sample shouldn't average the hidden gap
        if visible:
            self._tick_clock()
            for t in self.timers:
                t.start()
            if self.audio_dirty:
                self.audio_dirty = False
                self.audio.kick()
        else:
            for t in self.timers:
                t.stop()
            if self.clock_id:
                GLib.source_remove(self.clock_id)
                self.clock_id = 0

    # art ----------------------------------------------------------------------
    def _build_art(self):
        overlay = css(Gtk.Overlay(), "art")
        area = Gtk.DrawingArea()
        area.connect("draw", self._draw_art)
        overlay.add(area)
        cap = css(Gtk.Box(spacing=18), "caption")
        cap.set_valign(Gtk.Align.END)
        cap.set_halign(Gtk.Align.START)
        cap.pack_start(label(socket.gethostname(), "host"), False, False, 0)
        self.uptime_lbl = label("", "caption-sub")
        cap.pack_start(self.uptime_lbl, False, False, 0)
        cap.pack_start(label(os_name(), "caption-sub"), False, False, 0)
        overlay.add_overlay(cap)
        return overlay

    def _draw_art(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        rounded_rect(cr, 0, 0, w, h, RADIUS)
        cr.clip()
        if not os.path.exists(WALLPAPER):
            cr.set_source_rgb(*rgb(C["tile"]))
            cr.paint()
            return False
        if not self.art_cache or self.art_cache[:2] != (w, h):
            # "cover" crop: scale to fill, centre, keep aspect
            src = GdkPixbuf.Pixbuf.new_from_file(WALLPAPER)
            sw, sh = src.get_width(), src.get_height()
            scale = max(w / sw, h / sh)
            scaled = src.scale_simple(round(sw * scale), round(sh * scale),
                                               GdkPixbuf.InterpType.BILINEAR)
            ox, oy = (scaled.get_width() - w) // 2, (scaled.get_height() - h) // 2
            crop = scaled.new_subpixbuf(ox, oy, w, h)
            self.art_cache = (w, h, Gdk.cairo_surface_create_from_pixbuf(crop, 1, None))
        cr.set_source_surface(self.art_cache[2], 0, 0)
        cr.paint()
        return False

    # clock --------------------------------------------------------------------
    def _build_clock(self):
        t = tile()
        css(t, "clock-tile")
        self.time_lbl = label("", "clock")
        self.date_lbl = label("", "date")
        t.pack_start(self.time_lbl, False, False, 0)
        t.pack_start(self.date_lbl, False, False, 0)
        self.week = css(Gtk.Grid(column_homogeneous=True), "week")
        self.week.set_valign(Gtk.Align.END)
        t.pack_end(self.week, True, True, 0)
        self.week_day = None
        return t

    def _tick_clock(self):
        now = time.localtime()
        self.time_lbl.set_text(time.strftime("%H:%M", now))
        self.date_lbl.set_text(time.strftime("%A, %-d %B", now))
        if self.week_day != now.tm_yday:
            self.week_day = now.tm_yday
            self._build_week(now)
        self.uptime_lbl.set_text(uptime_text())
        if self.clock_id:
            GLib.source_remove(self.clock_id)
        self.clock_id = GLib.timeout_add((60 - now.tm_sec) * 1000 + 50, self._clock_timer)
        return False

    def _clock_timer(self):
        self.clock_id = 0
        self._tick_clock()
        return False

    def _build_week(self, now):
        for child in self.week.get_children():
            self.week.remove(child)
            child.destroy()
        today = time.mktime(now)
        start = today - ((now.tm_wday + 1) % 7) * 86400  # Sunday first
        for i in range(7):
            d = time.localtime(start + i * 86400)
            cell = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "wcell")
            cell.pack_start(label(time.strftime("%a", d)[:2].upper(), "wdow", xalign=0.5), False, False, 0)
            cell.pack_start(label(str(d.tm_mday), "wday", xalign=0.5), False, False, 0)
            set_class(cell, "today", d.tm_yday == now.tm_yday)
            set_class(cell, "past", d.tm_yday < now.tm_yday and d.tm_year == now.tm_year)
            self.week.attach(cell, i, 0, 1, 1)
        self.week.show_all()

    # system -------------------------------------------------------------------
    def _build_system(self):
        t = tile("System")
        self.meters = {k: Meter(k) for k in ("CPU", "Memory", "Swap", "Disk")}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        for m in self.meters.values():
            box.pack_start(m, False, False, 0)
        t.pack_start(box, True, True, 0)
        return t

    def _refresh_system(self):
        p = self.cpu.percent()
        self.meters["CPU"].set(p / 100, f"{p:.0f}%")
        mi = meminfo()
        used = mi["MemTotal"] - mi["MemAvailable"]
        self.meters["Memory"].set(used / mi["MemTotal"], f"{used / 1024:.1f} / {mi['MemTotal'] / 1024:.0f} GB")
        sw = mi["SwapTotal"] - mi["SwapFree"]
        self.meters["Swap"].set(sw / mi["SwapTotal"] if mi["SwapTotal"] else 0,
                                f"{sw / 1024:.1f} / {mi['SwapTotal'] / 1024:.0f} GB")
        du = shutil.disk_usage("/")
        self.meters["Disk"].set(du.used / du.total, f"{du.free / 2**30:.0f} GB free")
        if not self.dragging_brightness:
            self._show_brightness(self.backlight.pct())

    # network ------------------------------------------------------------------
    def _build_network(self):
        """Compact, one row: name + address | live graph | down/up rates."""
        menu = css(Gtk.Button(label="Networks…"), "link")
        menu.set_relief(Gtk.ReliefStyle.NONE)
        menu.connect("clicked", lambda *_: spawn(NET_MENU))
        t = css(tile("Network", menu), "compact")
        body = Gtk.Box(spacing=24)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.set_valign(Gtk.Align.CENTER)
        self.ssid_lbl = label("—", "ssid")
        self.ssid_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.ssid_lbl.set_max_width_chars(18)
        self.net_sub = label("", "sub")
        left.pack_start(self.ssid_lbl, False, False, 0)
        left.pack_start(self.net_sub, False, False, 0)
        body.pack_start(left, False, False, 0)
        self.spark = Gtk.DrawingArea()
        self.spark.connect("draw", self._draw_spark)
        body.pack_start(self.spark, True, True, 0)
        for key, arrow, cls in (("down", "↓", "rate-down"), ("up", "↑", "rate-up")):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            col.set_valign(Gtk.Align.CENTER)
            val = label("0.0", "rate", cls, xalign=1.0)
            col.pack_start(val, False, False, 0)
            col.pack_start(label(f"{arrow} Mb/s", "unit", xalign=1.0), False, False, 0)
            setattr(self, f"rate_{key}", val)
            body.pack_start(col, False, False, 0)
        t.pack_start(body, True, True, 0)
        self.iface = None
        return t

    # agents -------------------------------------------------------------------
    def _build_agents(self):
        self.agents_meta = label("", "sub", xalign=1.0)
        t = css(tile("Agents", self.agents_meta), "compact")
        self.agent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t.pack_start(self.agent_box, True, True, 0)
        self.agent_rows = {}  # pid -> Row
        self.agent_watch = AgentWatch()
        # /proc scan takes ~25 ms: run it off the UI thread.
        self.agents_job = Job(self.agent_watch.snapshot, self._apply_agents)
        return t

    def _apply_agents(self, agents):
        shown = agents[:self.MAX_AGENTS]
        if [a["pid"] for a in shown] != list(self.agent_rows):
            for child in self.agent_box.get_children():
                self.agent_box.remove(child)
                child.destroy()
            self.agent_rows = {}
            for a in shown:
                row = KillRow(f"{a['name']}  ·  {a['project']}",
                              lambda pid=a["pid"], n=a["name"]: Job(lambda: focus_agent(pid), lambda found, n=n: None if found else notify(
                                  f"{n} has no window", "Its terminal was closed. Use ✕ to stop it.")).kick(),
                              lambda pid=a["pid"], st=a["start"]: Job(lambda: same_process(pid, st) and stop_tree(pid, walk_up=False),
                                                       lambda _r: self.agents_job.kick()).kick())
                row.set_tooltip_text(a["cwd"])
                self.agent_rows[a["pid"]] = row
                self.agent_box.pack_start(row, False, False, 0)
            if not shown:
                self.agent_box.pack_start(label("No agents running", "sub"), False, False, 6)
            self.agent_box.show_all()
        for a in shown:
            self.agent_rows[a["pid"]].show_state(
                "work" if a["busy"] else "off",
                f"{'working' if a['busy'] else 'idle'}  ·  {age_text(a['age'])}  ·  {human(a['mb'])}")
        extra = len(agents) - len(shown)
        working = sum(a["busy"] for a in agents)
        self.agents_meta.set_text(
            f"{len(agents)} running" + (f", {working} working" if working else "") + (f"  (+{extra} more)" if extra else ""))

    MAX_AGENTS = 3

    # servers ------------------------------------------------------------------
    def _build_servers(self):
        self.servers_meta = label("", "sub", xalign=1.0)
        t = css(tile("Servers", self.servers_meta), "compact")
        self.server_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t.pack_start(self.server_box, True, True, 0)
        self.server_rows = {}  # pid -> KillRow
        self.servers_job = Job(servers_snapshot, self._apply_servers)
        return t

    def _apply_servers(self, servers):
        shown = servers[:self.MAX_AGENTS]
        if [s["pid"] for s in shown] != list(self.server_rows):
            for child in self.server_box.get_children():
                self.server_box.remove(child)
                child.destroy()
            self.server_rows = {}
            for s in shown:
                url = f"http://localhost:{s['ports'][0]}"
                row = KillRow(f"{s['name']}  ·  {s['project']}",
                              lambda u=url: spawn("xdg-open", u),
                              lambda pid=s["pid"], st=s["start"]: Job(lambda: same_process(pid, st) and stop_tree(pid),
                                                       lambda _r: self.servers_job.kick()).kick())
                row.set_tooltip_text(f"{url}\n{s['cmd'][:120]}")
                self.server_rows[s["pid"]] = row
                self.server_box.pack_start(row, False, False, 0)
            if not shown:
                self.server_box.pack_start(label("No dev servers running", "sub"), False, False, 6)
            self.server_box.show_all()
        for s in shown:
            ports = ", ".join(f":{p}" for p in s["ports"][:2])
            self.server_rows[s["pid"]].show_state("on", f"{ports}  ·  {age_text(s['age'])}  ·  {human(s['mb'])}")
        extra = len(servers) - len(shown)
        self.servers_meta.set_text(f"{len(servers)} running" + (f"  (+{extra} more)" if extra else "")
                                   if servers else "")

    def _refresh_net(self):
        self.iface, d, u = self.net.sample()
        self.rate_down.set_text(rate(d))
        self.rate_up.set_text(rate(u))
        self.spark.queue_draw()

    def _draw_spark(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        peak = max(max(self.net.down), max(self.net.up), 125_000)  # floor: 1 Mb/s
        cr.set_source_rgb(*rgb(C["track"]))
        for frac in (0.0, 0.5):
            cr.rectangle(0, round(h * frac), w, 1)
        cr.fill()
        n = len(self.net.down)
        for series, color in ((self.net.up, C["blue"]), (self.net.down, C["green"])):
            cr.set_source_rgb(*rgb(color))
            cr.set_line_width(2)
            for i, v in enumerate(series):
                x, y = i * (w - 1) / (n - 1), h - 1 - (v / peak) * (h - 4)
                cr.line_to(x, y) if i else cr.move_to(x, y)
            cr.stroke()
        return False

    # services -----------------------------------------------------------------
    def _build_services(self):
        # Two tabs in the header: Dev services | Top memory
        t = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "tile")
        head = css(Gtk.Box(spacing=4), "tile-head")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.tabs = {}
        for key, title in (("services", "Dev"), ("hogs", "Memory")):
            b = css(Gtk.Button(label=title), "tab")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, k=key: self._show_tab(k))
            self.tabs[key] = b
            head.pack_start(b, False, False, 0)
        self.tab_meta = Gtk.Stack()
        self.stack_total = label("", "sub", xalign=1.0)
        self.hogs_meta = label("", "sub", xalign=1.0)
        self.tab_meta.add_named(self.stack_total, "services")
        self.tab_meta.add_named(self.hogs_meta, "hogs")
        head.pack_end(self.tab_meta, False, False, 0)
        t.pack_start(head, False, False, 0)
        t.pack_start(self.stack, True, True, 0)

        hogs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.hog_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        hogs.pack_start(self.hog_box, False, False, 0)
        self.hog_rows = {}  # name -> KillRow
        self.hogs_job = Job(memory_hogs, self._apply_hogs)  # ~1 s of /proc reads: off the UI thread

        svc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # A Gtk.Stack clips its pages, which cut off the rows' hover background
        # where it bleeds past the text (margin: 0 -10px). Widen the stack by
        # the same amount and inset the pages so the bleed stays inside it.
        css(self.stack, "tab-stack")
        for page in (svc, hogs):
            page.set_margin_start(10)
            page.set_margin_end(10)
        self.stack.add_named(svc, "services")
        self.stack.add_named(hogs, "hogs")
        self.tab = "services"
        set_class(self.tabs["services"], "active", True)
        t, outer = svc, t
        self.docker_row = ServiceRow(
            self, "Docker",
            lambda: ok("systemctl", "start", "docker.service"),
            lambda: ok("systemctl", "stop", "docker.service", "docker.socket", "containerd.service"))
        t.pack_start(self.docker_row, False, False, 0)
        self.supa_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t.pack_start(self.supa_box, False, False, 0)
        self.supa_rows, self.supa_seen = {}, load_seen_projects()
        for proj in sorted(self.supa_seen):
            self._add_supa_row(proj)
        self.pg_rows = {}
        for name, unit in POSTGRES:
            row = ServiceRow(self, name, lambda u=unit: ok("systemctl", "start", u),
                             lambda u=unit: ok("systemctl", "stop", u))
            self.pg_rows[unit] = row
            t.pack_start(row, False, False, 0)
        return outer

    def _add_supa_row(self, proj):
        def start(w=self.supa_seen[proj]):
            if run("systemctl", "is-active", "docker.service") != "active" \
                    and not ok("systemctl", "start", "docker.service"):
                return False
            return ok("supabase", "start", "--workdir", w)
        row = ServiceRow(self, f"Supabase · {proj}", start,
                         lambda w=self.supa_seen[proj]: ok("supabase", "stop", "--workdir", w))
        row.set_tooltip_text(self.supa_seen[proj])
        self.supa_rows[proj] = row
        self.supa_box.pack_start(row, False, False, 0)
        # keep rows alphabetical
        for i, p in enumerate(sorted(self.supa_rows)):
            self.supa_box.reorder_child(self.supa_rows[p], i)
        row.show_all()

    def _show_tab(self, key):
        for k, b in self.tabs.items():
            set_class(b, "active", k == key)
        self.tab = key
        self.stack.set_visible_child_name(key)
        self.tab_meta.set_visible_child_name(key)
        if key == "hogs":
            self.hogs_job.kick()

    def _apply_hogs(self, hogs):
        if [h[0] for h in hogs] != list(self.hog_rows):
            for child in self.hog_box.get_children():
                self.hog_box.remove(child)
                child.destroy()
            self.hog_rows = {}
            for name, _mb, _pids in hogs:
                row = KillRow(name, None, lambda n=name: self._kill_hog(n))
                row.kill.set_tooltip_text("Stop all its processes")
                self.hog_rows[name] = row
                self.hog_box.pack_start(row, False, False, 0)
            self.hog_box.show_all()
        self.hog_pids = {name: pids for name, _mb, pids in hogs}
        for name, mb, pids in hogs:
            self.hog_rows[name].show_state("alert" if mb >= 4096 else "on" if mb >= 1024 else "off",
                                           f"{len(pids)} proc  ·  {human(mb)}" if len(pids) > 1 else human(mb))
        total = sum(mb for _n, mb, _p in hogs)
        self.hogs_meta.set_text(f"{human(total)} in top 5")

    def _kill_hog(self, name):
        pids = self.hog_pids.get(name, [])
        Job(lambda: kill_procs(pids), lambda _r: self.hogs_job.kick()).kick()

    def _apply_services(self, snap):
        state, supa = snap
        d_on, d_mb = state.get("docker.service", (False, 0.0))
        c_mb = state.get("containerd.service", (False, 0.0))[1]
        total = d_mb + c_mb if d_on else 0.0
        self.docker_row.update(d_on, human(d_mb + c_mb) if d_on else "off")
        new = {p: wd for p, (_mb, wd) in supa.items() if wd and self.supa_seen.get(p) != wd}
        if new:
            for p, wd in new.items():
                self.supa_seen[p] = wd
                if p in self.supa_rows:  # moved folder: rebuild its row
                    self.supa_rows.pop(p).destroy()
                self._add_supa_row(p)
            save_seen_projects(self.supa_seen)
        for proj, row in self.supa_rows.items():
            on = proj in supa
            mb = supa[proj][0] if on else 0.0
            row.update(on, human(mb) if on else ("off" if d_on else "needs Docker"))
            total += mb
        for unit, row in self.pg_rows.items():
            on, mb = state.get(unit, (False, 0.0))
            row.update(on, human(mb) if on else "off")
            total += mb if on else 0.0
        self.stack_total.set_text(f"{human(total)} in use" if total else "all off")

    # audio --------------------------------------------------------------------
    def _build_audio(self):
        t = tile("Audio")
        # One chip per device with a short name; the active one is highlighted.
        self.chips = {}      # kind -> FlowBox
        self.chip_keys = {}  # kind -> tuple of device names currently shown
        for tag, kind in (("Output", "output"), ("Microphone", "input")):
            t.pack_start(label(tag, "field"), False, False, 0)
            flow = css(Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8,
                                   row_spacing=8, max_children_per_line=4), "chips")
            flow.set_homogeneous(False)
            self.chips[kind] = flow
            t.pack_start(flow, False, False, 0)
        t.pack_start(Gtk.Box(), True, True, 0)  # push rows to the bottom
        self.mic_row = Row("Mic", lambda: self.keys.handle("mic-mute"))
        self.ee_row = Row("Sound enhancement", self._toggle_easyeffects)
        t.pack_start(self.mic_row, False, False, 0)
        t.pack_start(self.ee_row, False, False, 0)
        return t

    def _pick(self, kind, name):
        # Highlight immediately; the pactl event that follows confirms it.
        for chip in self.chips[kind].get_children():
            set_class(chip.get_child(), "active", chip.get_child().device == name)
        spawn(AUDIO_SWITCH, "set", kind, name)

    def _toggle_easyeffects(self):
        if self.ee_row.state == "on":
            spawn("easyeffects", "-q")
        else:
            spawn("easyeffects", "--gapplication-service")
        self.ee_row.show_state("busy", "…")
        later(2500, self.toggles.kick)

    def _apply_audio(self, a):
        for kind, items, current in (("output", a["outputs"], a["output"]), ("input", a["inputs"], a["input"])):
            flow = self.chips[kind]
            key = tuple(name for name, _ in items)
            if key != self.chip_keys.get(kind):  # device list changed: rebuild
                self.chip_keys[kind] = key
                for child in flow.get_children():
                    flow.remove(child)
                    child.destroy()
                for name, desc in items:
                    chip = css(Gtk.Button(label=short_device_name(name, desc, kind)), "chip")
                    chip.set_relief(Gtk.ReliefStyle.NONE)
                    chip.set_tooltip_text(
                        "AudioRelay: your phone as the PC's microphone"
                        + (" (this output plays into that mic)" if kind == "output" else "")
                        if "audiorelay" in name else desc)
                    chip.device = name
                    chip.connect("clicked", lambda _b, k=kind, n=name: self._pick(k, n))
                    flow.add(chip)
                flow.show_all()
            for child in flow.get_children():
                set_class(child.get_child(), "active", child.get_child().device == current)
        self.mic_row.show_state("alert" if a["muted"] else "on", "muted" if a["muted"] else "live")

    def _watch_audio(self):
        """Refresh audio only when PipeWire says something changed."""
        self.pactl = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, bufsize=0,
                                      preexec_fn=die_with_parent)
        self.pactl_buf = b""
        self.audio_debounce = 0
        GLib.io_add_watch(self.pactl.stdout.fileno(), GLib.PRIORITY_LOW,
                          GLib.IO_IN | GLib.IO_HUP, self._on_pactl)

    def _on_pactl(self, fd, cond):
        if cond & GLib.IO_HUP:  # PipeWire restarted: reap pactl, resubscribe
            self.pactl.wait()
            later(2000, self._watch_audio)
            self.audio_dirty = True
            return False
        self.pactl_buf += os.read(fd, 4096)
        *lines, self.pactl_buf = self.pactl_buf.split(b"\n")
        if any(re.search(rb"on (sink|source|server) ", l) for l in lines):
            if not self.visible:
                self.audio_dirty = True
            elif not self.audio_debounce:
                self.audio_debounce = GLib.timeout_add(250, self._audio_now)
        return True

    def _audio_now(self):
        self.audio_debounce = 0
        self.audio.kick()
        return False

    # controls -----------------------------------------------------------------
    def _build_controls(self):
        t = tile("Controls")
        # brightness
        line = Gtk.Box(spacing=14)
        css(line, "bright-line")
        line.pack_start(icon(G["sun"], 20, "glyph"), False, False, 0)
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bright.set_draw_value(False)
        self.bright.connect("value-changed", self._on_bright)
        self.bright.connect("button-press-event", lambda *_: setattr(self, "dragging_brightness", True))
        self.bright.connect("button-release-event", lambda *_: setattr(self, "dragging_brightness", False))
        self.dragging_brightness = False
        line.pack_start(self.bright, True, True, 0)
        self.bright_val = label("", "num", xalign=1.0)
        self.bright_val.set_size_request(44, -1)
        line.pack_end(self.bright_val, False, False, 0)
        t.pack_start(line, False, False, 0)

        # quick toggles
        row = css(Gtk.Box(spacing=10, homogeneous=True), "toggles")
        self.wifi_t = ToggleTile("Wi-Fi", G["wifi"], G["wifi_off"], self._flip_wifi)
        self.wifi_armed = 0
        self.bt_t = ToggleTile("Bluetooth", G["bt"], G["bt_off"], lambda: self._flip(BLUETOOTH, self.bt_t))
        self.dnd_t = ToggleTile("Focus", G["bell_off"], G["bell"], self._flip_dnd)
        self.settling = {}  # toggle -> time until which its click is still applying
        self.hp_t = ToggleTile("Headphones", G["headphones"], G["headphones"], self._flip_headphones)
        self.hp_t.show_state(False, "…")
        for w in (self.wifi_t, self.bt_t, self.dnd_t, self.hp_t):
            row.pack_start(w, True, True, 0)
        t.pack_start(row, True, True, 0)

        # power profile
        seg = css(Gtk.Box(homogeneous=True), "segmented")
        self.profile_btns = {}
        for key, text in (("power-saver", "Battery saver"), ("balanced", "Balanced"), ("performance", "Performance")):
            b = css(Gtk.Button(label=text), "seg")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, k=key: self._set_profile(k))
            self.profile_btns[key] = b
            seg.pack_start(b, True, True, 0)
        t.pack_start(seg, False, False, 0)
        return t

    def _on_bright(self, scale):
        if not self.syncing:
            pct = self.backlight.set_pct(round(scale.get_value()))
            self.bright_val.set_text(f"{pct}%")

    def _show_brightness(self, pct):
        self.syncing = True
        self.bright.set_value(pct)
        self.syncing = False
        self.bright_val.set_text(f"{pct}%")

    # Toggles flip instantly (optimistic), then refreshes confirm. For a few
    # seconds after a click a refresh that disagrees is ignored, because the
    # hardware (e.g. Bluetooth powering up) takes a moment to catch up.
    SETTLE = 3.0

    def _optimistic(self, toggle, on, text, settle=SETTLE):
        toggle.show_state(on, text)
        self.settling[toggle] = time.monotonic() + settle
        later(int(settle * 1000) + 100, self.toggles.kick)

    def _settled(self, toggle, on, text):
        if time.monotonic() < self.settling.get(toggle, 0) and on != toggle.on:
            return  # still applying the user's click
        toggle.show_state(on, text)

    def _flip(self, prop, toggle):
        want = not toggle.on
        dbus_set(*prop, GLib.Variant("b", want))
        self._optimistic(toggle, want, "On" if want else "Off")

    def _flip_wifi(self):
        """Turning Wi-Fi *off* needs a second click within 3 s (easy to hit by accident)."""
        t = self.wifi_t
        if t.on and not self.wifi_armed:
            set_class(t, "armed", True)
            t.state_lbl.set_text("Click again to turn off")
            self.wifi_armed = GLib.timeout_add(3000, self._disarm_wifi)
            return
        if self.wifi_armed:
            GLib.source_remove(self.wifi_armed)
            self._disarm_wifi()
        self._flip(WIFI, t)

    def _disarm_wifi(self):
        self.wifi_armed = 0
        set_class(self.wifi_t, "armed", False)
        self.wifi_t.state_lbl.set_text("On" if self.wifi_t.on else "Off")
        return False

    def _flip_dnd(self):
        want = not self.dnd_t.on
        dbus_set(*DND, GLib.Variant("u", 50 if want else 0))
        self._optimistic(self.dnd_t, want, "On" if want else "Off", settle=0.5)

    def _flip_headphones(self):
        spawn(BT_HEADPHONES)  # connects if disconnected, else disconnects
        self._optimistic(self.hp_t, self.hp_t.on,
                         "Disconnecting…" if self.hp_t.on else "Connecting…", settle=8.0)
        later(2500, self.toggles.kick)
        later(5000, self.toggles.kick)

    def _set_profile(self, key):
        dbus_set(*PROFILE, GLib.Variant("s", key))
        later(500, self.toggles.kick)

    def _apply_toggles(self, t):
        self._settled(self.wifi_t, t["wifi"], "On" if t["wifi"] else "Off")
        self._settled(self.bt_t, t["bt"], "On" if t["bt"] else "Off")
        self._settled(self.dnd_t, t["dnd"], "On" if t["dnd"] else "Off")
        hp = t["headphones"]
        if time.monotonic() >= self.settling.get(self.hp_t, 0) or hp["connected"] != self.hp_t.on:
            self.settling.pop(self.hp_t, None)
            self.hp_t.show_state(hp["connected"], (f"Connected · {hp['battery']}%" if hp["battery"] is not None
                                                   else "Connected") if hp["connected"] else "Not connected")
        self.ee_row.show_state("on" if t["easyeffects"] else "off", "on" if t["easyeffects"] else "off")
        for key, b in self.profile_btns.items():
            set_class(b, "active", key == t["profile"])
        # network identity lives here (D-Bus), rates in _refresh_net (/sys)
        self.ssid_lbl.set_text(t["ssid"] or ("Wired" if self.iface and not self.iface.startswith("wl") else "Offline"))
        q = wifi_quality(self.iface) if self.iface else None
        bars = "" if q is None else "  ·  signal " + "▮" * round(q * 4) + "▯" * (4 - round(q * 4))
        self.net_sub.set_text(f"{self.iface or '—'}  ·  {t['ip']}{bars}")


def output_geometry(name):
    out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith(name + " ") and " connected" in line:
            m = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", line)
            if m:
                return tuple(map(int, m.groups()))
    return None


def main():
    # The dashboard/OSD icons are drawn for Adwaita's symbolic set; keep it
    # even though apps use Papirus (its symbolic icons are smaller/different).
    Gtk.Settings.get_default().set_property("gtk-icon-theme-name", "Adwaita")
    provider = Gtk.CssProvider()
    provider.load_from_path(os.path.join(HERE, "dashboard.css"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    if PREVIEW:  # off-screen render for screenshots: no keys, no i3, no power
        dash = Dashboard(output_geometry(OUTPUT) or (1920, 1080, 0, 0), Backlight())
        dash.keys = None
        dash.show_all()
        dash.set_visible_state(True)
        Gtk.main()
        return
    try:
        i3 = I3()
    except OSError as e:
        print("dashboard: i3 IPC unavailable:", e)
        i3 = None
    backlight = Backlight()
    osd = Osd(i3)

    dash = None
    geom = output_geometry(OUTPUT)
    if geom:
        dash = Dashboard(geom, backlight)
        dash.show_all()
    keys = Keys(osd, backlight, lambda pct: dash and dash._show_brightness(pct))
    power = PowerAuto(dash.toggles.kick if dash else None)  # noqa: F841 (keeps the subscription alive)
    if dash:
        dash.keys = keys
        if FORCE_VISIBLE or not i3:
            dash.set_visible_state(True)
        else:
            i3.watch(dash.set_visible_state)
    try:
        Gtk.main()
    finally:
        if dash:
            dash.pactl.terminate()


if __name__ == "__main__":
    main()
