#!/bin/sh
# Per-job refresh inside an oco-builder image: update host packages and the
# void-packages bootstrap masterdir against the current remote repositories.

set -eu

xbps-install -Suvy
sudo -Eu builder sh -c 'cd /void-packages && ./xbps-src bootstrap-update'
