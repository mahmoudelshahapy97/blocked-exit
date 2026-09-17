"""Domain services.

Deliberately free of eager submodule imports: ``stream_worker`` imports
``app.services.alerting`` and friends, so re-exporting here would create an
import cycle.
"""
