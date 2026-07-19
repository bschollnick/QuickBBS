"""
Tests for physical-path → gallery-directory alias resolution.

Tests cover:
- DirectoryIndex.find_by_physical_path() — suffix matching, ALIAS_MAPPING
  overrides, albums-root handling, ambiguity and basename-only rejection
- FileIndex.process_link_file() — .alias branch via find_by_physical_path()
- FileIndex.virtual_directory_needs_repair()
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from quickbbs.common import get_dir_sha, normalize_fqpn
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.fileindex import FileIndex
from quickbbs.tests.test_directoryindex import DirectoryIndexTestBase, _make_dirs


class AliasResolutionTestBase(DirectoryIndexTestBase):
    """Adds a fake masters volume and gallery layout to the temp-dir fixture."""

    def setUp(self) -> None:
        super().setUp()
        _make_dirs(
            self.temp_dir,
            # gallery tree (indexed below)
            "albums/hentai_idea/test/videos/diana",
            "albums/hentai_idea/test/people/d/diana",
            "albums/hentai_idea/test/people/h/hally",
            "albums/hentai_idea/hyp/games/asfa_14.17/images/people/alison",
            "albums/site_a/videos/dup",
            "albums/site_b/videos/dup",
            # fake masters volume (physical alias targets — never indexed)
            "masters/videos/diana",
            "masters/games/asfa 14.17/images/people/alison",
        )
        for rel in (
            "albums/hentai_idea/test/videos/diana",
            "albums/hentai_idea/test/people/d/diana",
            "albums/hentai_idea/test/people/h/hally",
            "albums/hentai_idea/hyp/games/asfa_14.17/images/people/alison",
            "albums/site_a/videos/dup",
            "albums/site_b/videos/dup",
        ):
            success, record = self._add(rel)
            assert success, f"fixture add_directory failed for {rel}"
            self.dirs[rel] = record

    def _physical(self, rel_path: str) -> str:
        """Return an absolute physical (non-gallery) path under temp_dir."""
        return os.path.join(self.temp_dir, rel_path)


# ===========================================================================
# find_by_physical_path — suffix matching
# ===========================================================================


@pytest.mark.django_db
class TestFindByPhysicalPathSuffix(AliasResolutionTestBase):
    """Suffix-matching behaviour with no ALIAS_MAPPING entries."""

    def setUp(self) -> None:
        super().setUp()
        self._mapping_override = override_settings(ALIAS_MAPPING={})
        self._mapping_override.enable()

    def tearDown(self) -> None:
        self._mapping_override.disable()
        super().tearDown()

    def test_unique_two_component_suffix_matches(self) -> None:
        """videos/diana identifies the gallery videos copy, not the people dir."""
        result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/diana"))
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/test/videos/diana"].pk

    def test_basename_only_match_is_rejected(self) -> None:
        """A target whose only match is the bare folder name resolves to None."""
        # people/h/hally exists, but nothing ends with videos/hally —
        # matching on "hally" alone would self-link the wrong directory.
        result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/hally"))
        assert result is None

    def test_ambiguous_suffix_returns_none(self) -> None:
        """Two gallery dirs sharing the deepest matching suffix → None."""
        result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/dup"))
        assert result is None

    def test_no_match_returns_none(self) -> None:
        """A target with no gallery equivalent resolves to None."""
        result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/nonexistent"))
        assert result is None

    def test_space_to_underscore_variant_matches(self) -> None:
        """masters 'asfa 14.17' matches the gallery's underscored copy."""
        result = DirectoryIndex.find_by_physical_path(self._physical("masters/games/asfa 14.17/images/people/alison"))
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/hyp/games/asfa_14.17/images/people/alison"].pk

    def test_path_already_under_albums_root(self) -> None:
        """A target already inside the albums tree is looked up directly."""
        gallery_path = self._physical("albums/hentai_idea/test/videos/diana")
        result = DirectoryIndex.find_by_physical_path(gallery_path)
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/test/videos/diana"].pk


# ===========================================================================
# find_by_physical_path — ALIAS_MAPPING overrides
# ===========================================================================


