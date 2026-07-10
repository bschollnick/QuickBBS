## Links & Aliases

QuickBBS can display "shortcut" entries in a gallery that point at another directory in the gallery tree.  Two file types are supported:

* **`.link` files** — A simple QuickBBS-native shortcut file.
* **`.alias` files** — Standard macOS Finder aliases (macOS only).  Create one in the Finder (File → Make Alias, or ⌘L) and drop it into a gallery directory.  
    * While aliases normally do not need a file extension, to be recognized by QuickBBS, the alias file **MUST** have an .alias file extension.  e.g. `Link_to_other_directory.alias`.

When a link or alias resolves successfully, it appears in the gallery as a virtual directory: it gets a thumbnail, and clicking it navigates to the target directory.

---

## How Alias Resolution Works (v4.00+)

Alias resolution was re-engineered in v4.00 to be more robust, particularly for aliases whose targets live on a *different* volume than the gallery (for example, a "masters" drive whose content was copied into the albums tree).

When QuickBBS encounters an `.alias` file, resolution happens in two stages:

### Stage 1: Resolve the alias itself

The macOS Foundation framework resolves the alias bookmark to its raw target path.

**Important:** Resolution deliberately **never mounts a volume**.  If the alias points at a volume that is not currently mounted, the alias cannot be resolved — this is by design, to prevent gallery browsing from triggering network mounts or disk spin-ups.  Mount the volume yourself if you need those aliases to work.

### Stage 2: Translate the target to a gallery directory

The resolved target path is matched to a directory in the gallery database, in this order:

1. **Direct match** — If the target is already inside the albums tree, it is looked up directly.
2. **`ALIAS_MAPPING` override** — An explicit translation table in `quickbbs_settings.py` (see below).  The longest matching path prefix wins.  If a mapping matches but the translated directory does not exist in the gallery, the link is reported as a *missing gallery copy* — it will not fall through to guessing.
3. **Suffix matching** — The target's trailing path components are matched against existing gallery directories.  At least **two** trailing components must match; a bare directory-name match is never trusted, because a single name can easily match the wrong directory.

At each step, a second candidate with spaces replaced by underscores is also tried (e.g. `asfa 14.17` also matches a gallery copy named `asfa_14.17`), to accommodate copy tools that rename directories.

If no match is found, the link is treated as broken and logged.

---

## The `ALIAS_MAPPING` Setting

If your aliases point at an external/masters volume whose content is mirrored inside the albums tree, add an explicit translation in `quickbbs_settings.py`:

```python
ALIAS_MAPPING = {
    # "alias target prefix"        :  "equivalent gallery path"
    r"/volumes/masters/masters":      r"/volumes/.../albums/collection_name",
}
```

* Keys and values are path *prefixes*; anything after the matched prefix is carried over to the gallery path.
* Prefixes only match at path-component boundaries (`/volumes/x/videos_old` will not match a `/volumes/x/videos` key).
* When multiple keys match, the longest one wins, so overlapping entries are safe.

Use `ALIAS_MAPPING` whenever suffix matching alone is ambiguous or the directory layout differs between the source volume and the gallery.

---

## Repairing Link Targets

If aliases were indexed before an `ALIAS_MAPPING` entry existed, or the gallery tree has been reorganized, stored link targets can go stale.  The `repair_link_targets` management command re-resolves every link file in the database:

```bash
cd quickbbs

# Preview: report what would change without saving anything
python manage.py repair_link_targets --dry-run

# Repair: re-point mismatched targets
python manage.py repair_link_targets
```

The command:

* Clears the alias-resolution cache, so mapping changes take effect immediately.
* Re-points any link whose stored target no longer matches the current resolution.
* Reports links whose targets **cannot** be resolved (broken links), so you can fix or remove them.
* Reports any directory records that fall outside the albums tree.

Run it with `--dry-run` first after changing `ALIAS_MAPPING` or moving directories around, then run it for real once the report looks correct.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Alias shows no thumbnail / doesn't navigate | Target volume not mounted | Mount the volume (QuickBBS will never mount it for you) |
| Alias resolves to the wrong directory | Ambiguous suffix match | Add an explicit `ALIAS_MAPPING` entry, then run `repair_link_targets` |
| Aliases stopped working after reorganizing directories | Stale stored targets | `python manage.py repair_link_targets` |
| Alias target reported as "missing gallery copy" | Mapping matched, but the directory isn't in the gallery | Copy the content into the albums tree, or correct the mapping |
