#!/usr/bin/env python3
"""One-shot release: bump the minor version, build, publish, tag, push.

Run it when you've decided the current state of `master` is worth publishing:

    make release            # bump minor, upload to PyPI
    make release-test       # same, but upload to TestPyPI
    make release ARGS=--no-bump   # publish the current version as-is

What it does, in order:

  1. Refuses to run unless the tree is clean, you're on `master`, and local
     `master` matches `origin/master`.
  2. Decides the new version. The very first release (no `v*` tags yet)
     publishes the version already in pyproject.toml; every release after
     that bumps the minor (0.1.0 -> 0.2.0 -> 0.3.0 ...).
  3. Writes the version into pyproject.toml and prepends a CHANGELOG section
     built from the commit subjects since the previous release.
  4. Builds the sdist+wheel and runs `twine check`.
  5. Uploads to PyPI (or TestPyPI with --test). This is the point of no return.
  6. *Only after* a successful upload: commits, tags `vX.Y.Z`, and pushes both
     the commit and the tag. If anything before the upload fails, the working
     tree is restored and git history is left untouched.

Authentication: set a token in the environment before running, e.g.
    export UV_PUBLISH_TOKEN=pypi-...
(use a TestPyPI token together with --test).
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, echoing it; raise on non-zero exit."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def capture(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def die(msg: str) -> None:
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def check_preconditions() -> None:
    if capture(["git", "status", "--porcelain"]):
        die("Working tree is not clean — commit or stash your changes first.")
    branch = capture(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch != "master":
        die(f"You are on '{branch}', not 'master'. Switch to master to release.")
    print("  fetching origin ...")
    run(["git", "fetch", "--quiet", "origin"])
    local = capture(["git", "rev-parse", "HEAD"])
    remote = capture(["git", "rev-parse", "origin/master"])
    if local != remote:
        die("Local master differs from origin/master — push or pull first.")


def current_version() -> str:
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def bump_minor(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        die(f"Cannot parse version '{version}' as MAJOR.MINOR.PATCH")
    return f"{parts[0]}.{int(parts[1]) + 1}.0"


def latest_tag() -> str | None:
    tags = capture(["git", "tag", "--list", "v*", "--sort=-v:refname"])
    return tags.splitlines()[0] if tags else None


def write_version(version: str) -> None:
    text = PYPROJECT.read_text()
    new, n = re.subn(
        r'(?m)^version\s*=\s*".*"', f'version = "{version}"', text, count=1
    )
    if n != 1:
        die("Could not find a single version line in pyproject.toml")
    PYPROJECT.write_text(new)


def changelog_body(prev_tag: str | None) -> str:
    if prev_tag is None:
        return "- Initial public release."
    rng = f"{prev_tag}..HEAD"
    subjects = capture(
        ["git", "log", rng, "--no-merges", "--reverse", "--pretty=%s"]
    )
    lines = [f"- {s}" for s in subjects.splitlines() if s.strip()]
    return "\n".join(lines) if lines else "- No changes recorded."


def write_changelog(version: str, date: str, body: str) -> None:
    text = CHANGELOG.read_text() if CHANGELOG.exists() else "# Changelog\n\n## [Unreleased]\n"
    section = f"## [{version}] - {date}\n\n{body}\n"
    marker = "## [Unreleased]"
    if marker in text:
        head, tail = text.split(marker, 1)
        text = f"{head}{marker}\n\n{section}\n{tail.lstrip(chr(10))}"
    else:
        text = f"{text.rstrip()}\n\n{section}"
    CHANGELOG.write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser(description="Bump, build, publish, tag, push.")
    ap.add_argument("--test", action="store_true", help="upload to TestPyPI")
    ap.add_argument(
        "--no-bump",
        action="store_true",
        help="publish the current version without bumping",
    )
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    print("AnchorsFactory release\n----------------------")
    check_preconditions()

    cur = current_version()
    prev_tag = latest_tag()
    first_release = prev_tag is None
    if first_release or args.no_bump:
        new = cur
    else:
        new = bump_minor(cur)

    target = "TestPyPI" if args.test else "PyPI"
    print(f"\n  current version : {cur}")
    print(f"  release version : {new}")
    print(f"  target          : {target}")
    print(f"  changelog since : {prev_tag or '(first release — all history)'}")

    if not args.yes:
        ans = input(f"\nPublish {new} to {target}? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            die("Aborted by user.")

    date = datetime.date.today().isoformat()
    body = changelog_body(prev_tag)

    # --- working-tree changes (reversible until we commit) ---
    write_version(new)
    write_changelog(new, date, body)

    try:
        print("\nBuilding artifacts ...")
        # Start from an empty dist/ so we only ever publish what we just built
        # (uv build does not clear stale or pre-existing artifacts itself).
        dist_dir = ROOT / "dist"
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        run(["uv", "build"])
        dist_files = sorted(
            str(p)
            for p in dist_dir.glob("*")
            if p.is_file() and p.name.endswith((".whl", ".tar.gz"))
        )
        if not dist_files:
            raise subprocess.CalledProcessError(1, "uv build")
        print("\nChecking artifacts ...")
        run(["uvx", "twine", "check", *dist_files])
    except subprocess.CalledProcessError:
        run(["git", "checkout", "--", str(PYPROJECT), str(CHANGELOG)])
        die("Build/check failed — working tree restored, nothing published.")

    try:
        print(f"\nUploading to {target} ...")
        cmd = ["uv", "publish"]
        if args.test:
            cmd += ["--publish-url", "https://test.pypi.org/legacy/"]
        cmd += dist_files
        run(cmd)
    except subprocess.CalledProcessError:
        run(["git", "checkout", "--", str(PYPROJECT), str(CHANGELOG)])
        die(
            "Upload failed — working tree restored, nothing committed.\n"
            "  (Did you export UV_PUBLISH_TOKEN?)"
        )

    # --- upload succeeded: now it's safe to record it in git ---
    tag = f"v{new}"
    print(f"\nRecording release {tag} in git ...")
    run(["git", "add", str(PYPROJECT), str(CHANGELOG)])
    run(["git", "commit", "-m", f"Release {tag}"])
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", "master"])
    run(["git", "push", "origin", tag])

    print(f"\n✓ Published {new} to {target} and pushed {tag}.")


if __name__ == "__main__":
    main()
