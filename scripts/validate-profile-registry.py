#!/usr/bin/env python3
"""Validate profile ownership and channel isolation before deployment."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import yaml


def fail(message: str) -> None:
    raise SystemExit(f"FAIL {message}")


def service_exists(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "cat", service],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "profile-registry.yaml",
    )
    args = parser.parse_args()

    if not args.registry.is_file():
        fail(f"registry missing: {args.registry}")

    data = yaml.safe_load(args.registry.read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles")
    channel_owners = data.get("channel_owners")
    retired = set(data.get("retired_profiles") or [])

    if not isinstance(profiles, list) or not profiles:
        fail("profiles must be a non-empty list")
    if not isinstance(channel_owners, dict):
        fail("channel_owners must be a mapping")

    profile_ids = [profile.get("id") for profile in profiles]
    if any(not profile_id for profile_id in profile_ids):
        fail("every profile must define an id")
    if len(profile_ids) != len(set(profile_ids)):
        fail("profile ids must be unique")
    if retired.intersection(profile_ids):
        fail("retired profiles must not appear in profiles")

    by_id = {profile["id"]: profile for profile in profiles}
    for channel, owner in channel_owners.items():
        profile = by_id.get(owner)
        if profile is None:
            fail(f"{channel} owner is not registered: {owner}")
        if profile["primary_channel"] != channel:
            fail(f"{owner} does not declare {channel} as its primary channel")

    for profile in profiles:
        profile_id = profile["id"]
        repository = Path(profile["repository"])
        metadata = repository / profile["metadata"]
        live_path = Path(profile["live_profile_path"])
        if not metadata.is_file():
            fail(f"{profile_id} metadata missing: {metadata}")
        if not live_path.is_dir():
            fail(f"{profile_id} live profile missing: {live_path}")

        profile_data = yaml.safe_load(metadata.read_text(encoding="utf-8")) or {}
        if profile_data.get("profile_id") != profile_id:
            fail(f"{profile_id} metadata profile_id mismatch")
        if profile_data.get("channel_ownership", {}).get("primary") != profile["primary_channel"]:
            fail(f"{profile_id} primary channel mismatch")

        for channel in profile.get("disabled_channels") or []:
            if channel == profile["primary_channel"]:
                fail(f"{profile_id} disables its primary channel")
            if channel in channel_owners and channel_owners[channel] == profile_id:
                fail(f"{profile_id} owns and disables {channel}")

        service = profile.get("gateway_service")
        if service and not service_exists(service):
            fail(f"{profile_id} service is not installed: {service}")

    print(
        f"PASS profile registry: {len(profiles)} profiles, "
        f"{len(channel_owners)} channel owners, {len(retired)} retired profiles"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
