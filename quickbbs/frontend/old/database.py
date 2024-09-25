"""
Database Specific Functions
"""
# from typing import Iterator  # , Optional, Union, TypeVar, Generic

# from quickbbs.models import IndexData

# DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]

SORT_MATRIX = {
    0: ["-filetype__is_dir", "-filetype__is_link", "name_sort", "lastmod"],
    1: ["-filetype__is_dir", "-filetype__is_link", "lastmod", "name_sort"],
    2: ["-filetype__is_dir", "-filetype__is_link", "name_sort"],
}

# def get_db_files(sorder, fpath) -> Iterator[IndexData]:
#     """
#     Fetch the data from the database, and then order by the current users sort
#     """
#     index = (
#         IndexData.objects.prefetech_related("filetype")
#         .exclude(ignore=True)
#         .exclude(delete_pending=True)
#         .filter(fqpndirectory=fpath.lower().strip())
#         .order_by(*SORT_MATRIX[sorder])
#     )
#     return index

# def get_xth_image(database, positional=0, filters=None) -> Iterator[IndexData]:
#     """
#     Return the xth image from the database, using the passed filters

#     Parameters
#     ----------
#     database : object - The django database handle

#     positional : int - 0 is first, if positional is greater than the # of
#                  records, then it is reset to the count of records

#     filters : dictionary of filters

#     Returns
#     -------

#         boolean::
#             If successful the database record in question,
#                     otherwise returns None

#     Examples
#     --------
#     return_img_attach("test.png", img_data)
#     """
#     if filters is None:
#         filters = {}

#     data = (
#         database.objects.prefetech_related("filetype")
#         .filter(**filters)
#         .exclude(filetype__is_image=False)
#         .exclude(ignore=True)
#         .exclude(delete_pending=True)
#     )
#     try:
#         # exact match
#         return data[positional]
#     except IndexError:  # No matching position was found
#         # it has to be either too high (greater than length), or less than 0.
#         count = data.count()
#         if positional > count:  # The requested index is too high
#             return data[count]
#         # else, return None, because positional has to be 0 or less.
#     return None
