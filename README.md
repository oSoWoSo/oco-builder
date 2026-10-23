# oco-builder

Bootstrap Docker images for building binary packages for [repo.osowoso.org](https://repo.osowoso.org/)

Templates live at [OCO](https://github.com/oSoWoSo/oco) (mirrored to [Codeberg](https://codeberg.org/oSoWoSo/oco)); binaries are built via CI on GitHub using these images.

## Images

Published to GHCR, updated daily at 03:00 UTC.

| Image | Architecture | libc |
|-------|-------------|------|
| `ghcr.io/osowoso/oco-builder-x86_64` | x86\_64 | glibc |
| `ghcr.io/osowoso/oco-builder-x86_64-musl` | x86\_64 | musl |
| `ghcr.io/osowoso/oco-builder-aarch64` | aarch64 | glibc |
| `ghcr.io/osowoso/oco-builder-aarch64-musl` | aarch64 | musl |

## Usage

Builds inside the image use the `ethereal` xbps-src chroot-style: the
disposable container rootfs itself acts as the masterdir, so no
`--privileged` and no mount namespaces are needed — only root inside
the container.  `oco-prepare` sets everything up:

```sh
docker run --rm ghcr.io/osowoso/oco-builder-x86_64 \
  sh -euc 'oco-prepare && cd /oco-tree && ./xbps-src pkg <template>'
```

Do not bind-mount the package tree at `/void-packages`: the ethereal
chroot-style owns that path (it symlinks it to the tree and empties it
after every invocation).  The tree lives at `/oco-tree`.

## How it works

Each image starts from the official `ghcr.io/void-linux/void-*-full` base — pinned by digest in `.github/workflows/build.yml` — runs `xbps-src binary-bootstrap` with `--privileged` (required for chroot mount capabilities during the image build only), installs `base-chroot` into the container rootfs, and is smoke tested and committed as a ready-to-use build environment. Every image also carries a `base-<digest>` tag naming the Void release it was built from.

Package builds run via the `ethereal` chroot-style: `oco-prepare`
symlinks `/oco-tree/masterdir -> /`, appends
`XBPS_CHROOT_CMD=ethereal` + `XBPS_ALLOW_CHROOT_BREAKOUT=yes` to
`etc/conf`, and refreshes `base-chroot`.  xbps-src then builds directly
in the container rootfs as root — no mount namespaces, so unprivileged
runners (e.g. the shared Codeberg Forgejo runners, which drop
`--privileged`) work fine.

## Bundled tools

In addition to the void base + `xbps-src`, the images include:

- `base-chroot` -- the build toolchain, installed into the container
  rootfs because ethereal builds happen in the container itself
- `sudo`, `bash`, `curl`, `git` -- core build needs
- `nodejs` -- for surfer-cli
- `python3` -- runtime for repodata helpers in `oSoWoSo/oco`
- `surfer-cli` -- for managing repository
- `zstd` -- CLI for round-tripping zstd-compressed repodata

The `aarch64-musl` image additionally preloads a small `fcntl64` ABI bridge
for GitHub Actions' glibc-linked ARM Node runtime; other images are unchanged.

x86\_64 only
- `pandoc` -- README → HTML for the oco website generator

## CI secrets

`.github/workflows/feeds.yml` reads these. Only `BOT` is required; the rest
are optional and an unset token means "fetch anonymously", which is what
happened before they existed.

| Secret | Used for |
|--------|----------|
| `BOT` | `gh` CLI operations against the OCO repo — filing and updating `package-update` issues — and the GitHub entry in `feedsparser.py`'s `HOST_AUTH` |
| `CODEBERG` | Codeberg feeds (`Authorization: token`) |
| `GITLAB` | GitLab feeds (`PRIVATE-TOKEN`) |
