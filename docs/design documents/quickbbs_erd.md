# quickbbs — Entity-Relationship Diagram

**Companion to:** [`quickbbs_app_design.md`](quickbbs_app_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

A visual map of every model the `quickbbs` app owns, and how they relate. Field-level
detail (types, indexes, why a field is or isn't indexed) lives in
[`quickbbs_app_design.md` §4](quickbbs_app_design.md#4-component-reference) — this
diagram exists to answer "what points at what," not to restate every column. Verified
directly against `quickbbs/quickbbs/{models,directoryindex,fileindex}.py`.

---

## Diagram

```mermaid
erDiagram
    DirectoryIndex ||--o{ DirectoryIndex : "parent_directory (self, SET_NULL)"
    DirectoryIndex ||--o{ FileIndex : "home_directory (SET_NULL)"
    DirectoryIndex ||--o{ FileIndex : "virtual_directory (SET_NULL)"
    DirectoryIndex }o--|| filetypes : "filetype (CASCADE, always '.dir')"
    DirectoryIndex }o--o| FileIndex : "thumbnail (SET_NULL, cover image)"

    FileIndex }o--|| filetypes : "filetype (CASCADE)"
    FileIndex }o--o| ThumbnailFiles : "new_ftnail (SET_NULL)"
    FileIndex ||--o| Owners : "ownership (OneToOne, CASCADE)"

    Owners ||--|| AuthUser : "ownerdetails (OneToOne, CASCADE)"

    DirectoryIndex {
        string fqpndirectory PK "unique, always lowercase"
        string dir_fqpn_sha256 PK "unique, URL identifier"
        int parent_directory_id FK "self, nullable"
        float lastscan
        float lastmod
        bool cache_invalidated "True = needs rescan"
        float cache_lastscan
        bool delete_pending
        string filetype_id FK "always '.dir'"
        int thumbnail_id FK "-> FileIndex, cover image"
    }

    FileIndex {
        int id PK
        string file_sha256 "content hash, NOT unique (dedup key)"
        string unique_sha256 PK "content+path hash, unique, URL identifier"
        float lastscan
        float lastmod
        string name
        int size
        int home_directory_id FK "-> DirectoryIndex, nullable"
        int virtual_directory_id FK "-> DirectoryIndex, nullable, .link targets"
        bool delete_pending
        bool cover_image
        string filetype_id FK
        int new_ftnail_id FK "-> ThumbnailFiles, nullable"
        int ownership_id FK "-> Owners, OneToOne, nullable"
    }

    filetypes {
        string fileext PK "e.g. '.jpg', always lowercase"
        bool is_image
        bool is_movie
        bool is_pdf
        bool is_dir
        bool is_link
        bytes thumbnail "generic icon bytes"
    }

    ThumbnailFiles {
        int id PK
        string sha256_hash "unique, = FileIndex.file_sha256"
        bytes small_thumb "NULL or non-empty, never b''"
        bytes medium_thumb
        bytes large_thumb
    }

    Owners {
        int id PK
        uuid uuid
        int ownerdetails_id FK "-> auth.User, OneToOne, CASCADE"
    }

    Favorites {
        int id PK
        uuid uuid
    }

    AuthUser {
        int id PK
        string username
    }
```

---

## Reading the diagram

**Two self-contained trees meet at one seam.**
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex) forms
a tree via its own `parent_directory` self-reference;
[`FileIndex`](quickbbs_app_design.md#43-fileindexpy--fileindex) rows hang off that
tree via `home_directory`. The seam between them is `DirectoryIndex.thumbnail`, which
points *forward* into `FileIndex` — a directory's cover image is one of its own files
(or a descendant's, resolved by `get_cover_image()`), not a separate concept.

**Content identity is a hash, not a foreign key.** `FileIndex.file_sha256` is
deliberately *not* unique — every duplicate copy of a file across the collection
shares it ([§1.3](quickbbs_app_design.md#13-identical-files-are-the-same-file) of
`quickbbs_app_design.md`). [`ThumbnailFiles`](thumbnails_erd.md)`.sha256_hash` is the
join key that lets every one of those duplicate `FileIndex` rows share a single
thumbnail row through `FileIndex.new_ftnail`, without a join table.
`FileIndex.unique_sha256`, by contrast, is unique per row — it's the content hash plus
the file's path, so it can serve as a stable, regenerable public identifier
([§4.3](quickbbs_app_design.md#43-fileindexpy--fileindex)) without needing a UUID.

**`virtual_directory` is for `.link` files, not the file's real location.** A `.link`
file's `home_directory` is where the link file itself sits; `virtual_directory` is set
when the link resolves to a target directory inside the gallery, letting the file act
as if it lives there too without a second `FileIndex` row.

**`Owners` and `Favorites` are present but not load-bearing.** `Owners` exists only as
`FileIndex.ownership`'s target — "start of a permissions-based model" per its own
docstring, with no other code path populating or reading it today. `Favorites` has no
foreign key into anything; it's registered in `admin.py` and otherwise unused. Both are
included here for completeness, not because the rest of the app depends on them.

**[`filetypes`](filetypes_erd.md) is the one table every other model points at, never
the reverse.** Both `DirectoryIndex.filetype` and `FileIndex.filetype` are `CASCADE`
foreign keys into it, but `filetypes` itself has no foreign keys out — it's a small,
read-heavy lookup table loaded once into memory
([`filetypes_design.md` §1.2](filetypes_design.md#12-the-registry-is-read-constantly-and-changes-almost-never)),
not a participant in the directory/file tree.
