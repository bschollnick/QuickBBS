# filetypes — Entity-Relationship Diagram

**Companion to:** [`filetypes_design.md`](filetypes_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`filetypes` owns exactly one model. This diagram exists mainly to show that it's the
*referenced* side of two relationships owned by [`quickbbs`](quickbbs_erd.md), not a
participant with outgoing foreign keys of its own. Verified against
`filetypes/models.py`.

---

## Diagram

```mermaid
erDiagram
    filetypes ||--o{ DirectoryIndex : "referenced by DirectoryIndex.filetype (CASCADE)"
    filetypes ||--o{ FileIndex : "referenced by FileIndex.filetype (CASCADE)"

    filetypes {
        string fileext PK "e.g. '.jpg', '.dir', '.none' — always lowercase"
        bool generic "served with a stock icon"
        string icon_filename
        string color
        int filetype "legacy numeric type ID"
        string mimetype
        bool is_image
        bool is_archive
        bool is_pdf
        bool is_movie
        bool is_audio
        bool is_dir
        bool is_text
        bool is_html
        bool is_markdown
        bool is_link
        bytes thumbnail "generic icon image bytes"
    }

    DirectoryIndex {
        string fqpndirectory PK
        string filetype_id FK "always '.dir'"
    }

    FileIndex {
        int id PK
        string filetype_id FK
    }
```

---

## Reading the diagram

**One row per registered extension, keyed by the extension itself.** `fileext` is the
primary key — there's no separate surrogate ID a lookup has to go through.
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex) and
[`FileIndex`](quickbbs_app_design.md#43-fileindexpy--fileindex) both hold a `filetype`
foreign key `to_field="fileext"` rather than the usual implicit PK, so the FK column
*is* the extension string.

**No foreign keys point out of this table.** `filetypes` is a small, mostly-static
lookup table (seeded by `manage.py refresh_filetypes`) loaded once into a module-level
dict at startup and served from memory thereafter
([`filetypes_design.md` §1.2](filetypes_design.md#12-the-registry-is-read-constantly-and-changes-almost-never))
— every lookup elsewhere in the codebase reads that dict, never the database directly.
The `CASCADE` on both incoming foreign keys means deleting a `filetypes` row would
delete every `DirectoryIndex`/`FileIndex` row that references it, which is why
extensions are retired by unregistering them, not by deleting rows out from under
live data.
