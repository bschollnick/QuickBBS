import directory_caching

test = r"/Volumes/3TB_Drive/gallery/albums/Hyp-Collective/New/"

cdl = directory_caching.Cache()
cdl.smart_read(test)
cached_files, cached_dirs = cdl.return_sorted(
                    scan_directory=test,
                    reverse=False)

print len(cached_files)
print len(cached_dirs)
