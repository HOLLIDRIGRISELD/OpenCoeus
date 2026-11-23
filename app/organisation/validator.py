"""Filesystem path validation for organisation plans.

Every recommendation is re-validated immediately before a decision and again
immediately before it is executed. Validation is deliberately conservative:

* destinations must stay inside the organisation root (no ``..`` escapes);
* filenames must be portable across Windows, macOS and Linux;
* an existing path is never treated as replaceable;
* a parent component that is a file is a conflict, not something to work around.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def path_key(path: Path) -> str:
    """Return a comparable key for filesystem paths on case-insensitive hosts."""

    return os.path.normcase(str(Path(path).resolve(strict=False)))


@dataclass(slots=True)
class Issue:
    """One validation finding."""

    code: str
    message: str
    severity: str = "error"

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(slots=True)
class DestinationCheck:
    """Validation outcome for a proposed destination path."""

    destination: Path
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.is_error]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if not issue.is_error]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def message(self) -> str | None:
        return self.errors[0].message if self.errors else None


class PathGuard:
    """Validates destinations against an organisation root.

    Args:
        root: Directory that must contain every destination.
        max_filename_length: Conservative filename limit (portable headroom).
        max_path_length: Safety limit for the complete path string.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_filename_length: int = 120,
        max_path_length: int = 3800,
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.max_filename_length = max_filename_length
        self.max_path_length = max_path_length

    def contains(self, path: Path) -> bool:
        """Return True when ``path`` resolves inside the organisation root."""

        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            return candidate.resolve(strict=False).is_relative_to(self.root)
        except OSError:
            return False

    def check_filename(self, name: str) -> list[Issue]:
        """Validate the final path component."""

        issues: list[Issue] = []
        if not name or not name.strip():
            issues.append(Issue("empty_filename", "The proposed filename is empty."))
            return issues
        if name in {".", ".."}:
            issues.append(Issue("reserved_name", f"'{name}' is not a valid filename."))
        if _INVALID_FILENAME.search(name):
            issues.append(
                Issue(
                    "invalid_characters",
                    f"'{name}' contains characters that are not valid in portable filenames.",
                )
            )
        if name.endswith((" ", ".")):
            issues.append(
                Issue("trailing_character", "Filenames must not end with a space or a dot.")
            )
        if len(name) > self.max_filename_length:
            issues.append(
                Issue(
                    "filename_too_long",
                    f"The filename is longer than {self.max_filename_length} characters.",
                )
            )
        stem = Path(name).stem.lower()
        if stem in _WINDOWS_RESERVED:
            issues.append(
                Issue("reserved_name", f"'{stem}' is a reserved device name on Windows.")
            )
        return issues

    def check_source(self, source: Path) -> list[Issue]:
        """Validate the current location of a file."""

        issues: list[Issue] = []
        if not source.exists():
            issues.append(
                Issue("source_missing", f"The file no longer exists at {source}.", "error")
            )
            return issues
        if not source.is_file():
            issues.append(Issue("source_not_file", f"{source} is not a regular file."))
        if not self.contains(source):
            issues.append(
                Issue(
                    "source_outside_root",
                    "The file is outside the organisation root; it will be moved into it.",
                    "warning",
                )
            )
        return issues

    def check_destination(
        self,
        destination: Path,
        *,
        source: Path | None = None,
        occupied: set[str] | None = None,
        vacating: set[str] | None = None,
    ) -> DestinationCheck:
        """Validate a proposed destination.

        Args:
            destination: Absolute or root-relative target path.
            source: Current path, excluded from the "already exists" check.
            occupied: Lower-cased absolute paths already claimed by other
                actions in the same plan.
            vacating: Paths that another action in the same plan will leave free.
        """

        candidate = Path(destination)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        check = DestinationCheck(candidate)

        if ".." in Path(str(destination)).parts:
            check.issues.append(
                Issue(
                    "path_traversal",
                    "The destination contains '..' and could escape the organisation root.",
                )
            )
            return check

        resolved = candidate.resolve(strict=False)
        if not self.contains(resolved):
            check.issues.append(
                Issue(
                    "outside_root",
                    f"The destination {resolved} is outside the organisation root {self.root}.",
                )
            )
            return check

        check.issues.extend(self.check_filename(candidate.name))

        if len(str(candidate)) > self.max_path_length:
            check.issues.append(
                Issue("path_too_long", "The destination path is too long for this filesystem.")
            )

        parent = candidate.parent
        while parent != self.root and self.contains(parent):
            if parent.exists():
                if not parent.is_dir():
                    check.issues.append(
                        Issue(
                            "parent_not_directory",
                            f"Cannot create a folder because {parent} is a file.",
                        )
                    )
                break
            parent = parent.parent

        if candidate.exists():
            same_file = False
            if source is not None:
                try:
                    same_file = candidate.resolve() == source.resolve()
                except OSError:
                    same_file = False
            if not same_file and path_key(candidate) not in (vacating or set()):
                kind = "folder" if candidate.is_dir() else "file"
                check.issues.append(
                    Issue(
                        "destination_exists",
                        f"A {kind} already exists at {candidate}. OpenCoeus never overwrites.",
                    )
                )

        if occupied and str(resolved).lower() in occupied:
            check.issues.append(
                Issue(
                    "duplicate_target",
                    "Another planned action targets the same destination.",
                )
            )
        return check


