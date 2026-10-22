#!/usr/bin/env bash
# The [x] bracket trick stops pkill from matching this script's own command line.
pkill -f "[u]vicorn app.main:app" || true
pkill -f "[n]ext start" || true
pkill -f "[n]ext-server" || true
echo "stopped"
