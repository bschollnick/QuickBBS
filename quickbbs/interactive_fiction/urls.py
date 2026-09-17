"""URL routes for the interactive_fiction app.

Included under the "if/" prefix from the central quickbbs/quickbbs/urls.py.
"""

from __future__ import annotations

from django.urls import URLPattern, path

from interactive_fiction import panel_views, save_views, story_views, views

urlpatterns: list[URLPattern] = [
    path("", views.library, name="if_library"),
    path("upload/", story_views.upload, name="if_upload"),
    path("preferences/", views.preferences, name="if_preferences"),
    path("<slug:slug>/", views.play, name="if_play"),
    path("<slug:slug>/new-game/", views.character_creation, name="if_character_creation"),
    path("<slug:slug>/new-game/submit/", views.character_creation_submit, name="if_character_creation_submit"),
    path("<slug:slug>/play/", views.play_submit, name="if_play_submit"),
    path("<slug:slug>/undo/", views.play_undo, name="if_play_undo"),
    path("<slug:slug>/restart/", views.play_restart, name="if_play_restart"),
    path("<slug:slug>/panel/<str:tab_id>/", panel_views.play_panel_tab, name="if_play_panel_tab"),
    path("<slug:slug>/panel-action/<str:action_id>/<str:target_id>/", panel_views.play_panel_action, name="if_play_panel_action"),
    path("<slug:slug>/panel-command/<str:command_id>/<str:target_id>/", panel_views.play_panel_command, name="if_play_panel_command"),
    path("<slug:slug>/edit/", story_views.edit, name="if_edit"),
    path("<slug:slug>/saves/", save_views.saves, name="if_saves"),
    path("<slug:slug>/saves/import/", save_views.saves_import, name="if_saves_import"),
    path("<slug:slug>/saves/<int:slot>/save/", save_views.saves_save, name="if_saves_save"),
    path("<slug:slug>/saves/<int:slot>/load/", save_views.saves_load, name="if_saves_load"),
    path("<slug:slug>/saves/<int:slot>/export/", save_views.saves_export, name="if_saves_export"),
    path("<slug:slug>/saves/<int:slot>/delete/", save_views.saves_delete, name="if_saves_delete"),
    # The quicksave has its own routes rather than reusing <int:slot>:
    # Django's int converter matches digits only, so its negative slot
    # number would 404 before reaching the view.
    path("<slug:slug>/saves/quicksave/", save_views.saves_quicksave, name="if_saves_quicksave"),
    path("<slug:slug>/saves/quickload/", save_views.saves_quickload, name="if_saves_quickload"),
    # `path:` (not `str:`) because tag_name is a path-qualified media tag —
    # "guide/Male/guide12m.jpg", "shared/church8.jpg" — and Django's
    # `str:` converter matches any character EXCEPT "/". Under `str:` every
    # such tag failed to reverse (NoReverseMatch) and no story image was
    # ever served; only a hypothetical slash-free tag would have worked.
    path("<slug:slug>/image/<path:tag_name>/", story_views.story_image, name="if_story_image"),
    path("<slug:slug>/video/<path:tag_name>/", story_views.story_video, name="if_story_video"),
    path("<slug:slug>/cover/", story_views.story_cover, name="if_story_cover"),
]
