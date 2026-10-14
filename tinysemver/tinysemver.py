#!/usr/bin/env python3
"""TinySemVer is a tiny minimalistic Semantic Versioning tool.

This module traces the commit history of a Git repository after the last tag, and based 
on the commit messages, it determines the type of version bump (major, minor, or patch).
On "dry-runs" it simply reports the new version number, but on actual runs, it creates a
a new tag, and optionally pushes it to the repository, also updating the "version file",
the "changelog file", and all other files and RegEx patterns passed as CLI arguments.

Example:

    tinysemver --dry-run --verbose \
        --major-verbs 'breaking,break,major' \
        --minor-verbs 'feature,minor,add,new' \
        --patch-verbs 'fix,patch,bug,improve,docs,make' \
        --changelog-file 'CHANGELOG.md' \
        --guide-file 'CONTRIBUTING.md' \
        --version-file 'VERSION' \
        --update-version-in 'package.json' '"version": "(.*)"' \
        --update-version-in 'CITATION.cff' '^version: (.*)' \
        --update-major-version-in 'include/stringzilla/stringzilla.h' '^#define STRINGZILLA_VERSION_MAJOR (.*)' \
        --update-minor-version-in 'include/stringzilla/stringzilla.h' '^#define STRINGZILLA_VERSION_MINOR (.*)' \
        --update-patch-version-in 'include/stringzilla/stringzilla.h' '^#define STRINGZILLA_VERSION_PATCH (.*)'
    
    Multiple "--update-version-in" arguments can be passed to update multiple files.
    Each of them must be followed by a file path and a RegEx pattern.
    The RegEx pattern must contain a capturing group to extract the version number,
    that will be replaced by the new version number.

By default, the following conventions are used:

    - The repository must be a Git repository.
    - It must contain a "VERSION" and "CHANGELOG.md" files in the root directory.
    - The changelog is append-only - sorted in chronological order.
    - The contibution guide is in the "CONTRIBUTING.md" file.

Setting up a new project:

    $ git init # Initialize a new Git repository
    $ echo "0.1.0" > VERSION # Create a version file
    $ echo "# Changelog" > CHANGELOG.md # Create a changelog file
    $ git add VERSION CHANGELOG.md # Add the files to the repository
    $ git commit -m "Add: Initial files" # Create the first commit
    $ git tag v0.1.0 # Create the first tag

"""
import argparse
import os
import re
import subprocess
import sys
import traceback
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, NamedTuple

BumpType = Literal["major", "minor", "patch"]
PathLike = str | os.PathLike[str]
ChangeDiff = str


