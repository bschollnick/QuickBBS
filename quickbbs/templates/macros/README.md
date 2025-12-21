# QuickBBS Template Macros

This directory contains reusable Jinja2 macros for the QuickBBS template system.

## Available Macro Files

### `htmx.jinja` - HTMX Navigation Macros

Provides macros for creating HTMX-enabled links and buttons with consistent attributes.

**Macros:**
- `show_nav_link(url, text, ...)` - HTMX navigation link
- `show_nav_button(url, icon_name, ...)` - HTMX icon button
- `show_htmx_attrs(target, swap, cache)` - HTMX attributes string

**Example:**
```jinja
{% from 'macros/htmx.jinja' import show_nav_link, show_htmx_attrs %}

{# Simple navigation link #}
{{ show_nav_link("/gallery/photos", "Photos") }}

{# Link with custom CSS class #}
{{ show_nav_link(item.url, item.name, css_class="button is-primary") }}

{# Use attributes on custom element #}
<a href="{{ url }}" {{ show_htmx_attrs()|safe }}>Custom Link</a>
```

### `metadata.jinja` - Item Metadata Display Macros

Provides macros for displaying item metadata with icons (file sizes, dates, counts).

**Macros:**
- `show_icon_text(icon_class, value, condition)` - Icon with text display
- `show_item_metadata(item)` - Complete metadata section for gallery items

**Example:**
```jinja
{% from 'macros/metadata.jinja' import show_icon_text, show_item_metadata %}

{# Display single metadata field #}
{{ show_icon_text('far fa-calendar', '12/05/25 14:30') }}

{# Display complete metadata for gallery item #}
{{ show_item_metadata(item) }}
```

## Usage Guidelines

1. **Import at the top** of your template:
   ```jinja
   {% from 'macros/htmx.jinja' import show_nav_link, show_nav_button %}
   {% from 'macros/metadata.jinja' import show_item_metadata %}
   ```

2. **Use macros** in your template:
   ```jinja
   {{ show_nav_link(item.url, item.name) }}
   {{ show_item_metadata(item) }}
   ```

3. **Only import what you need** to keep templates clean and efficient.

## Benefits

- **DRY Principle**: Single source of truth for common patterns
- **Consistency**: All HTMX links use the same attributes
- **Maintainability**: Update behavior in one place
- **Readability**: Templates show intent, not implementation details

## Testing

To verify macros work correctly, you can test them in the Django shell:

```python
from django.template import Template, Context
from quickbbs.models import FileIndex

template = Template("""
    {% from 'macros/metadata.jinja' import show_item_metadata %}
    {{ show_item_metadata(item) }}
""")

item = FileIndex.objects.first()
html = template.render(Context({'item': item}))
print(html)
```

## See Also

- [jinja2_improvements.md](../../../jinja2_improvements.md) - Full optimization plan
- [Jinja2 Documentation](https://jinja.palletsprojects.com/en/3.1.x/templates/#macros)
