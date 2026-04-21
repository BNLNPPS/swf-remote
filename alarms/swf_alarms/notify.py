"""Notification channels. Email (SES) first; Mattermost etc. can slot in here.

Channels take an Alarm + EmailConfig (+ future per-channel config) and return
True on successful send, False on any failure. Failures must be logged but
must not raise — a stuck channel should not block other channels or future
alarms.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import boto3
from botocore.exceptions import BotoCoreError, ClientError


log = logging.getLogger(__name__)


@dataclass
class Alarm:
    check_name: str
    dedupe_key: str
    severity: str
    subject: str
    body: str
    recipients: list[str]
    data: dict


def send_email_ses(alarm: Alarm, *, region: str, from_addr: str) -> bool:
    ses = boto3.client("ses", region_name=region)
    try:
        resp = ses.send_email(
            Source=from_addr,
            Destination={"ToAddresses": alarm.recipients},
            Message={
                "Subject": {"Data": alarm.subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": alarm.body, "Charset": "UTF-8"}},
            },
        )
        log.info("SES send OK: MessageId=%s to=%s", resp.get("MessageId"),
                 ",".join(alarm.recipients))
        return True
    except (BotoCoreError, ClientError) as e:
        log.error("SES send FAILED for %s to %s: %s",
                  alarm.dedupe_key, alarm.recipients, e)
        return False
