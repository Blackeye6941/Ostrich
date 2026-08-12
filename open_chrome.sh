#!/bin/bash
if command -v google-chrome-stable &> /dev/null; then
    google-chrome-stable &
elif command -v google-chrome &> /dev/null; then
    google-chrome &
elif command -v chromium &> /dev/null; then
    chromium &
elif command -v chromium-browser &> /dev/null; then
    chromium-browser &
else
    xdg-open "https://www.google.com" &
fi
