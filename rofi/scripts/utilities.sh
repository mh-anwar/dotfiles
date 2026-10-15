#!/usr/bin/env bash
# Curated, local-first utility launcher for Rofi's script mode.

if [[ "${ROFI_RETV:-0}" -eq 1 ]]; then
    case "${ROFI_INFO:-}" in
        pdf)       setsid gtk-launch com.github.muriloventuroso.pdftricks >/dev/null 2>&1 & ;;
        video)     setsid gtk-launch org.gnome.gitlab.YaLTeR.VideoTrimmer >/dev/null 2>&1 & ;;
        image)     setsid gtk-launch io.gitlab.adhami3310.Converter >/dev/null 2>&1 & ;;
        screenshot) setsid gtk-launch kazam >/dev/null 2>&1 & ;;
        capture)   setsid gtk-launch org.flameshot.Flameshot >/dev/null 2>&1 & ;;
        scan)      setsid gtk-launch org.gnome.SimpleScan >/dev/null 2>&1 & ;;
        scanpdf)   setsid gtk-launch gscan2pdf >/dev/null 2>&1 & ;;
        documents) setsid gtk-launch org.gnome.Papers >/dev/null 2>&1 & ;;
        storage)   setsid gtk-launch org.gnome.baobab >/dev/null 2>&1 & ;;
        disks)     setsid gtk-launch org.gnome.DiskUtility >/dev/null 2>&1 & ;;
        partitions) setsid gtk-launch gparted >/dev/null 2>&1 & ;;
    esac
    exit 0
fi

printf '\0markup-rows\x1ftrue\n'
entry() {
    # A row has one NUL after its search text; all of its properties are then
    # separated by Unit Separator (0x1f).  Extra NULs make Rofi ignore `icon`.
    printf '%s\0display\x1f%s\x1fmeta\x1f%s\x1ficon\x1f%s\x1finfo\x1f%s\n' "$1" "$2" "$3" "$4" "$5"
}

entry 'PDF Tricks' '<b>PDF Tricks</b>&#10;<span size="small" weight="light">Merge, split, compress, and convert PDFs locally</span>' 'pdf merge split compress convert document' '/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps/com.github.muriloventuroso.pdftricks.svg' pdf
entry 'Video Trimmer' '<b>Video Trimmer</b>&#10;<span size="small" weight="light">Cut and shorten videos locally</span>' 'video trim cut clip shorten' '/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps/org.gnome.gitlab.YaLTeR.VideoTrimmer.svg' video
entry 'Switcheroo' '<b>Switcheroo</b>&#10;<span size="small" weight="light">Convert, resize, and compress images locally</span>' 'image convert resize compress webp png jpg' '/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps/io.gitlab.adhami3310.Converter.svg' image
entry 'Kazam' '<b>Kazam</b>&#10;<span size="small" weight="light">Record your screen or take screenshots</span>' 'screen record recording screenshot capture video' '/usr/share/icons/hicolor/64x64/icons/kazam.png' screenshot
entry 'Flameshot' '<b>Flameshot</b>&#10;<span size="small" weight="light">Capture and annotate screenshots</span>' 'screenshot screen capture annotate' '/usr/share/icons/hicolor/scalable/apps/flameshot.svg' capture
entry 'Simple Scan' '<b>Simple Scan</b>&#10;<span size="small" weight="light">Scan documents from a connected scanner</span>' 'scan scanner document' '/usr/share/icons/hicolor/scalable/apps/org.gnome.SimpleScan.svg' scan
entry 'gscan2pdf' '<b>gscan2pdf</b>&#10;<span size="small" weight="light">Scan and assemble multi-page PDFs</span>' 'scan pdf ocr document' '/usr/share/pixmaps/gscan2pdf.svg' scanpdf
entry 'Papers' '<b>Papers</b>&#10;<span size="small" weight="light">Read PDFs and other documents</span>' 'pdf document reader viewer' '/usr/share/icons/hicolor/scalable/apps/org.gnome.Papers.svg' documents
entry 'Disk Usage Analyzer' '<b>Disk Usage Analyzer</b>&#10;<span size="small" weight="light">Find files and folders using disk space</span>' 'disk storage space folders baobab' '/usr/share/icons/hicolor/scalable/apps/org.gnome.baobab.svg' storage
entry 'Disks' '<b>Disks</b>&#10;<span size="small" weight="light">Manage drives, mounts, SMART data, and disk images</span>' 'disk drive mount smart usb storage' '/usr/share/icons/hicolor/scalable/apps/org.gnome.DiskUtility.svg' disks
entry 'GParted' '<b>GParted</b>&#10;<span size="small" weight="light">Create and resize disk partitions</span>' 'partition disk resize format drive' '/usr/share/icons/Yaru/48x48/apps/gparted.png' partitions
