from timeit import timeit

from frontend.thumbnail_engine import FastImageProcessor, create_thumbnails_from_path

pillow = """
from frontend.thumbnail_engine import FastImageProcessor, create_thumbnails_from_path
filename = "image.png"
IMAGE_SIZES = {"large": (800, 600), "medium": (400, 300), "small": (200, 150)}

processor = FastImageProcessor(IMAGE_SIZES, backend="pillow")
thumbnails_pillow = create_thumbnails_from_path(
        filename, IMAGE_SIZES, format="JPEG", backend="pillow"
    )
"""

# apple = """
# from frontend.thumbnail_engine import FastImageProcessor, create_thumbnails_from_path
# filename = "image.png"
# IMAGE_SIZES = {"large": (800, 600), "medium": (400, 300), "small": (200, 150)}

# processor = FastImageProcessor(IMAGE_SIZES, backend="pillow")
# thumbnails_ci = create_thumbnails_from_path(
#             filename, IMAGE_SIZES, format="JPEG", backend="coreimage"
#         )
# """

print(
    "pillow : ",
    timeit(
        stmt=pillow,
        number=1000,
        globals={
            "FastImageProcessor": FastImageProcessor,
            "create_thumbnails_from_path": create_thumbnails_from_path,
        },
    ),
)
print("*" * 20)
# print("apple : ", timeit(stmt=apple, number=1000, globals={"FastImageProcessor": FastImageProcessor, "create_thumbnails_from_path": create_thumbnails_from_path}))
