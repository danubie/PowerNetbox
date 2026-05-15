"""Homepage macros: cmdlet count, latest release, compat table."""

import re
from pathlib import Path


# Resolve PowerNetbox.psd1 relative to this file's location, not CWD.
# docs-build/macros/homepage.py -> docs-build/macros -> docs-build -> worktree root
PSD1_PATH = Path(__file__).parent.parent.parent / "PowerNetbox.psd1"

# Release notes live in docs-build/generated/release-notes/ (CI-generated) or
# fall back to docs/release-notes/ (already-merged copy).
_WORKTREE_ROOT = Path(__file__).parent.parent.parent
_GENERATED_RELEASE_DIR = _WORKTREE_ROOT / "docs-build" / "generated" / "release-notes"
_DOCS_RELEASE_DIR = _WORKTREE_ROOT / "docs" / "release-notes"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?\.md$")
_RELEASED_RE = re.compile(r"^Released (\d{4}-\d{2}-\d{2})\b")

# The compat table is DERIVED, not hand-maintained. Source of truth = the CI
# integration matrix (what is actually tested) + the module manifest.
_INTEGRATION_YML = _WORKTREE_ROOT / ".github" / "workflows" / "integration.yml"
_MATRIX_NETBOX_RE = re.compile(r'^\s*netbox_short:\s*"?([\d.]+)"?\s*$', re.MULTILINE)
_PSD1_VERSION_RE = re.compile(r"ModuleVersion\s*=\s*'([\d.]+)'")
_PSD1_PSVER_RE = re.compile(r"PowerShellVersion\s*=\s*'([\d.]+)'")


def _netbox_tested_versions() -> list[str]:
    """NetBox versions from the CI integration matrix, in declared order
    (minimum -> ... -> primary target last)."""
    text = _INTEGRATION_YML.read_text(encoding="utf-8")
    seen, ordered = set(), []
    for v in _MATRIX_NETBOX_RE.findall(text):
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _module_version_line() -> tuple[str, str]:
    """Return (powernetbox_series, powershell_support) from the manifest.
    e.g. ('4.6.0.x', '5.1+ / 7+')."""
    content = PSD1_PATH.read_text(encoding="utf-8-sig")
    m = _PSD1_VERSION_RE.search(content)
    series = "current"
    if m:
        parts = m.group(1).split(".")
        series = ".".join(parts[:3]) + ".x" if len(parts) >= 3 else m.group(1)
    ps = _PSD1_PSVER_RE.search(content)
    ps_support = f"{ps.group(1)}+ / 7+" if ps else "5.1+ / 7+"
    return series, ps_support


def _count_public_cmdlets() -> int:
    """Count Verb-NB* entries in the FunctionsToExport block of the psd1."""
    # utf-8-sig strips BOM if present
    content = PSD1_PATH.read_text(encoding="utf-8-sig")
    entries = re.findall(r"'([A-Z][a-z]+-NB[^']+)'", content)
    return len(entries)


def _parse_version(filename: str) -> tuple:
    """Return a tuple of ints for semver sorting from a filename like '4.5.8.1.md'."""
    stem = filename[:-3]  # strip .md
    return tuple(int(x) for x in stem.split("."))


def _fetch_latest_release() -> dict | None:
    """Read the newest release note from disk and return a dict matching the old
    GitHub API shape: {tag_name, published_at, body}. Returns None on failure."""
    # Prefer the CI-generated directory; fall back to docs/release-notes/
    release_dir = None
    for candidate in (_GENERATED_RELEASE_DIR, _DOCS_RELEASE_DIR):
        if candidate.is_dir():
            release_dir = candidate
            break

    if release_dir is None:
        return None

    version_files = [f.name for f in release_dir.iterdir() if _VERSION_RE.match(f.name)]
    if not version_files:
        return None

    # Sort descending by semver and pick the newest
    latest_filename = sorted(version_files, key=_parse_version, reverse=True)[0]
    version = latest_filename[:-3]  # strip .md

    text = (release_dir / latest_filename).read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the "Released YYYY-MM-DD" line
    date = "unknown"
    body_start = 0
    for i, line in enumerate(lines):
        m = _RELEASED_RE.match(line)
        if m:
            date = m.group(1)
            body_start = i + 1
            break

    # Everything after the Released line is the body (skip leading blank lines)
    body_lines = lines[body_start:]
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]

    return {
        "tag_name": f"v{version}",
        "published_at": f"{date}T00:00:00Z",
        "body": "\n".join(body_lines),
    }


def register_homepage(env):
    """Register homepage macros with the mkdocs-macros env."""

    @env.macro
    def cmdlet_count() -> str:
        return str(_count_public_cmdlets())

    @env.macro
    def latest_release() -> str:
        release = _fetch_latest_release()
        if release is None:
            return "*(release info unavailable in this build context)*"

        tag = release["tag_name"]
        version = tag.lstrip("v")
        date = release["published_at"][:10]
        body_lines = release.get("body", "").splitlines()[:6]
        preview = "\n".join(body_lines)

        return (
            f"### [v{version}](release-notes/{version}.md) - {date}\n\n"
            f"{preview}\n\n"
            f"[Full changelog](release-notes/{version}.md)"
        )

    @env.macro
    def compat_table() -> str:
        """Compatibility table DERIVED from the CI integration matrix
        (.github/workflows/integration.yml) and the module manifest.
        Do not hand-edit the values here — change the CI matrix / bump
        the manifest and this table follows automatically."""
        header = (
            "| PowerNetbox | NetBox target | Also supports | PowerShell |\n"
            "|---|---|---|---|"
        )
        try:
            tested = _netbox_tested_versions()
            series, ps_support = _module_version_line()
            if not tested:
                raise ValueError("empty CI matrix")
            target = tested[-1]                 # primary target = highest/last
            also = ", ".join(tested[:-1]) or "—"
            return f"{header}\n| {series} | {target} | {also} | {ps_support} |"
        except Exception:
            # Never break the docs build on a parse failure — degrade gracefully.
            return (
                f"{header}\n"
                "| current | see CI matrix | see CI matrix | 5.1+ / 7+ |\n\n"
                "*(compatibility detail: "
                "[integration matrix]"
                "(https://github.com/ctrl-alt-automate/PowerNetbox/blob/dev/.github/workflows/integration.yml))*"
            )
