# Dotfiles - i3 Desktop Environment

This is a `~/.config` dotfiles repo for an i3wm-based Linux desktop (Ubuntu/Debian). Each component is independent — install only what you want. Copy the relevant directory into your `~/.config/`.

## Theme: TrueBlack + Tokyo Night

The shared color palette across components is Tokyo Night on true-black backgrounds. No transparency, no gaps.

### Color Palette
- Background: `#16161e` (polybar), `#1a1a1a` (GTK)
- Foreground: `#c0caf5`
- Primary/Accent: `#7aa2f7` (blue)
- Secondary: `#9ece6a` (green)
- Alert: `#f7768e` (red)
- Cyan: `#7dcfff`, Magenta: `#bb9af7`, Orange: `#e0af68`

---

## Components

Each section is self-contained. Dependencies listed are only for that component.

### GTK Theme (TrueBlack)

True black GTK 2/3/4 theme with rounded menus, blue accents, and no transparency.

```bash
# Copy theme and settings
cp -r themes/TrueBlack ~/.themes/TrueBlack
cp -r gtk-3.0/ ~/.config/gtk-3.0/
```

The `gtk-3.0/settings.ini` sets TrueBlack as the active theme, Inter font, and dark mode. Install dependencies:
```bash
sudo apt install -y fonts-inter lxappearance
```

Use `lxappearance` to preview or switch GTK themes if needed.

### i3 Window Manager

Tiling WM config — no gaps, no borders, Super as mod key.

```bash
sudo apt install -y i3 feh
cp -r i3/ ~/.config/i3/
```

- **Terminal**: expects `kitty` (install separately or change `bindsym $mod+Return`)
- **Launcher**: expects `rofi` (install separately or change `bindsym $mod+d`)
- **Compositor**: expects `picom` (install separately or remove the `picom` exec line)
- **Bar**: expects `polybar` (install separately or remove the polybar launch line)
- **Wallpapers**: included as `.jpg`/`.png` files in `i3/`. Set via `feh --bg-scale`. Each argument is one monitor left to right.
- **Lock screen**: uses `i3lock-multimonitor` — clone from https://github.com/shikherverma/i3lock-multimonitor into `~/.config/i3/i3lock-multimonitor/`, or remove the lock keybind.

To use i3 standalone without the other components, comment out the `exec` lines for picom, polybar, and rofi in the config.

### Polybar

Bottom bar with Tokyo Night colors. Launches on all connected monitors.

```bash
sudo apt install -y polybar
cp -r polybar/ ~/.config/polybar/
chmod +x ~/.config/polybar/launch.sh ~/.config/polybar/polybar-scripts/*.sh
```

Requires `fonts-inter` or another font — adjust `config.ini` if using a different one.

### Picom

Compositor for rounded corners (10px) and shadows. No transparency/opacity effects.

```bash
sudo apt install -y picom
cp -r picom/ ~/.config/picom/
```

Uses GLX backend. If you have issues, change `backend = "glx"` to `"xrender"` in `picom.conf`.

### Kitty

Terminal emulator config — Fira Code font at 12pt.

```bash
sudo apt install -y kitty fonts-firacode
cp -r kitty/ ~/.config/kitty/
```

### Rofi

App launcher and power menu. Uses the adi1090x/rofi theme collection.

```bash
sudo apt install -y rofi
cp -r rofi/ ~/.config/rofi/
chmod +x ~/.config/rofi/scripts/* ~/.config/rofi/launchers/*/launcher.sh ~/.config/rofi/powermenu/*/powermenu.sh ~/.config/rofi/applets/bin/*.sh
```

Requires Papirus icon theme for icons:
```bash
sudo apt install -y papirus-icon-theme
```

### Neovim

NvChad-based config.

```bash
sudo apt install -y neovim
cp -r nvim/ ~/.config/nvim/
```

On first launch, Lazy.nvim will auto-install plugins.

### Flameshot

Screenshot tool config.

```bash
sudo apt install -y flameshot
cp -r flameshot/ ~/.config/flameshot/
```

### Lyrebird

Voice changer presets.

```bash
sudo apt install -y lyrebird
cp -r lyrebird/ ~/.config/lyrebird/
```

---

## Key Design Decisions

- **No gaps** between tiled windows — all screen space is used
- **No transparency/opacity** on any windows
- **No window borders** (`border pixel 0`)
- **Rounded corners** via picom (10px), not i3
- **Shadows** via picom on all windows except dock/desktop/polybar
- **Bottom bar** (polybar), not top
- **Mod key** is Super (Windows key)
