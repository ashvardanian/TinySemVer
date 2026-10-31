"""TinySemVer turns Conventional Commits into Semantic Versioning releases.

Example:
    >>> from tinysemver import bump
    >>> new_version = bump(
    ...     path=".",
    ...     dry_run=True,
    ...     verbose=True,
    ...     version_file="VERSION",
    ...     changelog_file="CHANGELOG.md"
    ... )
"""

from tinysemver.tinysemver import (
    BumpType,
    ChangeDiff,
    Commit,
    NoNewCommitsError,
    PathLike,
    SemVer,
    bump,
    bump_version,
    commit_starts_with_verb,
    convert_commits_to_message,
    create_tag,
    get_commits_since_tag,
    get_diff_for_commit,
    get_last_tag,
    group_commits,
    normalize_verbs,
    parse_version,
    patch_with_regex,
)

__version__ = "3.1.0"
__all__ = [
    "BumpType",
    "ChangeDiff",
    "Commit",
    "NoNewCommitsError",
    "PathLike",
    "SemVer",
    "bump",
    "bump_version",
    "commit_starts_with_verb",
    "convert_commits_to_message",
    "create_tag",
    "get_commits_since_tag",
    "get_diff_for_commit",
    "get_last_tag",
    "group_commits",
    "normalize_verbs",
    "parse_version",
    "patch_with_regex",
]
