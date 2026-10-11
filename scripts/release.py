#!/usr/bin/env python3
"""Cut a release: bump the version, check the build, tag, push. CI publishes.

Run it when you've decided the current state of `master` is worth publishing:

    make release                  # bump minor, tag, push -> CI publishes to PyPI
    make release ARGS=--no-bump   # release the current version as-is
    make release-test             # CI publishes a .devN build to TestPyPI

What it does, in order:

  1. Refuses to run unless the tree is clean, you're on `master`, and local
     `master` matches `origin/master`.
  2. Decides the new version. The very first release (no `v*` tags yet)
     publishes the version already in pyproject.toml; every release after
     that bumps the minor (0.1.0 -> 0.2.0 -> 0.3.0 ...).
  3. Writes the version into pyproject.toml and promotes the curated
     `## [Unreleased]` CHANGELOG section to `## [version] - date`, leaving a
     fresh empty `## [Unreleased]`. That section is also the release notes.
     (Refuses if `## [Unreleased]` is empty — write your notes there as you go.)
  4. Builds the sdist+wheel locally, runs `twine check` and inspects the wheel,
     so a broken build fails here, before any tag exists. On failure the tree
     is restored and git history is left untouched.
  5. Commits, tags `vX.Y.Z`, pushes the commit and the tag.

Publishing is not done here. The pushed tag starts `.github/workflows/release.yml`,
which runs the tests, rebuilds, checks the wheel again, uploads to PyPI through
**trusted publishing** (OIDC: no API token anywhere) and creates the GitHub
Release with the CHANGELOG section as notes. If that workflow fails after the
tag is pushed, fix the cause and re-run the failed jobs in Actions; the tag
does not need to move unless the code does.

CI also calls this script for small helpers: `--check-wheel WHEEL...`,
`--notes VERSION` (print that CHANGELOG section) and `--print-version`.
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
ENV_FILE = ROOT / ".env"


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


# --- changelog ------------------------------------------------------------- #
def promote_unreleased(version: str, date: str) -> str:
    """Move the curated ``## [Unreleased]`` section to ``## [version] - date``,
    leaving a fresh empty ``## [Unreleased]``. Returns the section body (used as
    the release notes). Refuses if ``[Unreleased]`` is empty.
    """
    text = CHANGELOG.read_text() if CHANGELOG.exists() else ""
    m = re.search(r"(?ms)^##\s*\[Unreleased\][^\n]*\n(.*?)(?=^##\s|\Z)", text)
    if not m:
        die("No '## [Unreleased]' section in CHANGELOG.md.")
    body = m.group(1).strip()
    if not body:
        die("Nothing under '## [Unreleased]' in CHANGELOG.md — write the release "
            "notes there before releasing.")
    new = (
        f"{text[:m.start()]}## [Unreleased]\n\n"
        f"## [{version}] - {date}\n\n{body}\n\n"
        f"{text[m.end():].lstrip(chr(10))}"
    )
    CHANGELOG.write_text(new)
    return body


def changelog_section(version: str) -> str:
    """The body of ``## [version]`` in CHANGELOG.md (the release notes)."""
    text = CHANGELOG.read_text()
    m = re.search(rf"(?ms)^##\s*\[{re.escape(version)}\][^\n]*\n(.*?)(?=^##\s|\Z)", text)
    if not m:
        die(f"No '## [{version}]' section in CHANGELOG.md.")
    return m.group(1).strip()


class WheelContentsError(Exception):
    """The built wheel carries a file the distribution must not contain."""


def clean_build_artifacts() -> None:
    """Remove everything a previous build (or editable install) left behind."""
    for path in [ROOT / "dist", ROOT / "build", *ROOT.glob("*.egg-info")]:
        if path.exists():
            print(f"  removing {path.name}/")
            shutil.rmtree(path)


#: What the distribution must NOT contain. Rule sets are data the host owns and
#: the Studio is a repository-only tool (see pyproject's `packages`); both have
#: been put back into the wheel by accident once already.
FORBIDDEN_IN_WHEEL = (
    ("rule set", lambda name: name.endswith((".anchors", ".glyphsConstruction"))),
    ("studio module", lambda name: name.startswith("anchorsfactory/studio/")),
)


