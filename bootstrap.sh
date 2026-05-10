#!/bin/sh
# Builds an oco-builder bootstrap environment inside a void-{glibc,musl}-full
# container. Run by .github/workflows/build.yml, which mounts this repo at
# /tmp/oco-builder and passes:
#   NAME       target arch (x86_64 | x86_64-musl | aarch64 | aarch64-musl)
#   EXTRA_PKGS optional extra host packages (e.g. pandoc on x86_64)
set -eu

OCO_REPO="https://repo.osowoso.org/${NAME}"

mkdir -p /etc/xbps.d
cp /usr/share/xbps.d/*-repository-*.conf /etc/xbps.d/
sed -i 's|repo-default|repo-ci|g' /etc/xbps.d/*-repository-*.conf
xbps-install -Syu xbps
xbps-install -yu
# shellcheck disable=SC2086
xbps-install -y sudo bash curl fuse3 git python3 rclone rsync xtools zstd ${EXTRA_PKGS:-}

useradd -G xbuilder -M builder

git clone --depth 1 https://github.com/void-linux/void-packages.git /void-packages
chown -R builder:builder /void-packages
cd /void-packages

sudo -Eu builder common/travis/set_mirror.sh
sudo -Eu builder common/travis/prepare.sh
common/travis/fetch-xtools.sh

# prepare.sh already wrote XBPS_BUILD_ENVIRONMENT, XBPS_ALLOW_RESTRICTED
# and XBPS_CHROOT_CMD=uchroot into etc/conf and binary-bootstrapped the
# masterdir with that chroot style. Keep it (it is what void-packages own
# CI uses in --privileged containers); switching to ethereal here would
# point xbps-src at a plain `masterdir` that does not exist in the image.
cat >> etc/conf <<'EOF'
XBPS_CCACHE=yes
XBPS_UPDATE_CHECK_VERBOSE=yes
EOF

echo "repository=${OCO_REPO}" > /etc/xbps.d/oco.conf
echo y | xbps-install -S

for md in /void-packages/masterdir-*/; do
	[ -d "$md" ] || continue
	mkdir -p "${md}etc/xbps.d" "${md}var/db/xbps/keys"
	cp /var/db/xbps/keys/*.plist "${md}var/db/xbps/keys/"
	echo "repository=${OCO_REPO}" > "${md}etc/xbps.d/oco.conf"
done

chown -R builder:builder .
rm -rf hostdir/sources/* masterdir-*/var/cache/xbps/*
