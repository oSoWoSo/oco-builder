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

cat >> etc/conf <<'EOF'
XBPS_CCACHE=yes
XBPS_UPDATE_CHECK_VERBOSE=yes
EOF

echo "repository=${OCO_REPO}" > /etc/xbps.d/oco.conf

mkdir -p /var/db/xbps/keys
mkdir -p common/repo-keys
# The public key shipped in oco-repo-key.plist is DER-encoded, but xbps can
# only verify package signatures with a PEM key plist (see lib/verifysig.c
# PEM_read_bio_RSA_PUBKEY). Normalize it the same way xbps does on key import.
OCO_KEY="/var/db/xbps/keys/df:ec:10:ef:5c:03:e9:e0:9e:86:77:08:c2:b5:a8:cb.plist"
OCO_KEY_RAW=/tmp/oco-repo-key.plist
curl -fsSL "https://raw.githubusercontent.com/oSoWoSo/Void_Community_Repository/OCO/oco-repo-key.plist" \
	-o "$OCO_KEY_RAW" ||
 curl -fsSL "https://codeberg.org/oSoWoSo/oco/raw/branch/OCO/oco-repo-key.plist" \
	-o "$OCO_KEY_RAW"
tr -d '[:space:]' < "$OCO_KEY_RAW" |
	sed -n 's/.*<data>\(.*\)<\/data>.*/\1/p' | base64 -d > /tmp/oco-pub.der
openssl pkey -pubin -inform DER -in /tmp/oco-pub.der -outform PEM -out /tmp/oco-pub.pem
PEM_B64=$(base64 -w0 /tmp/oco-pub.pem)
{
	printf '<?xml version="1.0" encoding="UTF-8"?>\n'
	printf '<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
	printf '<plist version="1.0">\n<dict>\n\t<key>public-key</key>\n\t<data>%s</data>\n' "$PEM_B64"
	printf '\t<key>public-key-size</key>\n\t<integer>4096</integer>\n'
	printf '\t<key>signature-by</key>\n\t<string>oSoWoSo &lt;mail@osowoso.org&gt;</string>\n'
	printf '</dict>\n</plist>\n'
} > "$OCO_KEY"
cp "$OCO_KEY" common/repo-keys/
rm -f "$OCO_KEY_RAW" /tmp/oco-pub.der /tmp/oco-pub.pem

xbps_install_retry() {
	local max=3 delay=5 i
	for i in $(seq 1 $max); do
		echo "==> xbps-install -S -y (attempt $i/$max)"
		xbps-install -S -y && return 0
		[ "$i" -lt "$max" ] && sleep "$delay"
	done
	return 1
}
xbps_install_retry
xbps-install -y -R "$OCO_REPO" cosign
# Fail the image build rather than ship one without cosign: every manifest
command -v cosign >/dev/null 2>&1 || {
	echo "==> ERROR: cosign was not installed from ${OCO_REPO}" >&2
	exit 1
}

for md in /void-packages/masterdir-*/; do
	[ -d "$md" ] || continue
	mkdir -p "${md}etc/xbps.d" "${md}var/db/xbps/keys"
	cp /var/db/xbps/keys/*.plist "${md}var/db/xbps/keys/"
	echo "repository=${OCO_REPO}" > "${md}etc/xbps.d/oco.conf"
done

chown -R builder:builder .
rm -rf hostdir/sources/* masterdir-*/var/cache/xbps/*
