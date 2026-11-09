#!/usr/bin/env python3
"""Resolve BattleScribe/New Recruit catalogue XML across multiple .cat files.

Standard-library only. This is an importer/resolver, not a rules interpreter.
It preserves source XML fragments and link provenance; it never infers rules
from proximity or silently substitutes a missing target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attrs(el: ET.Element) -> dict[str, str]:
    return dict(el.attrib)


def text_content(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return "".join(el.itertext()).strip()


def serialise(el: ET.Element) -> str:
    return ET.tostring(el, encoding="unicode")


def direct_children(el: ET.Element, name: str) -> list[ET.Element]:
    return [x for x in list(el) if local(x.tag) == name]


def descendants(el: ET.Element, name: str) -> list[ET.Element]:
    return [x for x in el.iter() if x is not el and local(x.tag) == name]


@dataclass
class Catalogue:
    path: str
    root: ET.Element
    catalogue_id: str
    name: str
    revision: str | None
    sha256: str

    @classmethod
    def load(cls, path: Path) -> "Catalogue":
        raw = path.read_bytes()
        root = ET.fromstring(raw)
        if local(root.tag) != "catalogue":
            raise ValueError(f"{path}: root element is {local(root.tag)!r}, expected 'catalogue'")
        return cls(
            path=str(path),
            root=root,
            catalogue_id=root.get("id", ""),
            name=root.get("name", path.stem),
            revision=root.get("revision"),
            sha256=hashlib.sha256(raw).hexdigest(),
        )


class CatalogueResolver:
    ENTRY_TAGS = {"selectionEntry", "selectionEntryGroup", "profile"}

    def __init__(self, catalogues: Iterable[Catalogue]):
        self.catalogues = list(catalogues)
        self.by_catalogue_id = {c.catalogue_id: c for c in self.catalogues if c.catalogue_id}
        self.nodes: dict[str, tuple[Catalogue, ET.Element]] = {}
        self.duplicates: list[dict[str, Any]] = []
        for cat in self.catalogues:
            for node in cat.root.iter():
                if local(node.tag) not in self.ENTRY_TAGS:
                    continue
                node_id = node.get("id")
                if not node_id:
                    continue
                if node_id in self.nodes:
                    self.duplicates.append({
                        "id": node_id,
                        "first": self.nodes[node_id][0].path,
                        "duplicate": cat.path,
                        "tag": local(node.tag),
                    })
                    continue
                self.nodes[node_id] = (cat, node)

    def catalogue_dependencies(self, cat: Catalogue) -> list[dict[str, Any]]:
        result = []
        for link in descendants(cat.root, "catalogueLink"):
            target = link.get("targetId", "")
            resolved = self.by_catalogue_id.get(target)
            result.append({
                "link": attrs(link),
                "resolved": bool(resolved),
                "targetCatalogue": resolved.name if resolved else None,
                "targetPath": resolved.path if resolved else None,
                "conditions": [serialise(x) for x in descendants(link, "condition")],
            })
        return result

    def resolve_id(self, target_id: str) -> tuple[Catalogue, ET.Element] | None:
        return self.nodes.get(target_id)

    def _profile(self, cat: Catalogue, profile: ET.Element) -> dict[str, Any]:
        characteristics = []
        for ch in descendants(profile, "characteristic"):
            characteristics.append({
                "name": ch.get("name"),
                "typeId": ch.get("typeId"),
                "value": text_content(ch),
                "xml": serialise(ch),
            })
        return {
            "id": profile.get("id"),
            "name": profile.get("name"),
            "typeName": profile.get("typeName"),
            "typeId": profile.get("typeId"),
            "sourceCatalogue": cat.name,
            "sourcePath": cat.path,
            "characteristics": characteristics,
            "xml": serialise(profile),
        }

    def _entry(self, cat: Catalogue, node: ET.Element, stack: tuple[str, ...]) -> dict[str, Any]:
        node_id = node.get("id", "")
        result: dict[str, Any] = {
            "nodeType": local(node.tag),
            "id": node_id,
            "name": node.get("name"),
            "entryType": node.get("type"),
            "sourceCatalogue": cat.name,
            "sourceCatalogueId": cat.catalogue_id,
            "sourcePath": cat.path,
            "profiles": [],
            "children": [],
            "links": [],
            "constraints": [],
            "modifiers": [],
            "conditions": [],
            "xml": serialise(node),
        }
        if node_id and node_id in stack:
            result["cycleDetected"] = True
            return result

        for profile in descendants(node, "profile"):
            result["profiles"].append(self._profile(cat, profile))

        for tag, target_key in (("constraint", "constraints"), ("modifier", "modifiers"), ("condition", "conditions")):
            result[target_key] = [serialise(x) for x in descendants(node, tag)]

        next_stack = stack + ((node_id,) if node_id else ())
        for child in list(node):
            kind = local(child.tag)
            if kind in {"selectionEntry", "selectionEntryGroup"}:
                result["children"].append(self._entry(cat, child, next_stack))
            elif kind == "entryLink":
                result["links"].append(self._resolve_link(cat, child, next_stack))
        return result

    def _resolve_link(self, importer: Catalogue, link: ET.Element, stack: tuple[str, ...]) -> dict[str, Any]:
        target_id = link.get("targetId", "")
        found = self.resolve_id(target_id)
        record: dict[str, Any] = {
            "link": attrs(link),
            "importingCatalogue": importer.name,
            "importingCatalogueId": importer.catalogue_id,
            "importingPath": importer.path,
            "costs": [serialise(x) for x in descendants(link, "cost")],
            "constraints": [serialise(x) for x in descendants(link, "constraint")],
            "modifiers": [serialise(x) for x in descendants(link, "modifier")],
            "conditions": [serialise(x) for x in descendants(link, "condition")],
            "resolved": found is not None,
        }
        if not found:
            record["unresolvedReason"] = "targetId not found in supplied catalogues"
            return record
        target_cat, target_node = found
        record["targetCatalogue"] = target_cat.name
        record["targetPath"] = target_cat.path
        record["target"] = self._entry(target_cat, target_node, stack)
        return record

    def resolve_catalogue(self, cat: Catalogue) -> dict[str, Any]:
        roots = []
        for child in list(cat.root):
            if local(child.tag) in {"selectionEntry", "selectionEntryGroup"}:
                roots.append(self._entry(cat, child, ()))
            elif local(child.tag) == "entryLink":
                roots.append(self._resolve_link(cat, child, ()))
        return {
            "catalogue": {
                "name": cat.name,
                "id": cat.catalogue_id,
                "revision": cat.revision,
                "path": cat.path,
                "sha256": cat.sha256,
            },
            "dependencies": self.catalogue_dependencies(cat),
            "roots": roots,
        }

    def report(self, selected: Catalogue) -> dict[str, Any]:
        resolved = self.resolve_catalogue(selected)
        stats = {"links": 0, "resolved": 0, "unresolved": 0, "cycles": 0}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if "resolved" in value and "link" in value:
                    stats["links"] += 1
                    stats["resolved" if value["resolved"] else "unresolved"] += 1
                if value.get("cycleDetected"):
                    stats["cycles"] += 1
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(resolved)
        resolved["resolverDiagnostics"] = {
            "catalogueCount": len(self.catalogues),
            "indexedNodeCount": len(self.nodes),
            "duplicateIds": self.duplicates,
            **stats,
        }
        return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, help="Name or path of the catalogue to resolve")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("files", nargs="+", help="All .cat files participating in resolution")
    args = parser.parse_args()

    catalogues = [Catalogue.load(Path(p)) for p in args.files]
    selected = next((c for c in catalogues if c.name == args.catalogue or c.path == args.catalogue or Path(c.path).name == args.catalogue), None)
    if selected is None:
        parser.error(f"selected catalogue {args.catalogue!r} not found among input files")

    resolver = CatalogueResolver(catalogues)
    result = resolver.report(selected)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["resolverDiagnostics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
