"""Semantic URL - A Parsing & Manipulation library for creating & using Semantic URLs
"""


try:
    from setuptools import setup, find_packages
except:
    from disutils.core import setup, find_packages

__title__ = 'semantic_url'
__author__ = 'Benjamin Schollnick'
__license__ = 'MIT'
__copyright__ = 'Copyright 2015 Benjamin Schollnick'
__module_name__ = __title__
__version__ = '1.0.10'
__author__ = 'Benjamin Schollnick'
__author_email__ = 'Benjamin@schollnick.net'
__license__ = 'MIT'
__copyright__ = 'Copyright 2015 Benjamin Schollnick'
__github_url__ = 'https://github.com/bschollnick/Semantic_URL/tree/master'

__pypi_keywords__ ='semantic', 'URL'

dependencies = []

doclines = __doc__.split("\n")

__packages__ = ['semantic_url']

__package_data__ = {}

setup(
    name=__title__,
    version=__version__,
    description=doclines[0],
    author=__author__,
    author_email=__author_email__,
    maintainer=__author__,
    maintainer_email=__author_email__,
    url=__github_url__,
    download_url=__github_url__,
    py_modules=[__module_name__],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows :: Windows 7',
        'Operating System :: Microsoft :: Windows :: Windows XP',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2'
    ],
    include_package_data = True,
    package_data = __package_data__,
    packages = __packages__,
    requires = dependencies,
    long_description = "\n".join(doclines[2:]),
    keywords = __pypi_keywords__

)