def verify_wheel(path: str) -> None:
    """Fail the release if the built wheel carries something it shouldn't.

    The build config alone is not enough of a guarantee — it was correct for
    0.5.0 and the wheel still shipped the Studio, because a stale egg-info
    overrode it. So the artifact itself is inspected, right before upload.
    """
    import zipfile

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    for label, matches in FORBIDDEN_IN_WHEEL:
        found = sorted(n for n in names if matches(n))
        if found:
            raise WheelContentsError(
                f"{Path(path).name} contains {len(found)} {label} file(s), "
                f"e.g. {found[0]} — the wheel is the engine, the CLI and the "
                f"vendored GlyphConstruction only.")
    print(f"  {Path(path).name}: no rule sets, no studio ✓")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bump, check, tag, push (CI publishes).")
    ap.add_argument(
        "--no-bump",
        action="store_true",
        help="release the current version without bumping",
    )
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    # helpers for CI (no git, no side effects)
    ap.add_argument("--check-wheel", nargs="+", metavar="WHEEL",
                    help="only inspect built wheel(s) for forbidden files")
    ap.add_argument("--notes", metavar="VERSION",
                    help="only print the CHANGELOG section of VERSION")
    ap.add_argument("--print-version", action="store_true",
                    help="only print the version in pyproject.toml")
    args = ap.parse_args()

    if args.check_wheel:
        try:
            for wheel in args.check_wheel:
                verify_wheel(wheel)
        except WheelContentsError as exc:
            die(str(exc))
        return
    if args.notes:
        print(changelog_section(args.notes))
        return
    if args.print_version:
        print(current_version())
        return

    print("AnchorsFactory release\n----------------------")
    check_preconditions()

    cur = current_version()
    first_release = latest_tag() is None
    new = cur if first_release or args.no_bump else bump_minor(cur)
    tag = f"v{new}"
    if capture(["git", "tag", "--list", tag]):
        die(f"Tag {tag} already exists.")

    print(f"\n  current version : {cur}")
    print(f"  release version : {new}")
    print("  publish         : by CI on tag push (trusted publishing to PyPI)")

    if not args.yes:
        ans = input(f"\nTag and push {tag}? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            die("Aborted by user.")

    date = datetime.date.today().isoformat()

    # --- working-tree changes (reversible until we commit) ---
    write_version = PYPROJECT.read_text()
    new_pyproject, n = re.subn(
        r'(?m)^version\s*=\s*".*"', f'version = "{new}"', write_version, count=1
    )
    if n != 1:
        die("Could not find a single version line in pyproject.toml")
    PYPROJECT.write_text(new_pyproject)
    promote_unreleased(new, date)

    try:
        print("\nBuilding artifacts (local check; CI builds what it publishes) ...")
        # Start from no dist/, build/ or *.egg-info: setuptools reuses an
        # existing egg-info's file list in preference to `packages` in
        # pyproject.toml, so a stale one from an earlier editable install
        # silently puts modules back into the wheel. That shipped the Studio
        # in 0.5.0.
        dist_dir = ROOT / "dist"
        clean_build_artifacts()
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
        for f in dist_files:
            if f.endswith(".whl"):
                verify_wheel(f)
    except (subprocess.CalledProcessError, WheelContentsError) as exc:
        run(["git", "checkout", "--", str(PYPROJECT), str(CHANGELOG)])
        detail = f"\n  {exc}" if isinstance(exc, WheelContentsError) else ""
        die(f"Build/check failed — working tree restored, nothing tagged.{detail}")

    print(f"\nRecording release {tag} in git ...")
    run(["git", "add", str(PYPROJECT), str(CHANGELOG)])
    run(["git", "commit", "-m", f"Release {tag}"])
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", "master"])
    run(["git", "push", "origin", tag])

    print(f"\n✓ Pushed {tag}. CI now tests, builds and publishes it:\n"
          f"    https://github.com/typedev/AnchorsFactory/actions\n"
          f"  (or: gh run watch)")


if __name__ == "__main__":
    main()
