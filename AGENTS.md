# Dotfiles - i3 Desktop Environment

`~/.config` dotfiles for an i3wm desktop on Ubuntu/Debian. Only these are tracked in git: `i3`, `polybar`, `dunst`, `picom`, `rofi`, `kitty`, `nvim`, `gtk-3.0`, `themes/TrueBlack`, `flameshot`, `lyrebird`, `pavucontrol.ini`. Everything else in `~/.config` is app state — ignore it.

## How to Work With Me

**Responses** — short, no walls of text. Use these sections (skip any that are empty):
- **Summary** — what you did, 1–3 bullets
- **Actions for you** — commands I need to run, things to reload/test (e.g. `$mod+Shift+r`)
- **Notes** — caveats or open questions, only if they matter

Lead with the conclusion. No deep technical explanations unless I ask.

**Efficiency**
- Don't overthink. For small changes, read the relevant file, make the edit, done.
- Don't explore the whole repo or re-read files you just edited.
- Fix the specific thing I asked about — don't refactor, rename, or remove features unless asked.
- If something is genuinely ambiguous, ask one short question instead of guessing big.


## Components

### i3 (`i3/`)
- Terminal `kitty`, launcher `rofi/scripts/launcher_dune_random` (`$mod+d`)
- Wallpapers set per-monitor with `feh --bg-scale` (args = monitors left→right)
- `monitors.sh` — xrandr layout: laptop (eDP) + DisplayPort-0 + HDMI-A-0, all 1080p
- Idle lock: `xss-lock` → `lock-if-idle.sh` (skips if audio playing or fullscreen) → `betterlockscreen`
- Manual lock `$mod+Shift+p`: `i3lock-multimonitor` (clone into `i3/i3lock-multimonitor/`)
- `osd.sh` — volume/brightness/mic keys; forwards to the dashboard process (D-Bus `dev.mohammad.Osd`), which applies the change and shows the Windows-style bottom-centre popup. Falls back to plain pactl/brightnessctl if the dashboard isn't running
- `docker-toggle.sh` — helper script
- Dashboard (`~/.config/dashboard/`, not in this repo): full-screen bento grid on workspace 0 (`$mod+``, pinned to eDP). Workspace 0 is dashboard-only: apps opened there get moved to the previous workspace. Holds network, uptime, brightness (moved off polybar)
- Notifications: `dunst` (`dunst/dunstrc`) — left-click opens the app; `$mod+n` last notification, `$mod+Shift+n` dismiss all. `focus_on_window_activation focus` so clicks jump to the app's workspace
- Autostarts: picom, polybar, dunst, nm-applet, blueman, flameshot, copyq, kdeconnect, udiskie, easyeffects, keepassxc, polkit-gnome, firefox, `~/.config/dashboard/launch.sh` (not in this repo)

### Polybar (`polybar/`)
- Bar `the_one_bar`, launched on every monitor by `launch.sh`
- Fonts: JetBrains Mono NL + Font Awesome 6 Free
- Custom modules in `polybar-scripts/` (clock, cpu, mem, network, brightness, bluetooth, mic, fan, thermal, uptime)
- Script deps: `pactl`, `bluetoothctl`, `brightnessctl`, `sensors`, `playerctl`, `notify-send`

### Picom (`picom/picom.conf`)
- GLX backend (use `xrender` if it misbehaves). Needs picom v12+ for the animation block.

### Rofi (`rofi/`)
- adi1090x theme collection; custom launcher style `launchers/type-6/style-1-dune.rasi`
- Extra scripts in `scripts/`: `audio-switch.sh`, `clipboard.sh` (copyq), `utilities.sh`
- Icons: `papirus-icon-theme`

### GTK (`themes/TrueBlack`, `gtk-3.0/`)
- adw-gtk3-dark (GTK3) + stock libadwaita (GTK4), recoloured graphite in `gtk-*/gtk.css`; Inter 11, Adwaita icons and cursor (Papirus tried, rejected). TrueBlack is kept but unused
- Install theme to `~/.themes/TrueBlack`

### Others
- **kitty** — Fira Code 12pt
- **nvim** — NvChad + Lazy.nvim
- **flameshot**, **lyrebird**, **pavucontrol** — app settings only

## Install Deps (Ubuntu)

```bash
sudo apt install -y i3 feh polybar picom rofi kitty neovim flameshot copyq \
  xss-lock dunst easyeffects blueman udiskie brightnessctl playerctl lm-sensors \
  fonts-inter fonts-firacode fonts-jetbrains-mono fonts-font-awesome papirus-icon-theme
```
`betterlockscreen` and `i3lock-multimonitor` are installed manually.
