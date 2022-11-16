# Config

> Auto-generated documentation for [frontend.config](blob/master/frontend/config.py) module.

:Module: Config
:Date: 2015-05-1
:Platforms: Mac, Windows, Unix (Tested under Mac OS X)
:Version: 1
:Authors:
    - Benjamin Schollnick

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Config
    - [load_data](#load_data)

:Description:
    This module will read in the configuration ini.

**Modules Used (Batteries Included)**:

* os
* os.path
* stat
* string
* time

:Concept:

While not ideal, INI based configuration files, are easy to debug,
and more important, easy to update.

The module is passed the location of the configuration files,
and will read in the necessary ini files (settings.ini by default).
The different segments of the ini file will be stored in a seperate
dictionary for ease of use..

code

```python
load_data(<fqfn>)
print config.configdata["USER"]
print config.configdata["EMAIL"]
```

## load_data

[[find in source code]](blob/master/frontend/config.py#L57)

```python
def load_data(filename=None, ini_group=''):
```

:Description:
    Load data from the ini file

#### Arguments

- `filename` - (default value = None) To override the filename
    pass a string containing the new filename.

- `oname` - The option name to read from the ini

#### Returns

loaded dictionary

code

```python
USER = load_user_data(settings_file)
EMAIL = load_email_data(settings_file)
```
