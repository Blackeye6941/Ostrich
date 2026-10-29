echo $DBUS_SESSION_BUS_ADDRESS
echo $XDG_SESSION_TYPE
echo $DISPLAY $WAYLAND_DISPLAY
ps aux | grep -E "at-spi|dbus" | grep -v grep
gsettings get org.gnome.desktop.interface toolkit-accessibility
