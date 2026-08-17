"""URL routes for the interactive_fiction app.

Included under the "if/" prefix from the central quickbbs/quickbbs/urls.py.
"""

from __future__ import annotations

from django.urls import URLPattern, path

from interactive_fiction import save_views, story_views, views

urlpatterns: list[URLPattern] = [
    path("", views.library, name="if_library"),
    path("upload/", story_views.upload, name="if_upload"),
    path("preferences/", views.preferences, name="if_preferences"),
    path("<slug:slug>/", views.play, name="if_play"),
    path("<slug:slug>/play/", views.play_submit, name="if_play_submit"),
    path("<slug:slug>/undo/", views.play_undo, name="if_play_undo"),
    path("<slug:slug>/restart/", views.play_restart, name="if_play_restart"),
    path("<slug:slug>/edit/", story_views.edit, name="if_edit"),
    path("<slug:slug>/saves/", save_views.saves, name="if_saves"),
    path("<slug:slug>/saves/import/", save_views.saves_import, name="if_saves_import"),
    path("<slug:slug>/saves/<int:slot>/save/", save_views.saves_save, name="if_saves_save"),
    path("<slug:slug>/saves/<int:slot>/load/", save_views.saves_load, name="if_saves_load"),
    path("<slug:slug>/saves/<int:slot>/export/", save_views.saves_export, name="if_saves_export"),
    path("<slug:slug>/image/<str:tag_name>/", story_views.story_image, name="if_story_image"),
    path("<slug:slug>/cover/", story_views.story_cover, name="if_story_cover"),
]
