from __future__ import annotations

from models.schemas import StandardLibrary


def allowed_categories(library: StandardLibrary | None) -> set[str]:
    if library is None:
        return {"other"}
    return (
        {entry.category for entry in library.entries}
        | set(library.heading_aliases.values())
        | {item.category for item in library.category_keywords}
        | {"other"}
    )


def resolve_category(
    title: str,
    model_category: str,
    text: str,
    library: StandardLibrary | None,
) -> tuple[str, str]:
    if library is None:
        return "other", "unassigned"
    mapped = library.heading_aliases.get(title.strip().lower())
    if mapped:
        return mapped, "heading"
    if model_category in allowed_categories(library) and model_category != "other":
        return model_category, "model"
    lowered = " ".join(text.replace("\u00ad", "-").split()).lower()
    for item in library.category_keywords:
        if any(phrase in lowered for phrase in item.phrases):
            return item.category, "keyword"
    return "other", "keyword"
