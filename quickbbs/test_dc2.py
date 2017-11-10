import directory_caching

if __name__ == "__main__":
    cdl = directory_caching.Cache()
    cdl.smart_read("/Volumes/3TB_Drive/gallery/albums/hentai idea")
    cached_files, cached_dirs = cdl.return_sorted(
                    scan_directory="/Volumes/3TB_Drive/gallery/albums/hentai idea",
                    sort_by=1, reverse=False)
    print len(cached_files)
    print len(cached_dirs)
