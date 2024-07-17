# dotfiles
This repository contains important/custom linux application configs (specifically, i3, polybar and rofi).

# Firefox
In `~/.mozilla/<profilecode>` add a directory `chrome` and within it create a `userChrome.css` file. Add:
```
#navigator-toolbox[inFullscreen="true"] #PersonalToolbar {
  visibility: unset !important;
}
```
## Installs:
- i3 (as well as betterlockscreen)
- dunst
- polybar
- pamixer + pavucontrol
- brave
- firefox
- keepassxc
- kdeconnect
- zsh (ohmyzsh)
- lyrebird
- LyX
- calibre
- flameshot
- solaar


# Random Fixes
- Backlight issues:
 - `sudo chmod +s $(which brightnessctl)` [Github Issue](https://github.com/i3/i3/discussions/4763)
 - [Changing GRUB Config](https://www.reddit.com/r/linuxquestions/comments/1cf7vu1/the_solution_to_brightness_issue_for_amd_apu/)
 - [i3 Config Change (Keybinds)](https://github.com/particleofmass/i3wm_screen_brightness)
 - [Arch Backlight Wiki](https://wiki.archlinux.org/title/backlight)
 - amdgpu_bl0 randomly changed to amdgpu_bl1 after upgrading to Ubuntu 24
 - [Random Scripts That I Use](https://unix.stackexchange.com/questions/322814/xf86monbrightnessup-xf86monbrightnessdown-special-keys-not-working)
