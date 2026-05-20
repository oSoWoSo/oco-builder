# oco-builder

Bootstrap Docker images for building binary packages for [repo.osowoso.org](https://repo.osowoso.org/) — the binary repository of [Void Community Repository](https://codeberg.org/oSoWoSo/oco) (VUR).

Templates live at [codeberg.org/oSoWoSo/oco](https://codeberg.org/oSoWoSo/oco), binaries are built via CI at [github.com/oSoWoSo/Void_Community_Repository](https://github.com/oSoWoSo/Void_Community_Repository) using these images.

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

Each image starts from the official `ghcr.io/void-linux/void-*-full` base, runs `xbps-src binary-bootstrap` with `--privileged` (required for chroot mount capabilities), then is committed as a ready-to-use build environment.

## Bundled tools

In addition to the void base + `xbps-src`, the images include:

- `sudo`, `bash`, `curl`, `git` -- core build needs
- `python3` -- runtime for repodata helpers in `oSoWoSo/oco`
- `rclone` -- manage files on cloud storage
- `fuse3` -- filesystem in userspace
- `zstd` -- CLI for round-tripping zstd-compressed repodata
- `pandoc` -- README → HTML for the oco website generator (x86\_64 only; not packaged for all archs in void)