@pytest.mark.django_db
class TestFindByPhysicalPathMapping(AliasResolutionTestBase):
    """ALIAS_MAPPING override behaviour."""

    def _mapping(self, source_rel: str, target_rel: str) -> dict[str, str]:
        return {self._physical(source_rel): self._physical(target_rel)}

    def test_mapping_override_wins(self) -> None:
        """A matching prefix translates directly to the mapped gallery path."""
        mapping = self._mapping("masters/videos", "albums/hentai_idea/test/videos")
        with override_settings(ALIAS_MAPPING=mapping):
            result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/diana"))
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/test/videos/diana"].pk

    def test_mapping_is_boundary_anchored(self) -> None:
        """A 'videos' key must not match a 'videos_old' path component."""
        _make_dirs(self.temp_dir, "masters/videos_old/diana")
        mapping = self._mapping("masters/videos", "albums/hentai_idea/test/videos")
        with override_settings(ALIAS_MAPPING=mapping):
            result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos_old/diana"))
        # Falls through to suffix matching: videos_old/diana has no gallery
        # equivalent, and bare "diana" is ambiguous/basename-only → None.
        assert result is None

    def test_mapping_with_missing_gallery_copy_is_authoritative(self) -> None:
        """A prefix hit whose translated path is missing → None, no fall-through."""
        _make_dirs(self.temp_dir, "masters/videos/dup")
        mapping = self._mapping("masters/videos", "albums/hentai_idea/test/videos")
        with override_settings(ALIAS_MAPPING=mapping):
            # test/videos/dup does not exist; suffix matching WOULD find
            # site_a/site_b videos/dup (ambiguous) — but the override must
            # not fall through to it.
            result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/dup"))
        assert result is None

    def test_mapping_creates_unscanned_on_disk_directory(self) -> None:
        """A translated path on disk but not yet indexed is added."""
        _make_dirs(self.temp_dir, "masters/videos/newdir", "albums/hentai_idea/test/videos/newdir")
        mapping = self._mapping("masters/videos", "albums/hentai_idea/test/videos")
        with override_settings(ALIAS_MAPPING=mapping):
            result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/newdir"))
        assert result is not None
        assert result.fqpndirectory == normalize_fqpn(self._physical("albums/hentai_idea/test/videos/newdir"))

    def test_longest_prefix_wins(self) -> None:
        """Overlapping keys resolve via the most specific prefix."""
        mapping = {
            self._physical("masters"): self._physical("albums/site_a"),
            self._physical("masters/videos"): self._physical("albums/hentai_idea/test/videos"),
        }
        with override_settings(ALIAS_MAPPING=mapping):
            result = DirectoryIndex.find_by_physical_path(self._physical("masters/videos/diana"))
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/test/videos/diana"].pk


# ===========================================================================
# process_link_file — .alias branch
# ===========================================================================


@pytest.mark.django_db
class TestProcessLinkFileAlias(AliasResolutionTestBase):
    """FileIndex.process_link_file() routing for .alias files."""

    def test_alias_resolves_through_find_by_physical_path(self) -> None:
        """A resolvable alias returns the translated gallery DirectoryIndex."""
        alias_filetype = SimpleNamespace(fileext=".alias")
        with override_settings(ALIAS_MAPPING={}):
            with patch.object(FileIndex, "resolve_macos_alias", return_value=self._physical("masters/videos/diana")):
                result = FileIndex.process_link_file(Path("/fake/diana-videos.alias"), alias_filetype, "diana-videos.alias")
        assert result is not None
        assert result.pk == self.dirs["albums/hentai_idea/test/videos/diana"].pk

    def test_unresolvable_alias_returns_none(self) -> None:
        """An alias whose target has no gallery copy returns None."""
        alias_filetype = SimpleNamespace(fileext=".alias")
        with override_settings(ALIAS_MAPPING={}):
            with patch.object(FileIndex, "resolve_macos_alias", return_value=self._physical("masters/videos/nonexistent")):
                result = FileIndex.process_link_file(Path("/fake/x.alias"), alias_filetype, "x.alias")
        assert result is None

    def test_dangling_bookmark_returns_none(self) -> None:
        """A bookmark that raises ValueError (deleted master) returns None."""
        alias_filetype = SimpleNamespace(fileext=".alias")
        with patch.object(FileIndex, "resolve_macos_alias", side_effect=ValueError("Error creating bookmark data")):
            result = FileIndex.process_link_file(Path("/fake/dead.alias"), alias_filetype, "dead.alias")
        assert result is None


# ===========================================================================
# virtual_directory_needs_repair
# ===========================================================================


@pytest.mark.django_db
class TestVirtualDirectoryNeedsRepair(AliasResolutionTestBase):
    """FileIndex.virtual_directory_needs_repair() states."""

    def test_missingvirtual_directory_needs_repair(self) -> None:
        """No virtual_directory set → repair needed."""
        link = FileIndex()
        assert link.virtual_directory_needs_repair() is True

    def test_in_tree_virtual_directory_is_healthy(self) -> None:
        """A virtual_directory under the albums root → no repair."""
        link = FileIndex(virtual_directory=self.dirs["albums/hentai_idea/test/videos/diana"])
        assert link.virtual_directory_needs_repair() is False

    def test_out_of_treevirtual_directory_needs_repair(self) -> None:
        """A virtual_directory outside the albums root → repair needed."""
        # Simulate a legacy out-of-tree row by direct ORM create —
        # add_directory now rejects paths outside the albums root.
        stale_path = normalize_fqpn(self._physical("masters/videos/stale"))
        stale_dir = DirectoryIndex.objects.create(
            fqpndirectory=stale_path,
            dir_fqpn_sha256=get_dir_sha(stale_path),
            lastscan=0,
            lastmod=0,
        )
        link = FileIndex(virtual_directory=stale_dir)
        assert link.virtual_directory_needs_repair() is True

    def test_add_directory_rejects_out_of_tree_path(self) -> None:
        """add_directory refuses to create rows outside the albums root."""
        _make_dirs(self.temp_dir, "masters/videos/rejected")
        target = self._physical("masters/videos/rejected") + os.sep
        success, record = DirectoryIndex.add_directory(target)
        assert success is False
        assert record is None
        assert not DirectoryIndex.objects.filter(fqpndirectory=normalize_fqpn(target)).exists()
