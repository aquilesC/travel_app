"""Form rendering for the whole site (v4 #29): fields use templates/django/forms/field.html,
and text-like inputs get the shared `field-input` Tailwind class."""

from django import forms
from django.forms.renderers import TemplatesSetting

TEXT_LIKE = (forms.TextInput, forms.EmailInput, forms.PasswordInput, forms.NumberInput, forms.URLInput,
             forms.DateInput, forms.DateTimeInput, forms.TimeInput, forms.Textarea, forms.Select)


class SiteFormRenderer(TemplatesSetting):
    form_template_name = "django/forms/div.html"
    field_template_name = "django/forms/field.html"

    def render(self, template_name, context, request=None):
        widget = context.get("widget")
        if widget is not None and template_name.startswith("django/forms/widgets/"):
            attrs = widget.setdefault("attrs", {})
            if widget.get("type") not in ("checkbox", "radio", "file", "hidden") and \
                    not template_name.endswith(("checkbox_select.html", "radio.html", "clearable_file_input.html")):
                attrs["class"] = f"{attrs.get('class', '')} field-input".strip()
        return super().render(template_name, context, request)
