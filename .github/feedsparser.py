#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import feedparser
from packaging.version import InvalidVersion, Version


OPML_PATH = os.environ.get(
    "OPML_PATH",
    "feeds.opml",
)
OPML_URL = os.environ.get(
    "OPML_URL",
    "https://raw.githubusercontent.com/"
    "oSoWoSo/vOid_Community_repOsitory/"
    "refs/heads/OCO/src/feed.opml",
)
FOLDER_NAME = "package-update"

OCO_DIR = Path(
    os.environ["RUNNER_TEMP"]
) / "oco"

README_FILE = OCO_DIR / "README.md"
SRC_PKGS = OCO_DIR / "srcpkgs"

TARGET_REPO = os.environ["TARGET_REPO"]
ISSUE_LABEL = os.environ["OCO_LABEL"]

PACKAGES_BY_NAME = {}


VERSION_RE = re.compile(
    r"(?<![0-9])"
    r"v?"
    r"(\d+(?:\.\d+){0,5}"
    r"(?:[-+._][0-9A-Za-z.-]+)?)"
)


def log(state, name, detail=""):
    print(f"{state:<8} {name:<26} {detail}".rstrip())


def run_gh(args):
    result = subprocess.run(
        ["gh", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        print(
            result.stderr,
            file=sys.stderr,
        )

        raise RuntimeError(
            "gh command failed: "
            f"gh {' '.join(args)}"
        )

    return result.stdout


def extract_version(text):
    if not text:
        return None

    match = VERSION_RE.search(text)

    if not match:
        return None

    raw = match.group(1)

    try:
        return Version(raw)
    except InvalidVersion:
        numeric = re.match(
            r"\d+(?:\.\d+)+",
            raw,
        )

        if not numeric:
            return None

        try:
            return Version(
                numeric.group(0)
            )
        except InvalidVersion:
            return None


def parse_rules(value):
    rules = []

    if not value:
        return rules

    for line in value.splitlines():
        line = line.strip()

        if not line:
            continue

        if line.startswith("EntryTitle="):
            line = line[len("EntryTitle="):]

        try:
            rules.append(
                re.compile(line)
            )
        except re.error as exc:
            print(
                f"WARNING: invalid rule "
                f"{line!r}: {exc}",
                file=sys.stderr,
            )

    return rules


def get_outline_attribute(outline, name):
    for key, value in outline.attrib.items():
        if key.rsplit("}", 1)[-1] == name:
            return value

    return ""


def entry_allowed(
    title,
    keep_rules,
    block_rules,
):
    if keep_rules:
        if not any(
            rule.search(title)
            for rule in keep_rules
        ):
            return False

    if any(
        rule.search(title)
        for rule in block_rules
    ):
        return False

    return True


def load_opml():
    opml_path = Path(OPML_PATH)

    if opml_path.exists():
        return ET.parse(
            opml_path
        ).getroot()

    request = urllib.request.Request(
        OPML_URL,
        headers={
            "User-Agent":
                "package-update-github-action/1.0",
            "Accept": "application/xml, text/xml, */*",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        data = response.read()

    return ET.fromstring(
        data
    )


def load_feeds():
    root = load_opml()
    body = root.find("body")

    if body is None:
        raise RuntimeError(
            "OPML has no <body>"
        )

    package_folder = None

    for outline in body:
        if not outline.tag.endswith("outline"):
            continue

        if (
            outline.attrib.get("text")
            == FOLDER_NAME
        ):
            package_folder = outline
            break

    if package_folder is None:
        raise RuntimeError(
            f"OPML folder "
            f"{FOLDER_NAME!r} not found"
        )

    feeds = []

    for outline in package_folder:
        if not outline.tag.endswith("outline"):
            continue

        xml_url = outline.attrib.get(
            "xmlUrl",
            "",
        ).strip()

        if not xml_url:
            continue

        html_url = outline.attrib.get(
            "htmlUrl",
            "",
        ).strip()

        name = (
            outline.attrib.get("title")
            or outline.attrib.get("text")
            or ""
        ).strip()

        if not name:
            continue

        block_rules = []

        block_rules.extend(
            parse_rules(
                get_outline_attribute(
                    outline,
                    "blocklistRules",
                )
            )
        )

        block_rules.extend(
            parse_rules(
                get_outline_attribute(
                    outline,
                    "blockFilterEntryRules",
                )
            )
        )

        keep_rules = parse_rules(
            get_outline_attribute(
                outline,
                "keeplistRules",
            )
        )

        feeds.append(
            {
                "name": name,
                "xml_url": xml_url,
                "html_url": html_url,
                "keep_rules": keep_rules,
                "block_rules": block_rules,
            }
        )

    return feeds


def normalize_url(url):
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)

    host = parsed.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    path = parsed.path.rstrip("/")

    # Remove common repository/feed suffixes.
    suffixes = (
        "/tags.atom",
        "/releases.atom",
        "/feed.atom",
        "/atom.xml",
        "/rss.xml",
        "/feed.xml",
        "/releases",
        "/tags",
    )

    changed = True

    while changed:
        changed = False

        for suffix in suffixes:
            if path.endswith(suffix):
                path = path[:-len(suffix)].rstrip("/")
                changed = True
                break

    if path.endswith(".git"):
        path = path[:-4]

    return f"{host}{path}".lower()


def url_matches(
    feed_url,
    template_url,
):
    feed = normalize_url(feed_url)
    template = normalize_url(template_url)

    if not feed or not template:
        return False

    if feed == template:
        return True

    # This handles release/archive URLs:
    #
    # github.com/foo/bar
    # github.com/foo/bar/releases/download/...
    #
    # and similar layouts on Codeberg/GitLab.
    if template.startswith(feed + "/"):
        return True

    if feed.startswith(template + "/"):
        return True

    return False


def template_urls(template):
    text = template.read_text(
        encoding="utf-8",
        errors="replace",
    )

    return re.findall(
        r'https?://[^\s"\']+',
        text,
    )


def build_package_map():
    """
    Map every upstream repository to all OCO
    packages using that upstream.


    This is what allows:

        brave-browser
            -> brave-browser-bin
            -> brave-origin-bin


    Also records all package names so feeds whose
    name matches a template can be resolved even
    when their URLs don't line up.


    """
    global PACKAGES_BY_NAME
    mapping = {}
    packages_by_name = {}

    if not SRC_PKGS.is_dir():
        raise RuntimeError(
            f"{SRC_PKGS} does not exist"
        )

    for package_dir in sorted(SRC_PKGS.iterdir()):
        if not package_dir.is_dir():
            continue

        template = (
            package_dir / "template"
        )

        if not template.is_file():
            continue

        package = package_dir.name
        packages_by_name.setdefault(
            package.casefold(),
            package,
        )

        urls = template_urls(template)

        if not urls:
            continue

        for url in urls:
            key = normalize_url(url)

            if not key:
                continue

            mapping.setdefault(
                key,
                set(),
            ).add(package)

    PACKAGES_BY_NAME = packages_by_name

    return mapping


def find_packages_for_feed(
    feed,
    package_map,
):
    """
    Resolve a feed to OCO packages.


    URL matching first (a template can map one
    upstream to several packages, e.g. brave-browser).,
    then fall back to an exact case-insensitive name
    match so feeds whose title equals a template name
    are found even when the URLs don't line up.


    """
    packages = set()
    matched_by_name = False

    feed_urls = [
        feed["xml_url"],
        feed["html_url"],
    ]

    for key, package_names in package_map.items():
        for feed_url in feed_urls:
            if url_matches(
                feed_url,
                key,
            ):
                packages.update(
                    package_names
                )

    if not packages:
        name = feed["name"].casefold().strip()
        package = PACKAGES_BY_NAME.get(name)

        if package:
            packages.add(package)
            matched_by_name = True

    return sorted(
        packages,
        key=str.casefold,
    ), matched_by_name


def closest_package(feed_name):
    """
    Return up to two plausibly related template
    names for a feed that matched nothing,, or None.


    A candidate must contain the feed name or vice
    versa; the two closest ones are reported.


    """
    name = feed_name.casefold().strip()
    candidates = []

    for package in sorted(
        PACKAGES_BY_NAME.values(),
        key=str.casefold,
    ):
        pkg = package.casefold()

        if pkg == name:
            continue

        if pkg in name or name in pkg:
            candidates.append(package)


            if len(candidates) >= 2:
                break

    if not candidates:
        return None

    return ", ".join(candidates)


def load_repository_versions():
    versions = {}

    for line in README_FILE.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        if not line.startswith("|"):
            continue

        columns = [
            item.strip()
            for item in (
                line.strip()
                .strip("|")
                .split("|")
            )
        ]

        if len(columns) < 2:
            continue

        package = columns[0]
        version_text = columns[1]

        if (
            not package
            or package.lower()
            == "package"
            or re.fullmatch(
                r"[-: ]+",
                package,
            )
        ):
            continue

        version = extract_version(
            version_text
        )

        if version is None:
            continue

        versions[
            package.casefold()
        ] = {
            "name": package,
            "version": version,
            "version_text": version_text,
        }

    return versions


def fetch_feed(feed):
    try:
        request = urllib.request.Request(
            feed["xml_url"],
            headers={
                "User-Agent":
                    "package-update-github-action/1.0",
                "Accept": (
                    "application/atom+xml, "
                    "application/rss+xml, "
                    "application/xml, "
                    "text/xml, */*"
                ),
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            data = response.read()

        parsed = feedparser.parse(data)

        candidates = []

        for entry in parsed.entries:
            title = str(
                entry.get("title", "")
            ).strip()

            link = str(
                entry.get("link", "")
            ).strip()

            if not entry_allowed(
                title,
                feed["keep_rules"],
                feed["block_rules"],
            ):
                continue

            version = extract_version(
                title
            )

            if version is None:
                version = extract_version(
                    link
                )

            if version is None:
                continue

            candidates.append(
                {
                    "version": version,
                    "version_text": str(
                        version
                    ),
                    "title": title,
                    "link": link,
                }
            )

        if not candidates:
            return {
                **feed,
                "error":
                    "no valid version found",
            }

        latest = max(
            candidates,
            key=lambda item:
                item["version"],
        )

        return {
            **feed,
            **latest,
        }

    except Exception as exc:
        return {
            **feed,
            "error": str(exc),
        }


def load_issues():
    return json.loads(
        run_gh(
            [
                "issue",
                "list",
                "--repo",
                TARGET_REPO,
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                (
                    "number,title,body,"
                    "state,url"
                ),
            ]
        )
    )


def marker(package):
    return (
        "<!-- package-update:"
        f"{package.casefold()} -->"
    )


def find_open_issue(
    issues,
    package,
):
    package_marker = marker(package)

    for issue in issues:
        if issue["state"] != "OPEN":
            continue

        body = issue.get("body") or ""

        if package_marker in body:
            return issue

    return None


def find_duplicate(
    issues,
    package,
    upstream_version,
):
    package_marker = marker(package)

    version_marker = (
        "<!-- upstream-version:"
        f"{upstream_version} -->"
    )

    for issue in issues:
        body = issue.get("body") or ""

        if (
            package_marker in body
            and version_marker in body
        ):
            return issue

    return None


def issue_version(issue):
    body = issue.get("body") or ""

    match = re.search(
        r"<!-- upstream-version:"
        r"([^\s]+) -->",
        body,
    )

    if match:
        return extract_version(
            match.group(1)
        )

    return extract_version(
        issue.get("title", "")
    )


def make_body(
    package,
    upstream_version,
    repository_version,
    result,
):
    return f"""## Package update

**Package:** `{package}`

**Repository version:** `{repository_version}`

**Upstream version:** `{upstream_version}`

### Source

{result["link"]}

<!-- package-update:{package.casefold()} -->
<!-- upstream-version:{upstream_version} -->
<!-- source:{result["link"]} -->
"""


def ensure_label():
    result = subprocess.run(
        [
            "gh",
            "label",
            "create",
            ISSUE_LABEL,
            "--repo",
            TARGET_REPO,
            "--description",
            "Upstream package update",
            "--color",
            "1d76db",
            "--force",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        print(
            "WARNING: unable to create label:",
            result.stderr.strip(),
            file=sys.stderr,
        )


def create_issue(
    package,
    repository_package,
    result,
):
    upstream = result["version_text"]
    repository = (
        repository_package["version_text"]
    )

    title = (
        f"Update {package} "
        f"to {upstream}"
    )

    body = make_body(
        package,
        upstream,
        repository,
        result,
    )

    url = run_gh(
        [
            "issue",
            "create",
            "--repo",
            TARGET_REPO,
            "--title",
            title,
            "--body",
            body,
            "--label",
            ISSUE_LABEL,
        ]
    ).strip()

    log(
        "CREATE",
        package,
        f"{repository} -> {upstream}  {url}",
    )


def update_issue(
    issue,
    package,
    repository_package,
    result,
):
    upstream = result["version_text"]
    repository = (
        repository_package["version_text"]
    )

    title = (
        f"Update {package} "
        f"to {upstream}"
    )

    body = make_body(
        package,
        upstream,
        repository,
        result,
    )

    run_gh(
        [
            "issue",
            "edit",
            str(issue["number"]),
            "--repo",
            TARGET_REPO,
            "--title",
            title,
            "--body",
            body,
        ]
    )

    log(
        "UPDATE",
        package,
        f"#{issue['number']} {repository} -> {upstream}",
    )


def close_issue(
    issue,
    package,
    repository_version,
):
    run_gh(
        [
            "issue",
            "close",
            str(issue["number"]),
            "--repo",
            TARGET_REPO,
            "--comment",
            (
                f"`{package}` is now available "
                f"in OCO as version "
                f"`{repository_version}`."
            ),
        ]
    )

    log(
        "CLOSE",
        package,
        f"#{issue['number']}  repository={repository_version}",
    )


def process_feed(
    result,
    repository_versions,
    package_map,
    issues,
    stats,
):
    feed_name = result["name"]

    if result.get("error"):
        stats["error"] += 1
        log(
            "ERROR",
            feed_name,
            result["error"],
        )
        return

    packages, matched_by_name = (
        find_packages_for_feed(
            result,
            package_map,
        )
    )

    if not packages:
        stats["miss"] += 1
        hint = closest_package(feed_name)

        detail = (
            "no OCO package matches feed"
            + (f"; closest: {hint}" if hint else "")
        )
        log("MISS", feed_name, detail)
        return

    upstream = result["version"]
    match_kind = "name" if matched_by_name else "URL"

    for package in packages:
        repository_package = (
            repository_versions.get(
                package.casefold()
            )
        )

        if repository_package is None:
            stats["miss"] += 1
            log(
                "MISS",
                package,
                "template exists but no README row",
            )
            continue

        repository_version = (
            repository_package["version"]
        )

        open_issue = find_open_issue(
            issues,
            package,
        )

        # Already up-to-date.


        if upstream <= repository_version:
            stats["ok"] += 1
            detail = (
                f"up-to-date (repo {repository_version}.,  "
                f"{match_kind} match)"
            )

            if open_issue:
                close_issue(
                    open_issue,
                    package,
                    repository_package[
                        "version_text"
                    ],
                )
                detail = (
                    f"closed #{open_issue['number']}  "
                    f"(repo {repository_version}.,  "
                    f"{match_kind} match)"
                )

            log("OK", package, detail)
            continue

        # Upstream is newer.


        if open_issue:
            tracked_version = (
                issue_version(open_issue)
            )

            if (
                tracked_version is None
                or upstream > tracked_version
            ):
                stats["update"] += 1
                update_issue(
                    open_issue,
                    package,
                    repository_package,
                    result,
                )
            else:
                stats["skip"] += 1
                log(
                    "SKIP",
                    package,
                    f"issue #{open_issue['number']}  "
                    f"already tracks {tracked_version}",
                )

            continue

        # No open issue. Check closed issues too
        # to avoid creating the exact same issue again.
        duplicate = find_duplicate(
            issues,
            package,
            result["version_text"],
        )

        if duplicate:
            stats["skip"] += 1
            log(
                "SKIP",
                package,
                f"already tracked by #{duplicate['number']}",
            )
            continue

        stats["create"] += 1
        create_issue(
            package,
            repository_package,
            result,
        )


def main():
    feeds = load_feeds()
    repository_versions = (
        load_repository_versions()
    )
    package_map = build_package_map()

    print(
        f"Feeds: {len(feeds)}"
    )

    print(
        f"OCO packages: "
        f"{len(repository_versions)}"
    )

    issues = load_issues()

    ensure_label()

    print("Fetching feeds...")

    results = []

    with ThreadPoolExecutor(
        max_workers=10
    ) as executor:
        futures = [
            executor.submit(
                fetch_feed,
                feed,
            )
            for feed in feeds
        ]

        for future in as_completed(
            futures
        ):
            results.append(
                future.result()
            )

    stats = {
        "ok": 0,
        "update": 0,
        "create": 0,
        "skip": 0,
        "miss": 0,
        "error": 0,
    }

    for result in sorted(
        results,
        key=lambda item:
            item["name"].casefold(),
    ):
        process_feed(
            result,
            repository_versions,
            package_map,
            issues,
            stats,
        )

        # Refresh after every feed because one
        # feed can create multiple issues.


        issues = load_issues()

    print()

    log(
        "SUMMARY",
        "feeds",
        f"{len(results)}  "
        f"| ok {stats['ok']}  "
        f"| update {stats['update']}  "
        f"| create {stats['create']}  "
        f"| skip {stats['skip']}  "
        f"| miss {stats['miss']}  "
        f"| error {stats['error']}",
    )


if __name__ == "__main__":
    main()
