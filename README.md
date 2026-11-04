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

```sh
docker run --privileged --rm ghcr.io/osowoso/oco-builder-x86_64 \
  ./xbps-src pkg <template>
```

## How it works

Each image starts from the official `ghcr.io/void-linux/void-*-full` base — pinned by digest in `.github/workflows/build.yml` — runs `xbps-src binary-bootstrap` with `--privileged` (required for chroot mount capabilities), then is smoke tested and committed as a ready-to-use build environment. Every image also carries a `base-<digest>` tag naming the Void release it was built from.

## Bundled tools

In addition to the void base + `xbps-src`, the images include:

- `sudo`, `bash`, `curl`, `git` -- core build needs
- `nodejs` -- for surfer-cli
- `python3` -- runtime for repodata helpers in `oSoWoSo/oco`
- `surfer-cli` -- for managing repository
- `zstd` -- CLI for round-tripping zstd-compressed repodata

The `aarch64-musl` image additionally preloads a small `fcntl64` ABI bridge
for GitHub Actions' glibc-linked ARM Node runtime; other images are unchanged.

x86\_64 only
- `pandoc` -- README → HTML for the oco website generator

## Package update feed

The package update feed CI previously lived here (`.github/feedsparser.py` +
`.github/workflows/feeds.yml`). It has moved to the
[OCO repository](https://github.com/oSoWoSo/oco) (`.github/workflows/feed-update.yml`,
`src/feedsparser.py`) and is deprecated here: those files are gone and the
workflow no longer runs from this repo.
