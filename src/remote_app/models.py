"""Django models for swf-remote.

Alarm state lives in swf-remote's existing Postgres DB, NOT in a separate
store. The standalone swf-alarms engine writes via raw psycopg (no Django
import), the dashboard reads via the ORM below. Table names are pinned via
`db_table` so both sides can reference the same schema without guessing
Django's app-prefixed default names.
"""
from django.db import models


class AlarmRun(models.Model):
    """One engine tick. Per-check detail rows hang off AlarmCheckRun."""
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    checks_run = models.IntegerField(default=0)
    alarms_seen = models.IntegerField(default=0)
    notifications_sent = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    error_details = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'alarm_run'
        indexes = [models.Index(fields=['-started_at'])]


class AlarmCheckRun(models.Model):
    """One check's execution inside an AlarmRun.

    Written even when the check is disabled or fails — lets the dashboard
    show 'this check is configured, here's when it last ran and why it
    didn't produce alarms'.
    """
    run = models.ForeignKey(AlarmRun, on_delete=models.CASCADE,
                            related_name='check_runs')
    check_name = models.CharField(max_length=200)
    kind = models.CharField(max_length=100)
    enabled = models.BooleanField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    alarms_seen = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    params_snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'alarm_check_run'
        indexes = [models.Index(fields=['check_name', '-started_at'])]


class AlarmFiring(models.Model):
    """One alarm, keyed by (check_name, dedupe_key).

    The engine upserts on that key: first occurrence inserts, subsequent
    occurrences update last_fired_at / last_seen_at / cooldown_until and
    re-open a cleared firing if the condition returns.
    """
    STATE_CHOICES = [('active', 'active'), ('cleared', 'cleared')]

    check_name = models.CharField(max_length=200)
    dedupe_key = models.CharField(max_length=400)
    first_fired_at = models.DateTimeField()
    last_fired_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    cooldown_until = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=16, default='active',
                             choices=STATE_CHOICES)
    cleared_at = models.DateTimeField(null=True, blank=True)
    severity = models.CharField(max_length=32)
    subject = models.CharField(max_length=500)
    body = models.TextField()
    recipients = models.TextField()  # comma-separated, sufficient for MVP
    data = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'alarm_firing'
        constraints = [
            models.UniqueConstraint(fields=['check_name', 'dedupe_key'],
                                    name='uniq_alarm_firing_key'),
        ]
        indexes = [
            models.Index(fields=['state', '-last_fired_at']),
            models.Index(fields=['check_name', '-last_fired_at']),
        ]


class AlarmFiringEvent(models.Model):
    """Append-only log of state transitions on an AlarmFiring.

    Actions: fired, re-confirmed, re-fired, notified, notify-failed,
    notify-skipped-cooldown, notify-skipped-dry-run, cleared.
    """
    firing = models.ForeignKey(AlarmFiring, on_delete=models.CASCADE,
                               related_name='events')
    ts = models.DateTimeField()
    action = models.CharField(max_length=64)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'alarm_firing_event'
        indexes = [models.Index(fields=['firing', '-ts'])]
