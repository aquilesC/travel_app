"""Domain rules for trips, shared by web views, the API and WhatsApp ingest (v4 #20).

Every function takes the acting user first and enforces trip membership. Errors
are raised as the classes in `errors`; they subclass Django's own exceptions, so
a web view that doesn't catch them still answers 404/403/400 as before.
"""
