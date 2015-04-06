"""
Quick and dirty common library for cheetah templating.

Eventually needs to be eliminated, and rolled into the main package.
"""
import Cheetah
import Cheetah.Template
import os


def setup_template(filename=None, template_directory=None):
    """
    Give a filename to load, and directory name, 
    and it returns the Template object
    """
    if filename != None and template_directory != None:
        template_data = open(
            os.sep.join([template_directory, filename]), 'r').readlines()
        template_data = "\n".join(template_data)
        return Cheetah.Template.Template(template_data)


def render_template(template):
    """
        Returns the template as a string
    """
    return str(template)
