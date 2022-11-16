# Watchdogmon

> Auto-generated documentation for [frontend.watchdogmon](blob/master/frontend/watchdogmon.py) module.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Watchdogmon
    - [watchdog_monitor](#watchdog_monitor)
        - [watchdog_monitor().on_event](#watchdog_monitoron_event)
        - [watchdog_monitor().shutdown](#watchdog_monitorshutdown)
        - [watchdog_monitor().startup](#watchdog_monitorstartup)
    - [on_created](#on_created)
    - [on_deleted](#on_deleted)
    - [on_modified](#on_modified)
    - [on_moved](#on_moved)

## watchdog_monitor

[[find in source code]](blob/master/frontend/watchdogmon.py#L36)

```python
class watchdog_monitor():
    def __init__():
```

### watchdog_monitor().on_event

[[find in source code]](blob/master/frontend/watchdogmon.py#L41)

```python
def on_event(event):
```

### watchdog_monitor().shutdown

[[find in source code]](blob/master/frontend/watchdogmon.py#L70)

```python
def shutdown(*args):
```

### watchdog_monitor().startup

[[find in source code]](blob/master/frontend/watchdogmon.py#L44)

```python
def startup(
    monitor_path,
    created=None,
    deleted=None,
    modified=None,
    moved=None,
):
```

## on_created

[[find in source code]](blob/master/frontend/watchdogmon.py#L17)

```python
def on_created(event):
```

## on_deleted

[[find in source code]](blob/master/frontend/watchdogmon.py#L21)

```python
def on_deleted(event):
```

## on_modified

[[find in source code]](blob/master/frontend/watchdogmon.py#L25)

```python
def on_modified(event):
```

## on_moved

[[find in source code]](blob/master/frontend/watchdogmon.py#L30)

```python
def on_moved(event):
```
