#!/usr/bin/env python3
"""
Instagram post downloader with offset and limit support.

Downloads posts from a specified Instagram profile using instaloader.
"""

from __future__ import annotations

import argparse
from itertools import islice

import instaloader


def main() -> None:
    """Download Instagram posts with configurable offset and limit."""
    parser = argparse.ArgumentParser(description="Download Instagram posts with offset and limit")
    parser.add_argument("profile", help="Target Instagram profile username")
    parser.add_argument(
        "--offset",
        type=int,
        default=100,
        help="Number of posts to skip (default: 100)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of posts to download (default: 10)",
    )
    parser.add_argument(
        "--username",
        help="Username for session authentication (optional, improves rate limits)",
    )

    args = parser.parse_args()

    loader = instaloader.Instaloader()

    # Load session from file if username is provided
    if args.username:
        session_file = "/Users/benjamin/IL_sessionfile.txt"
        try:
            loader.load_session_from_file(args.username, session_file)
            print(f"✓ Session loaded from {session_file}")
        except FileNotFoundError:
            print(f"✗ Session file not found: {session_file}")
            print("  Continuing without authentication...")
        except Exception as e:  # TODO: narrow to instaloader.exceptions types once instaloader exception hierarchy is documented
            print(f"✗ Could not load session: {e}")
            print("  Continuing without authentication...")

    target_profile = args.profile
    offset = args.offset
    limit = args.limit

    print(f"\nFetching posts from profile: {target_profile}")
    profile = instaloader.Profile.from_username(loader.context, target_profile)

    # get_posts() returns posts in reverse chronological order (newest to oldest)
    posts = profile.get_posts()

    print(f"Downloading {limit} posts starting from offset {offset} (newest to oldest)\n")

    # Use islice to skip the first 'offset' posts and take the next 'limit' posts
    downloaded_count = 0
    skipped_count = 0
    processed = 0

    for post in islice(posts, offset, offset + limit):
        processed += 1
        # download_post returns True if something was downloaded, False if already exists
        was_downloaded = loader.download_post(post, target=profile.username)

        if was_downloaded:
            downloaded_count += 1
            print(f"  [{processed}/{limit}] ✓ Downloaded: {post.shortcode}")
        else:
            skipped_count += 1
            print(f"  [{processed}/{limit}] ⊘ Skipped (exists): {post.shortcode}")

    print(f"\n✓ Finished processing {processed} posts.")
    print(f"  Downloaded: {downloaded_count}")
    print(f"  Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
