# TinySemVer

![TinySemVer Banner](https://github.com/ashvardanian/ashvardanian/blob/master/repositories/TinySemVer.jpg)

> [!WARNING]
> TinySemVer is deprecated and archived.
> Automated versioning needs a CI credential that can push past branch protection, which in practice means long-lived tokens readable by every workflow and third-party Action in every repository.
> That attack surface grows far faster than the value of automatic version bumps.
> Bump versions by hand in a `Release: vX.Y.Z` commit, publish with `gh release create`, and let CI publish on `release: published` through trusted publishing.

__TinySemVer__ turns [Conventional Commits](https://www.conventionalcommits.org/) into [Semantic Versioning](https://semver.org/) releases from a single short Python file.
It reads the commits since the last tag, picks the next version, patches it into every file you name, extends the changelog, commits, tags and optionally publishes a GitHub release.

```sh
$ uvx tinysemver --dry-run --verbose
> Current version: 1.2.2
> Next version: 1.3.0
```

`uvx` runs it straight from PyPI, while `pip install tinysemver` or `uv tool install tinysemver` keep it installed.
A dry run changes nothing, so it's safe anywhere.

## Commit Verbs

The first word of each commit title decides the bump, in any case, followed by a colon or a space:

- Major: `breaking`, `break`, `major`.
- Minor: `feature`, `feat`, `minor`, `add`, `new`.
- Patch: `fix`, `patch`, `bug`, `improve`, `docs`, `make`.

A commit matching none of them stops the release, and merge commits are skipped.
Replace any list with `--major-verbs`, `--minor-verbs` or `--patch-verbs`.

## Command Line

Each file that embeds the version takes a path and a regular expression with exactly one capturing group, which receives the new version:

```sh
$ tinysemver --verbose \
    --changelog-file 'CHANGELOG.md' \
    --version-file 'VERSION' \
    --update-version-in 'pyproject.toml' '^version = "(\d+\.\d+\.\d+)"' \
    --update-version-in 'package.json' '"version": "(\d+\.\d+\.\d+)"' \
    --update-major-version-in 'include/project.h' '^#define PROJECT_VERSION_MAJOR (\d+)' \
    --update-minor-version-in 'include/project.h' '^#define PROJECT_VERSION_MINOR (\d+)' \
    --update-patch-version-in 'include/project.h' '^#define PROJECT_VERSION_PATCH (\d+)' \
    --github-repository 'owner/project' \
    --push
```

Prefer strict groups like `(\d+\.\d+\.\d+)` over `(.*)`.
Without `--push`, the release commit and tag stay local, and `git reset --soft HEAD~1` undoes the commit.
Run `tinysemver --help` for every flag.

## GitHub Action

The [GitHub Action](https://github.com/marketplace/actions/tinysemver) takes the same settings as inputs, writing patterns as `path:regex` lines in a `|` block.
A dry run on every pull request catches a commit title without a verb, or a pattern that stopped matching:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0 # TinySemVer needs the tags
- uses: ashvardanian/tinysemver@v3
  with:
    dry-run: "true"
    verbose: "true"
    version-file: "VERSION"
    update-version-in: |
      pyproject.toml:^version = "(\d+\.\d+\.\d+)"
      package.json:"version": "(\d+\.\d+\.\d+)"
```

Pushing from CI takes `push: "true"` and a `github-token` that bypasses your branch protection, with `persist-credentials: false` on the checkout.
That token is the attack surface the warning above describes.

## Release Candidates

TinySemVer never invents pre-releases, but it honors a `-rc.N` set by hand in the version file, to let people opt into a project before its API is stable.
While the version file holds `3.0.0-rc.1`, the next release is exactly `3.0.0`, whatever the verbs say, and its changelog lists every commit since the last final tag.
Pre-release tags never serve as the base, and the `-rc.N` suffix is stripped from every patched file, so the usual `(\d+\.\d+\.\d+)` patterns keep matching.
A candidate that isn't above the last final tag stops the release, and other pre-release or build suffixes are rejected.

## Moving Tags

With `--push-moving-tags`, or `push-moving-tags: "true"` in the Action, each `v3.1.0` release also moves the `v3` and `v3.1` aliases, the way GitHub Actions are usually pinned:

```yaml
uses: ashvardanian/tinysemver@v3       # non-breaking updates
uses: ashvardanian/tinysemver@v3.1     # patch updates
uses: ashvardanian/tinysemver@v3.1.0   # never changes
```

Moving a tag is a force-push, so it needs permission to bypass tag protection.
If an alias can't be pushed, TinySemVer warns and moves on, because the release itself is already published.

## Why Another Tool

I used to release my 10+ projects with [semantic-release](https://github.com/semantic-release/semantic-release).
Then a breaking change deep in its dependencies broke all of their CI pipelines for a month, affecting dozens of companies using those libraries.
Tracing it meant wading through __363K lines of JavaScript__:

```sh
$ .../node_modules$ cloc .
   10751 text files.
    7809 unique files.
    3498 files ignored.

github.com/AlDanial/cloc v 1.90  T=2.96 s (2450.6 files/s, 300331.1 lines/s)
--------------------------------------------------------------------------------
Language                      files          blank        comment           code
--------------------------------------------------------------------------------
JavaScript                     4902          48080          81205         363424
TypeScript                      732           7008          73034          79367
...                             ...            ...            ...            ...
--------------------------------------------------------------------------------
SUM:                           7256          90782         164390         634071
--------------------------------------------------------------------------------
```

TinySemVer is one Python file with about 600 lines of code, and `rich` for colored output as its only dependency.

## What's Missing

- Commit scopes, like `feat(scope): add new feature`, which make little sense for most projects.
- GenAI.

TinySemVer accepts only `MAJOR.MINOR.PATCH` and a hand-set `-rc.N`, while SemVer 2.0 allows [many more forms](https://regex101.com/r/Ly7O1x/3/), like `1.0.0-alpha.beta.1` or `2.0.0+build.1848`.

## Real-World Example

[USearch](https://github.com/unum-cloud/usearch) has bindings to 10 programming languages, and its version lives in a dozen files:

```sh
$ tinysemver --dry-run --verbose \
    --version-file 'VERSION' \
    --update-version-in 'package.json' '"version": "(\d+\.\d+\.\d+)"' \
    --update-version-in 'CITATION.cff' '^version: (\d+\.\d+\.\d+)' \
    --update-version-in 'Cargo.toml' '^version = "(\d+\.\d+\.\d+)"' \
    --update-version-in 'wasmer.toml' '^version = "(\d+\.\d+\.\d+)"' \
    --update-version-in 'conanfile.py' 'version = "(\d+\.\d+\.\d+)"' \
    --update-version-in 'java/README.md' "usearchVersion = '(\d+\.\d+\.\d+)'" \
    --update-version-in 'java/README.md' "version: '(\d+\.\d+\.\d+)'" \
    --update-version-in 'README.md' 'version = {(\d+\.\d+\.\d+)}' \
    --update-version-in 'csharp/nuget/nuget-package.props' '>(\d+\.\d+\.\d+)</Version>' \
    --update-version-in 'CMakeLists.txt' 'VERSION (\d+\.\d+\.\d+)' \
    --update-major-version-in 'include/usearch/index.hpp' '^#define USEARCH_VERSION_MAJOR (\d+)' \
    --update-minor-version-in 'include/usearch/index.hpp' '^#define USEARCH_VERSION_MINOR (\d+)' \
    --update-patch-version-in 'include/usearch/index.hpp' '^#define USEARCH_VERSION_PATCH (\d+)'
```
