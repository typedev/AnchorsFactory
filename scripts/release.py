#!/usr/bin/env python3
"""One-shot release: bump the version, build, publish, tag, push.

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
  3. Resolves the publish token (see Authentication) — before touching anything.
  4. Writes the version into pyproject.toml and promotes the curated
     `## [Unreleased]` CHANGELOG section to `## [version] - date`, leaving a
     fresh empty `## [Unreleased]`. That section is also the release notes.
     (Refuses if `## [Unreleased]` is empty — write your notes there as you go.)
  5. Builds the sdist+wheel and runs `twine check`.
  6. Uploads to PyPI (or TestPyPI with --test). This is the point of no return.
  7. With --test this is a dry run: after the TestPyPI upload the working tree
     is restored (version/CHANGELOG edits undone) and nothing is committed —
     so a later `make release` bumps cleanly to the same version.
  8. For a real (non --test) release: commits, tags `vX.Y.Z`, pushes the commit
     and the tag, and creates a GitHub Release with the changelog section as
     notes and the artifacts attached (best-effort — needs an authenticated
     `gh`; a failure there leaves PyPI/tag intact). If anything before the
     upload fails, the tree is restored and git history is left untouched.

Authentication: the token is read from the environment, then from a (gitignored)
`.env` in the repo root, and finally prompted interactively if neither has it.
Variables: `PYPI_TOKEN` for a real release, `TEST_PYPI_TOKEN` with --test (a bare
`UV_PUBLISH_TOKEN` is accepted as a fallback for either). Example `.env`:

    PYPI_TOKEN=pypi-...
    TEST_PYPI_TOKEN=pypi-...
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import os
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


# --- tokens ---------------------------------------------------------------- #
def load_env_file() -> dict[str, str]:
    """Parse simple KEY=VALUE lines from a gitignored .env (no dependency)."""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def resolve_token(test: bool) -> str:
    """Find the publish token: real env, then .env, then an interactive prompt.

    Looks at the target-specific variable first (TEST_PYPI_TOKEN / PYPI_TOKEN),
    then a bare UV_PUBLISH_TOKEN, in both the environment and `.env`.
    """
    primary = "TEST_PYPI_TOKEN" if test else "PYPI_TOKEN"
    names = (primary, "UV_PUBLISH_TOKEN")
    file_env = load_env_file()
    for source in (os.environ, file_env):
        for name in names:
            if source.get(name):
                return source[name]
    where = "TestPyPI" if test else "PyPI"
    try:
        token = getpass.getpass(f"  {where} token ({primary} not in env or .env): ")
    except (EOFError, KeyboardInterrupt):
        die("No token provided — aborted.")
    if not token.strip():
        die("No token provided — aborted.")
    return token.strip()


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

    if not args.yes:
        ans = input(f"\nPublish {new} to {target}? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            die("Aborted by user.")

    # Resolve the token up front (may prompt) — before mutating anything, so a
    # missing token aborts cleanly with the tree untouched.
    token = resolve_token(args.test)
    publish_env = {**os.environ, "UV_PUBLISH_TOKEN": token}

    date = datetime.date.today().isoformat()

    # --- working-tree changes (reversible until we commit) ---
    write_version = PYPROJECT.read_text()
    new_pyproject, n = re.subn(
        r'(?m)^version\s*=\s*".*"', f'version = "{new}"', write_version, count=1
    )
    if n != 1:
        die("Could not find a single version line in pyproject.toml")
    PYPROJECT.write_text(new_pyproject)
    body = promote_unreleased(new, date)

    try:
        print("\nBuilding artifacts ...")
        # Start from an empty dist/ so we only ever publish what we just built
        # (uv build does not clear stale or pre-existing artifacts itself), and
        # from no build/ or *.egg-info either: setuptools reuses an existing
        # egg-info's file list in preference to `packages` in pyproject.toml, so
        # a stale one from an earlier editable install silently puts modules back
        # into the wheel. That shipped the Studio in 0.5.0.
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
        die(f"Build/check failed — working tree restored, nothing published.{detail}")

    try:
        print(f"\nUploading to {target} ...")
        cmd = ["uv", "publish"]
        if args.test:
            cmd += ["--publish-url", "https://test.pypi.org/legacy/"]
        cmd += dist_files
        run(cmd, env=publish_env)
    except subprocess.CalledProcessError:
        run(["git", "checkout", "--", str(PYPROJECT), str(CHANGELOG)])
        die("Upload failed — working tree restored, nothing committed.")

    if args.test:
        # TestPyPI is a dry run: undo the version/CHANGELOG edits so the real
        # `make release` later bumps cleanly. Nothing is committed/tagged/pushed.
        run(["git", "checkout", "--", str(PYPROJECT), str(CHANGELOG)])
        print(f"\n✓ Uploaded {new} to TestPyPI. Working tree restored — "
              "run `make release` for the real PyPI release.")
        return

    # --- real upload succeeded: now it's safe to record it in git ---
    tag = f"v{new}"
    print(f"\nRecording release {tag} in git ...")
    run(["git", "add", str(PYPROJECT), str(CHANGELOG)])
    run(["git", "commit", "-m", f"Release {tag}"])
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", "master"])
    run(["git", "push", "origin", tag])

    # A real release also gets a GitHub Release, with the changelog section as
    # notes and the built artifacts attached. Best-effort: a missing/unauth'd
    # `gh` must not undo a successful PyPI publish, so just warn.
    print(f"\nCreating GitHub release {tag} ...")
    try:
        run(
            ["gh", "release", "create", tag, "--title", tag,
             "--notes", body, *dist_files]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            f"  ! Could not create the GitHub release for {tag} "
            "(is `gh` installed and authenticated?).\n"
            "    The PyPI publish and the git tag are unaffected; create it\n"
            f"    later with:  gh release create {tag} --notes \"...\""
        )

    print(f"\n✓ Published {new} to PyPI and pushed {tag}.")


if __name__ == "__main__":
    main()
