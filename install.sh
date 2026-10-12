#!/usr/bin/env bash
# Installs ScreenCap: menu entry, autostart on login, and Cinnamon hotkeys.
#   ./install.sh            install
#   ./install.sh --uninstall
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/screencap.py"
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"
KB=/org/cinnamon/desktop/keybindings

# name | command flag | binding
HOTKEYS=(
  "ScreenCap: screenshot area|--screenshot-area|<Super><Shift>s"
  "ScreenCap: screenshot full screen|--screenshot-full|<Super><Shift>f"
  "ScreenCap: record area (toggle)|--record-area|<Super><Shift>r"
  "ScreenCap: record full screen (toggle)|--record-full|<Super><Shift>v"
)

remove_hotkeys() {
  command -v dconf >/dev/null || return 0
  local list new=()
  list=$(dconf read "$KB/custom-list" | tr -d "[]',@as" )
  for id in $list; do
    if [[ "$(dconf read "$KB/custom-keybindings/$id/command")" == *screencap.py* ]]; then
      dconf reset -f "$KB/custom-keybindings/$id/"
    else
      new+=("'$id'")
    fi
  done
  dconf write "$KB/custom-list" "@as [$(IFS=,; echo "${new[*]}")]"
}

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$APPS/screencap.desktop" "$AUTOSTART/screencap.desktop"
  remove_hotkeys
  pkill -f "$BIN" || true
  echo "ScreenCap uninstalled."
  exit 0
fi

chmod +x "$BIN"
mkdir -p "$APPS" "$AUTOSTART"
cat > "$APPS/screencap.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ScreenCap
Comment=Take screenshots and record the screen
Exec=$BIN
Icon=applets-screenshooter
Categories=Utility;Graphics;
Terminal=false
EOF
cp "$APPS/screencap.desktop" "$AUTOSTART/screencap.desktop"

if command -v dconf >/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" == *Cinnamon* ]]; then
  remove_hotkeys
  ids=$(dconf read "$KB/custom-list" | tr -d "[]',@as")
  n=0
  for entry in "${HOTKEYS[@]}"; do
    IFS='|' read -r name flag binding <<<"$entry"
    while [[ " $ids " == *" custom$n "* ]]; do n=$((n + 1)); done
    id="custom$n"; ids="$ids $id"
    dconf write "$KB/custom-keybindings/$id/name" "'$name'"
    dconf write "$KB/custom-keybindings/$id/command" "'$BIN $flag'"
    dconf write "$KB/custom-keybindings/$id/binding" "['$binding']"
  done
  list=$(for i in $ids; do printf "'%s'," "$i"; done)
  dconf write "$KB/custom-list" "[${list%,}]"
  echo "Hotkeys: Super+Shift+S area shot · Super+Shift+F full shot · Super+Shift+R record area · Super+Shift+V record full"
fi

pgrep -f "$BIN" >/dev/null || (nohup "$BIN" >/dev/null 2>&1 &)
echo "ScreenCap installed and running (look for the camera icon in your panel)."
