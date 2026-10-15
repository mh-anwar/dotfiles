#!/usr/bin/env bash
# Search CopyQ history. Selecting an item restores it to the active clipboard.

if [[ ( "${ROFI_RETV:-0}" -eq 1 || "${ROFI_RETV:-0}" -eq 10 || "${ROFI_RETV:-0}" -eq 11 ) && "${ROFI_INFO:-}" =~ ^[0-9]+$ ]]; then
    copyq select "$ROFI_INFO" >/dev/null 2>&1
    exit 0
fi

printf '\0prompt\x1fClipboard\n\0no-custom\x1ftrue\n\0use-hot-keys\x1ftrue\n'

items=$(copyq eval -- 'var limit = Math.min(size(), 100); for (var i = 0; i < limit; ++i) { var text = str(read(mimeText, i)).replace(/[\r\n]+/g, " ").replace(/\0/g, ""); if (text.length) print(i + "\t" + text.slice(0, 300) + "\n"); }' 2>/dev/null)

if [[ -z "$items" ]]; then
    printf 'CopyQ history is unavailable\0nonselectable\x1ftrue\x1ficon\x1fdialog-warning\n'
    exit 0
fi

while IFS=$'\t' read -r index text; do
    printf '%s\0display\x1f%s\x1ficon\x1fedit-paste\x1finfo\x1f%s\n' "$text" "$text" "$index"
done <<< "$items"
