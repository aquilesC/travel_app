import markdown as md
import nh3
from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

register = template.Library()


def render_markdown(text):
    html = md.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    # nh3's default allowlist drops <script>, event handlers and javascript: URLs.
    return nh3.clean(html, link_rel="noopener noreferrer nofollow")


@register.filter(name="markdown")
def markdown_filter(text):
    return mark_safe(render_markdown(text))


@register.simple_tag(takes_context=True)
def media_url(context, media, variant):
    """Owner URL normally; token URL on the public share page."""
    token = context.get("share_token")
    if token:
        return reverse("share_media", args=[token, media.pk, variant])
    return reverse("serve_media", args=[media.pk, variant])