class SemVer(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class Commit(NamedTuple):
    hash: str
    message: str


class NoNewCommitsError(Exception):
    """Raised when no new commits are found since the last tag."""





try:
    from rich.console import Console

    _console: Any = Console()
except ImportError:
    _console = None


def print_to_console(message: str) -> None:
    """Print a message to the console, rendering `rich` markup when it's installed."""
    if _console:
        _console.print(message)
    else:
        print(message)


def get_last_tag(repository_path: PathLike) -> str | None:
    """Retrieve the last full-version Git tag name from the repository.

    Only three-component tags count: the moving `v3` and `v3.0` aliases that `push_moving_tags`
    maintains point at the same commits as real releases and must never be mistaken for one.
    """
    result = subprocess.run(
        [
            "git",
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*.[0-9]*.[0-9]*",
            "--match",
            "[0-9]*.[0-9]*.[0-9]*",
            "--exclude",
            "*-*",
        ],
        capture_output=True,
        cwd=repository_path,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip().decode("utf-8")


def get_commits_since_tag(repository_path: PathLike, tag: str | None) -> list[Commit]:
    """Get commit hashes and messages since the specified Git tag, or the whole history without one."""
    result = subprocess.run(
        ["git", "log", f"{tag}..HEAD" if tag else "HEAD", "--no-merges", "--pretty=format:%h:%s"],
        capture_output=True,
        cwd=repository_path,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to list commits since '{tag}': {result.stderr.decode('utf-8').strip()}")

    commits = []
    for line in result.stdout.decode("utf-8").splitlines():
        commit_hash, _, message = line.partition(":")
        if line.strip():
            commits.append(Commit(commit_hash, message))
    return commits


def get_diff_for_commit(repository_path: PathLike, commit_hash: str) -> ChangeDiff:
    """Retrieve the diff for a specific commit and parse into Change named tuples."""
    result = subprocess.run(
        ["git", "diff", f"{commit_hash}^", commit_hash, "--unified=3"],
        capture_output=True,
        cwd=repository_path,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to retrieve diff for commit: {commit_hash}")

    return result.stdout.decode("utf-8")


def parse_version(tag: str) -> tuple[SemVer, str]:
    """Parse `[v]MAJOR.MINOR.PATCH[-rc.N]` into its core and its verbatim `-rc.N` suffix."""
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-rc\.(?:0|[1-9]\d*))?", tag.strip())
    if not match:
        raise ValueError(f"Version '{tag}' is not in the MAJOR.MINOR.PATCH[-rc.N] format")
    return SemVer(int(match.group(1)), int(match.group(2)), int(match.group(3))), match.group(4) or ""


def commit_starts_with_verb(commit: str, verb: str) -> bool:
    """Check if a commit message starts with a specific verb, ignoring capitalization and punctuation marks."""
    if not commit.lower().startswith(verb):
        return False
    return len(commit) == len(verb) or commit[len(verb)].isspace() or commit[len(verb)] == ":"


def normalize_verbs(verbs: str | list[str] | None, defaults: list[str]) -> list[str]:
    """Normalize a list of verbs, allowing string input to be split by commas."""
    if isinstance(verbs, str):
        return [verb.strip("\"'") for verb in verbs.split(",")]
    elif verbs is None:
        return defaults
    else:
        return verbs


def group_commits(
    commits: list[Commit],
    major_verbs: list[str],
    minor_verbs: list[str],
    patch_verbs: list[str],
) -> tuple[list[Commit], list[Commit], list[Commit]]:
    """Group commits into major, minor, and patch categories based on keywords to simplify future `BumpType` resolution."""
    major_commits: list[Commit] = []
    minor_commits: list[Commit] = []
    patch_commits: list[Commit] = []

    for commit in commits:
        if any(commit_starts_with_verb(commit.message, verb) for verb in major_verbs):
            major_commits.append(commit)
        if any(commit_starts_with_verb(commit.message, verb) for verb in minor_verbs):
            minor_commits.append(commit)
        if any(commit_starts_with_verb(commit.message, verb) for verb in patch_verbs):
            patch_commits.append(commit)

    return major_commits, minor_commits, patch_commits


def convert_commits_to_message(
    major_commits: list[Commit],
    minor_commits: list[Commit],
    patch_commits: list[Commit],
) -> str:
    """Turns the different commits (major, minor, patch) into a single message."""
    message = ""

    if len(major_commits):
        message += "\n### Major\n\n" + "\n".join(f"- {c.message} ({c.hash})" for c in major_commits) + "\n"
    if len(minor_commits):
        message += "\n### Minor\n\n" + "\n".join(f"- {c.message} ({c.hash})" for c in minor_commits) + "\n"
    if len(patch_commits):
        message += "\n### Patch\n\n" + "\n".join(f"- {c.message} ({c.hash})" for c in patch_commits) + "\n"

    return message


def bump_version(version: SemVer, bump_type: BumpType) -> SemVer:
    """Bump the version based on the specified bump type (major, minor, patch)."""
    major, minor, patch = version
    if bump_type == "major":
        return SemVer(major + 1, 0, 0)
    if bump_type == "minor":
        return SemVer(major, minor + 1, 0)
    return SemVer(major, minor, patch + 1)


def create_tag(
    *,  # enforce keyword-only arguments
    repository_path: PathLike,
    version: SemVer,
    user_name: str,
    user_email: str,
    default_branch: str = "main",
    github_token: str | None = None,
    github_repository: str | None = None,
    push: bool = False,
    create_release: bool = False,
    push_moving_tags: bool = False,
    major_commits: list[Commit] | None = None,
    minor_commits: list[Commit] | None = None,
    patch_commits: list[Commit] | None = None,
) -> None:
    """Create a new Git tag and optionally push it to a remote GitHub repository."""

    tag = f"v{version}"
    env = os.environ.copy()
    env["GIT_COMMITTER_NAME"] = user_name
    env["GIT_COMMITTER_EMAIL"] = user_email
    env["GIT_AUTHOR_NAME"] = user_name
    env["GIT_AUTHOR_EMAIL"] = user_email
    if github_token:
        env["GITHUB_TOKEN"] = github_token

    message = f"Release: {tag} [skip ci]"
    message += convert_commits_to_message(major_commits or [], minor_commits or [], patch_commits or [])

    # `-u` keeps untracked build outputs out of the release commit
    subprocess.run(["git", "add", "-u"], cwd=repository_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repository_path, env=env, check=True)

    # Get the SHA of the new commit
    new_commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(["git", "tag", "-a", tag, "-m", message, new_commit_sha], cwd=repository_path, env=env, check=True)
    print_to_console(f"[bold green]Created new tag:[/bold green] {tag}")

    # Optionally create moving major and minor version tags for GitHub Actions compatibility
    # This allows users to reference @v2 or @v2.1 instead of @v2.1.1
    # Note: This requires force-push permissions
    if push_moving_tags:
        major_tag = f"v{version.major}"
        minor_tag = f"v{version.major}.{version.minor}"

        # Force-update major version tag (e.g., v2 -> v2.1.1)
        subprocess.run(
            ["git", "tag", "-fa", major_tag, "-m", f"Update {major_tag} to {tag}", new_commit_sha],
            cwd=repository_path,
            env=env,
            check=True,
        )
        print_to_console(f"[bold green]Updated major version tag:[/bold green] {major_tag} -> {tag}")

        # Force-update minor version tag (e.g., v2.1 -> v2.1.1)
        subprocess.run(
            ["git", "tag", "-fa", minor_tag, "-m", f"Update {minor_tag} to {tag}", new_commit_sha],
            cwd=repository_path,
            env=env,
            check=True,
        )
        print_to_console(f"[bold green]Updated minor version tag:[/bold green] {minor_tag} -> {tag}")
    if push:
        url = None
        if github_token and github_repository:
            url = f"https://x-access-token:{github_token}@github.com/{github_repository}"
        elif not github_token and not github_repository:
            url = "origin"
        else:
            assert github_repository and not github_token, "You can't provide the GitHub token without the repository"
            url = f"https://github.com/{github_repository}"

        # Push both commits and the tag
        push_result = subprocess.run(
            ["git", "push", url, f"{new_commit_sha}:{default_branch}"],
            cwd=repository_path,
            capture_output=True,
            env=env,
            check=False,
        )
        if push_result.returncode != 0:
            raise RuntimeError(
                f"Failed to push the new commits to the remote repository: '{url}' with error: {push_result.stderr.decode('utf-8')}"
            )

        # Push the specific version tag (e.g., v2.1.1)
        push_result = subprocess.run(
            ["git", "push", url, tag], cwd=repository_path, capture_output=True, env=env, check=False
        )
        if push_result.returncode != 0:
            raise RuntimeError(
                f"Failed to push the tag '{tag}' to the remote repository: '{url}' with error: {push_result.stderr.decode('utf-8')}"
            )

        print_to_console(f"[bold green]Pushed tag:[/bold green] {tag}")

        # Optionally force-push the moving major and minor version tags. By this point the version
        # commit and the exact tag are already on the remote, so the release is complete and cannot
        # be retried - a token without force-push rights must cost the aliases, never the release.
        if push_moving_tags:
            for moving_tag in (f"v{version.major}", f"v{version.major}.{version.minor}"):
                push_result = subprocess.run(
                    ["git", "push", url, moving_tag, "--force"],
                    cwd=repository_path,
                    capture_output=True,
                    env=env,
                    check=False,
                )
                if push_result.returncode != 0:
                    print_to_console(
                        f"[bold yellow]Warning:[/bold yellow] couldn't force-push moving tag '{moving_tag}': "
                        f"{push_result.stderr.decode('utf-8').strip()} - the release itself is complete"
                    )
                else:
                    print_to_console(f"[bold green]Pushed moving tag:[/bold green] {moving_tag} -> {tag}")

        if create_release and github_repository:
            release_result = subprocess.run(
                ["gh", "release", "create", tag, "--title", f"Release {tag}", "--notes", message],
                cwd=repository_path,
                capture_output=True,
                text=True,
                env={**env, "GH_REPO": github_repository},
                check=False,
            )
            if release_result.returncode != 0:
                raise RuntimeError(f"Failed to create the GitHub release for '{tag}': {release_result.stderr.strip()}")
            print_to_console(f"[bold green]Created GitHub release for tag:[/bold green] {tag}")


def patch_with_regex(
    file_path: PathLike,
    regex_pattern: str,
    new_version: str,
    dry_run: bool = False,
    verbose: bool = False,
    count: int = 1,
    stale_version: str = "",
) -> None:
    """Update a file by replacing the first capturing group of its matches with a new version.

    `count` bounds how many matches are rewritten, following `re.sub` semantics: the default `1`
    rewrites only the first - which suits a single-line version file and a catch-all `(.*)` pattern
    whose empty-string matches would otherwise duplicate the version - while `0` rewrites every match,
    what a README that lists the dependency more than once needs so no example pins a stale version.
    A `stale_version` like `3.0.0-rc.1` is first cut down to its core `3.0.0`, so the usual
    `(\\d+\\.\\d+\\.\\d+)` patterns still match the pre-release they graduate.
    """

    assert os.path.exists(file_path), f"File missing: {file_path}"
    with open(file_path, "r") as file:
        old_content = file.read()
    stale_core, _, _ = stale_version.partition("-")
    if stale_version:
        old_content = old_content.replace(stale_version, stale_core)

    def replace_first_group(match: re.Match[str]) -> str:
        assert len(match.groups()) == 1, f"Must contain exactly one capturing group in: {regex_pattern} for {file_path}"
        range_to_replace = match.span(1)
        old_slice = match.span(0)
        old_string = match.string[old_slice[0] : old_slice[1]]
        updated = (
            old_string[: range_to_replace[0] - old_slice[0]]
            + new_version
            + old_string[range_to_replace[1] - old_slice[0] :]
        )
        return updated

    compiled_pattern = re.compile(regex_pattern, re.MULTILINE)
    matches = list(compiled_pattern.finditer(old_content))
    new_content = compiled_pattern.sub(replace_first_group, old_content, count=count)

    non_empty_matches = [m for m in matches if len(m.group(0).strip())]
    assert len(non_empty_matches) > 0, f"No matches found in: {file_path}"

    for match in non_empty_matches:
        match_line = old_content.count("\n", 0, match.start()) + 1
        old_slice = match.group(0)
        new_slice = compiled_pattern.sub(replace_first_group, old_slice, count=1)

        if verbose:
            print_to_console(f"[bold cyan]Will update file:[/bold cyan] {file_path}:{match_line}")
            shown_slice = old_slice.replace(stale_core, stale_version) if stale_version else old_slice
            print_to_console(f"[red]- {shown_slice}[/red]")
            print_to_console(f"[green]+ {new_slice}[/green]")

    if not dry_run:
        with open(file_path, "w") as file:
            file.write(new_content)
        if verbose:
            print_to_console(f"[bold green]File updated successfully:[/bold green] {file_path}")


def bump(
    *,  # enforce keyword-only arguments
    dry_run: bool = False,
    verbose: bool = False,
    major_verbs: str | list[str] | None = None,
    minor_verbs: str | list[str] | None = None,
    patch_verbs: str | list[str] | None = None,
    path: PathLike | None = None,  # takes current directory as default
    changelog_file: PathLike | None = None,  # relative or absolute path to the changelog file
    version_file: PathLike | None = None,  # relative or absolute path to the version file
    update_version_in: Sequence[tuple[PathLike, str]] | None = None,  # path + regex pattern pairs
    update_major_version_in: Sequence[tuple[PathLike, str]] | None = None,  # path + regex pattern pairs
    update_minor_version_in: Sequence[tuple[PathLike, str]] | None = None,  # path + regex pattern pairs
    update_patch_version_in: Sequence[tuple[PathLike, str]] | None = None,  # path + regex pattern pairs
    git_user_name: str = "TinySemVer",
    git_user_email: str = "tinysemver@ashvardanian.com",
    push: bool = True,
    github_token: str | None = None,
    github_repository: str | None = None,
    default_branch: str = "main",
    create_release: bool = False,
    push_moving_tags: bool = False,
) -> SemVer:
    """Primary function used to update the files (version, changelog, etc.), create a new Git tag, push it to a GitHub repository.
    It can be used for dry-runs to preview the changes without actually creating a new tag.
    It can be used as a standalone script or as a library function.

    Args:
        dry_run (bool): If True, performs a dry run without making any changes. Defaults to False.
        verbose (bool): If True, enables verbose output. Defaults to False.
        major_verbs (List[str]): List of keywords that indicate a major version bump. Defaults to ["major", "breaking", "break"].
        minor_verbs (List[str]): List of keywords that indicate a minor version bump. Defaults to ["minor", "feature", "add", "new"].
        patch_verbs (List[str]): List of keywords that indicate a patch version bump. Defaults to ["patch", "fix", "bug", "improve", "docs", "make"].
        path (Optional[PathLike]): The path to the repository. If None, the current directory is used. Defaults to None.
        changelog_file (Optional[PathLike]): The path to the changelog file to update. If None, no changelog update is performed. Defaults to None.
        version_file (Optional[PathLike]): The path to the version file to update. If None, no version file update is performed. Defaults to None.
        update_version_in (Optional[List[Tuple[PathLike, str]]]): List of (file, regex pattern) tuples to update the full version in specified files. Defaults to None.
        update_major_version_in (Optional[List[Tuple[PathLike, str]]]): List of (file, regex pattern) tuples to update the major version in specified files. Defaults to None.
        update_minor_version_in (Optional[List[Tuple[PathLike, str]]]): List of (file, regex pattern) tuples to update the minor version in specified files. Defaults to None.
        update_patch_version_in (Optional[List[Tuple[PathLike, str]]]): List of (file, regex pattern) tuples to update the patch version in specified files. Defaults to None.
        git_user_name (str): The Git user name for committing changes. Defaults to "TinySemVer".
        git_user_email (str): The Git user email for committing changes. Defaults to "tinysemver@ashvardanian.com".
        push (bool): If True, pushes the changes to the remote GitHub repository. Defaults to True.
        github_token (Optional[str]): The GitHub token for authentication. If None, it attempts to use the GH_TOKEN environment variable. Defaults to None.
        github_repository (Optional[str]): The GitHub repository in 'owner/repo' format. If None, it attempts to use the GH_REPOSITORY environment variable. Defaults to None.
        default_branch (str): The default branch to push the changes to. Defaults to "main".

    Returns:
        SemVer: The new version after the bump.
    """

    repository_path = os.path.abspath(path) if path else os.getcwd()
    assert os.path.isdir(os.path.join(repository_path, ".git")), f"Not a Git repository: {repository_path}"

    def absolute(file_path: PathLike) -> str:
        return os.path.join(repository_path, os.fspath(file_path))  # an absolute `file_path` wins the join

    changelog_file = absolute(changelog_file) if changelog_file else None
    version_file = absolute(version_file) if version_file else None
    update_version_in = [(absolute(file), pattern) for file, pattern in update_version_in or []]
    update_major_version_in = [(absolute(file), pattern) for file, pattern in update_major_version_in or []]
    update_minor_version_in = [(absolute(file), pattern) for file, pattern in update_minor_version_in or []]
    update_patch_version_in = [(absolute(file), pattern) for file, pattern in update_patch_version_in or []]

    # Let's pull the environment variables from the GitHub Action context
    # https://cli.github.com/manual/gh_help_environment
    if not dry_run:
        github_token = github_token or os.getenv("GH_TOKEN")
        github_repository = github_repository or os.getenv("GH_REPOSITORY")
        if github_repository:
            assert re.fullmatch(
                r"[\w.-]+/[\w.-]+", github_repository
            ), "GitHub repository must be in the 'owner/repo' format"

    assert not version_file or (
        not os.path.exists(version_file) or os.path.isfile(version_file)
    ), f"Version file is missing or isn't a regular file: {version_file}"
    assert not changelog_file or (
        not os.path.exists(changelog_file) or os.path.isfile(changelog_file)
    ), f"Changelog file is missing or isn't a regular file: {changelog_file}"

    major_verbs = normalize_verbs(major_verbs, ["major", "breaking", "break"])
    minor_verbs = normalize_verbs(minor_verbs, ["minor", "feature", "feat", "add", "new"])
    patch_verbs = normalize_verbs(patch_verbs, ["patch", "fix", "bug", "improve", "docs", "make"])

    # A pre-release like `3.0.0-rc.1`, set by hand in the version file, names the next release
    last_tag = get_last_tag(repository_path)
    planned_text, planned_version, planned_suffix = "", SemVer(0, 0, 0), ""
    if version_file and os.path.exists(version_file):
        with open(version_file, "r") as file:
            planned_text = file.read().strip()
        planned_version, planned_suffix = parse_version(planned_text)
    assert last_tag or planned_suffix, f"No tags found in the repository: {repository_path}"

    current_version = parse_version(last_tag)[0] if last_tag else None
    if verbose and current_version:
        print_to_console(f"Current version: {current_version}")

    commits = get_commits_since_tag(repository_path, last_tag)
    if not len(commits):
        raise NoNewCommitsError(f"No new commits since {last_tag or 'the first commit'}")

    if verbose:
        print_to_console(f"? Commits since last tag: {len(commits)}")
        for commit_hash, message in commits:
            print_to_console(f"# {commit_hash}: {message}")

    major_commits, minor_commits, patch_commits = group_commits(commits, major_verbs, minor_verbs, patch_verbs)
    assert (
        len(major_commits) + len(minor_commits) + len(patch_commits)
    ), "No commit categories found to bump the version: " + ", ".join(commit.message for commit in commits)

    bump_type: BumpType
    if len(major_commits):
        bump_type = "major"
    elif len(minor_commits):
        bump_type = "minor"
    else:
        bump_type = "patch"
    if planned_suffix:
        assert (
            not current_version or planned_version > current_version
        ), f"Pre-release {planned_version}{planned_suffix} isn't above the last tag {last_tag}"
        new_version = planned_version
    else:
        assert current_version, f"No tags found in the repository: {repository_path}"
        new_version = bump_version(current_version, bump_type)
    if verbose:
        print_to_console(f"Next version: {new_version} (type: {bump_type})")

    new_version_str = str(new_version)
    if version_file:
        patch_with_regex(version_file, r"(.*)", new_version_str, dry_run=dry_run, verbose=verbose)

    if changelog_file:
        now = datetime.now()
        changes = f"\n## {now:%B %d, %Y}: v{new_version_str}\n"
        changes += convert_commits_to_message(major_commits, minor_commits, patch_commits)

        print_to_console(f"Will update file: {changelog_file}")
        if verbose:
            changes_lines = changes.count("\n") + 1
            print_to_console(f"? Appending {changes_lines} lines")
            for line in changes.split("\n"):
                print_to_console(f"+ {line}")

        if not dry_run:
            with open(changelog_file, "a") as file:
                file.write(changes)

    # `count=0`: a user pattern may match several lines - a README listing the dependency more than
    # once - and every one must move, unlike the single-line version file patched above.
    if update_version_in:
        for file_path, regex_pattern in update_version_in:
            patch_with_regex(
                file_path,
                regex_pattern,
                new_version_str,
                dry_run=dry_run,
                verbose=verbose,
                count=0,
                stale_version=planned_text if planned_suffix else "",
            )
    if not current_version or new_version.major != current_version.major:
        for file_path, regex_pattern in update_major_version_in:
            patch_with_regex(file_path, regex_pattern, str(new_version.major), dry_run=dry_run, verbose=verbose, count=0)
    if not current_version or new_version[:2] != current_version[:2]:
        for file_path, regex_pattern in update_minor_version_in:
            patch_with_regex(file_path, regex_pattern, str(new_version.minor), dry_run=dry_run, verbose=verbose, count=0)
    for file_path, regex_pattern in update_patch_version_in:
        patch_with_regex(file_path, regex_pattern, str(new_version.patch), dry_run=dry_run, verbose=verbose, count=0)

    if not dry_run:
        create_tag(
            repository_path=repository_path,
            version=new_version,
            user_name=git_user_name,
            user_email=git_user_email,
            default_branch=default_branch,
            github_token=github_token,
            github_repository=github_repository,
            push=push,
            create_release=create_release,
            push_moving_tags=push_moving_tags,
            major_commits=major_commits,
            minor_commits=minor_commits,
            patch_commits=patch_commits,
        )

    return new_version


def main() -> None:
    """
    TinySemVer entrypoint responsible for parsing CLI arguments and environment variables,
    preprocessing them and passing down to the `bump` function.
    """
    if "GITHUB_ACTIONS" not in os.environ:
        parser = argparse.ArgumentParser(description="Tiny Semantic Versioning tool")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Do not create a new tag",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            default=False,
            help="Print more information",
        )
        parser.add_argument(
            "--push",
            action="store_true",
            default=False,
            help="Push the new tag to the repository",
        )
        parser.add_argument(
            "--major-verbs",
            help="Comma-separated list of major verbs, like 'breaking,break,major'",
        )
        parser.add_argument(
            "--minor-verbs",
            help="Comma-separated list of minor verbs, like 'feature,minor,add,new'",
        )
        parser.add_argument(
            "--patch-verbs",
            help="Comma-separated list of patch verbs, like 'fix,patch,bug,improve,docs,make'",
        )
        parser.add_argument(
            "--changelog-file",
            help="Path to the changelog file, like 'CHANGELOG.md'",
        )
        parser.add_argument(
            "--version-file",
            help="Path to the version file, like 'VERSION'",
        )
        parser.add_argument(
            "--update-version-in",
            nargs=2,
            action="append",
            metavar=("FILE", "REGEX"),
            help="File path and regex pattern to update version",
        )
        parser.add_argument(
            "--update-major-version-in",
            nargs=2,
            action="append",
            metavar=("FILE", "REGEX"),
            help="File path and regex pattern to update major version",
        )
        parser.add_argument(
            "--update-minor-version-in",
            nargs=2,
            action="append",
            metavar=("FILE", "REGEX"),
            help="File path and regex pattern to update minor version",
        )
        parser.add_argument(
            "--update-patch-version-in",
            nargs=2,
            action="append",
            metavar=("FILE", "REGEX"),
            help="File path and regex pattern to update patch version",
        )
        parser.add_argument(
            "--path",
            default=".",
            help="Path to the git repository",
        )
        parser.add_argument(
            "--git-user-name",
            default="TinySemVer",
            help="Git user name for commits",
        )
        parser.add_argument(
            "--git-user-email",
            default="tinysemver@ashvardanian.com",
            help="Git user email for commits",
        )
        parser.add_argument(
            "--github-token",
            help="GitHub access token to push to protected branches, if not set will use GH_TOKEN env var",
        )
        parser.add_argument(
            "--default-branch",
            help="Default branch name of the repo, if not set will default to 'main'",
        )
        parser.add_argument(
            "--github-repository",
            help="GitHub repository in the 'owner/repo' format, if not set will use GH_REPOSITORY env var",
        )
        parser.add_argument(
            "--create-release",
            action="store_true",
            default=False,
            help="Create a GitHub release using the GitHub CLI",
        )
        parser.add_argument(
            "--push-moving-tags",
            action="store_true",
            default=False,
            help="Push moving major and minor version tags (requires force-push permissions)",
        )
        args = parser.parse_args()
    else:

        def patterns_from_environment(name: str) -> list[tuple[str, str]]:
            pairs = []
            for line in os.environ.get(name, "").splitlines():
                file_path, colon, regex_pattern = line.partition(":")
                assert not line or colon, f"Expected 'path:regex' in {name}, got: {line}"
                if line:
                    pairs.append((file_path, regex_pattern))
            return pairs

        args = argparse.Namespace()
        args.dry_run = os.environ.get("TINYSEMVER_DRY_RUN", "").lower() == "true"
        args.verbose = os.environ.get("TINYSEMVER_VERBOSE", "").lower() == "true"
        args.push = os.environ.get("TINYSEMVER_PUSH", "").lower() == "true"
        args.major_verbs = os.environ.get("TINYSEMVER_MAJOR_VERBS") or "breaking,break,major"
        args.minor_verbs = os.environ.get("TINYSEMVER_MINOR_VERBS") or "feature,feat,minor,add,new"
        args.patch_verbs = os.environ.get("TINYSEMVER_PATCH_VERBS") or "fix,patch,bug,improve,docs,make"
        args.default_branch = os.environ.get("TINYSEMVER_DEFAULT_BRANCH") or "main"
        args.changelog_file = os.environ.get("TINYSEMVER_CHANGELOG_FILE")
        args.version_file = os.environ.get("TINYSEMVER_VERSION_FILE")
        args.update_version_in = patterns_from_environment("TINYSEMVER_UPDATE_VERSION_IN")
        args.update_major_version_in = patterns_from_environment("TINYSEMVER_UPDATE_MAJOR_VERSION_IN")
        args.update_minor_version_in = patterns_from_environment("TINYSEMVER_UPDATE_MINOR_VERSION_IN")
        args.update_patch_version_in = patterns_from_environment("TINYSEMVER_UPDATE_PATCH_VERSION_IN")
        args.path = os.environ.get("TINYSEMVER_REPO_PATH")
        args.git_user_name = os.environ.get("TINYSEMVER_GIT_USER_NAME", "TinySemVer")
        args.git_user_email = os.environ.get("TINYSEMVER_GIT_USER_EMAIL", "tinysemver@ashvardanian.com")
        args.github_token = os.environ.get("GITHUB_TOKEN")
        args.github_repository = os.environ.get("GITHUB_REPOSITORY")
        args.create_release = os.environ.get("TINYSEMVER_CREATE_RELEASE", "").lower() == "true"
        args.push_moving_tags = os.environ.get("TINYSEMVER_PUSH_MOVING_TAGS", "").lower() == "true"

    # It's common for a CI pipeline to have multiple broken settings or missing files.
    # For the best user experience, we want to catch all errors and print them at once,
    # instead of failing at the first error and exiting the script... forcing the user to
    # fix one issue at a time, and re-run the script multiple times.
    #
    # TODO: To achieve this, on even on "real runs", we should first perform a "dry run" to catch,
    # accumulate all errors

    try:
        bump(
            path=args.path,
            dry_run=args.dry_run,
            verbose=args.verbose,
            major_verbs=args.major_verbs,
            minor_verbs=args.minor_verbs,
            patch_verbs=args.patch_verbs,
            changelog_file=args.changelog_file,
            version_file=args.version_file,
            update_version_in=args.update_version_in,
            update_major_version_in=args.update_major_version_in,
            update_minor_version_in=args.update_minor_version_in,
            update_patch_version_in=args.update_patch_version_in,
            git_user_name=args.git_user_name,
            git_user_email=args.git_user_email,
            github_token=args.github_token,
            github_repository=args.github_repository,
            default_branch=args.default_branch or "main",
            push=args.push,
            create_release=args.create_release,
            push_moving_tags=args.push_moving_tags,
        )
    except NoNewCommitsError as e:
        print(f"! {e}")
        sys.exit(0)
    except AssertionError as e:
        print(f"! {e}")
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
