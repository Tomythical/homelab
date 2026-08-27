#!/usr/bin/env python3
"""Regenerate vendored Tailscale operator CRDs for an exact release tag."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request

import yaml

REPOSITORY = "tailscale/tailscale"
RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
CRD_FILENAME = re.compile(r"^tailscale\.com_[a-z0-9-]+\.yaml$")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def release_crd_urls(version: str) -> list[str]:
    directory = (
        f"https://api.github.com/repos/{REPOSITORY}/contents/"
        f"cmd/k8s-operator/deploy/crds?ref={version}"
    )
    entries = json.loads(fetch(directory))
    urls = sorted(
        entry["download_url"]
        for entry in entries
        if entry.get("type") == "file" and CRD_FILENAME.fullmatch(entry.get("name", ""))
    )
    if not urls:
        raise ValueError(f"no Tailscale CRD files found for {version}")
    return urls


def validate_bundle(content: str) -> None:
    documents = [document for document in yaml.safe_load_all(content) if document]
    if not documents:
        raise ValueError("generated CRD bundle is empty")

    names: set[str] = set()
    for document in documents:
        if document.get("apiVersion") != "apiextensions.k8s.io/v1":
            raise ValueError("bundle contains a non-v1 CRD document")
        if document.get("kind") != "CustomResourceDefinition":
            raise ValueError("bundle contains a non-CRD document")
        name = document.get("metadata", {}).get("name", "")
        if not name.endswith(".tailscale.com") or name in names:
            raise ValueError(f"invalid or duplicate CRD name: {name!r}")
        if document.get("spec", {}).get("group") != "tailscale.com":
            raise ValueError(f"CRD has unexpected API group: {name!r}")
        names.add(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="Tailscale release tag, e.g. v1.102.3")
    parser.add_argument(
        "--output",
        default="infra/crds/tailscale/tailscale.yaml",
        type=pathlib.Path,
        help="combined CRD bundle path",
    )
    args = parser.parse_args()

    if not RELEASE_TAG.fullmatch(args.version):
        parser.error("version must be a valid v-prefixed Tailscale release tag")

    bundle = "\n---\n".join(
        fetch(url).decode("utf-8").rstrip() for url in release_crd_urls(args.version)
    ) + "\n"
    validate_bundle(bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(bundle)
    print(f"Wrote {len(release_crd_urls(args.version))} Tailscale {args.version} CRDs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
