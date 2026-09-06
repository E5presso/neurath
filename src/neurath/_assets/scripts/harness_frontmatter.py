"""Neurath Markdown frontmatter를 dependency 없이 일관되게 해석합니다."""

from __future__ import annotations

from dataclasses import dataclass


class MarkdownFrontmatterError(ValueError):
    """Markdown frontmatter가 deterministic subset을 만족하지 않을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class MarkdownFrontmatter:
    """Parsed top-level metadata와 frontmatter를 제외한 body입니다."""

    metadata: dict[str, object]
    """Frontmatter에서 해석한 top-level scalar와 tuple metadata입니다."""

    body: str
    """Frontmatter delimiter와 metadata를 제거한 Markdown body입니다."""

    @property
    def paths(self) -> tuple[str, ...]:
        """Non-empty `paths` list를 반환하며 없거나 빈 값은 always-on으로 둡니다.

        Returns:
            Canonical path scope tuple이며 값이 없으면 빈 tuple입니다.

        Raises:
            MarkdownFrontmatterError: `paths`가 non-empty string tuple이 아니면 발생합니다.
        """
        raw_paths = self.metadata.get("paths", ())
        if not isinstance(raw_paths, tuple) or any(
            not isinstance(item, str) or not item for item in raw_paths
        ):
            raise MarkdownFrontmatterError("paths must be a string list")
        return raw_paths


def parse_markdown_frontmatter(text: str) -> MarkdownFrontmatter:
    """Neurath가 사용하는 top-level scalar/list YAML subset을 읽습니다.

    Args:
        text: Optional frontmatter를 포함한 Markdown source입니다.

    Returns:
        Parsed metadata와 frontmatter를 제외한 body입니다.

    Raises:
        MarkdownFrontmatterError: Frontmatter가 닫히지 않았거나 지원 subset을 위반하면
            발생합니다.
    """
    if not text.startswith("---\n"):
        return MarkdownFrontmatter(metadata={}, body=text)
    lines = text.splitlines()
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise MarkdownFrontmatterError("frontmatter must have a closing delimiter") from error
    metadata: dict[str, object] = {}
    list_key: str | None = None
    for line in lines[1:closing]:
        if line.startswith("  - ") and list_key is not None:
            current = metadata[list_key]
            if not isinstance(current, list):
                raise MarkdownFrontmatterError(f"frontmatter field is not a list: {list_key}")
            current.append(_scalar(line[4:].strip()))
            continue
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not raw_value:
            metadata[key] = []
            list_key = key
            continue
        metadata[key] = _scalar(raw_value)
        list_key = None
    for key, value in tuple(metadata.items()):
        if isinstance(value, list):
            metadata[key] = tuple(value)
    return MarkdownFrontmatter(
        metadata=metadata,
        body="\n".join(lines[closing + 1 :]).lstrip("\n"),
    )


def _scalar(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return ()
        return tuple(str(_scalar(item.strip())) for item in inner.split(","))
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
