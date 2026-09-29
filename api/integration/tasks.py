"""Scheduled ecosystem jobs (Procrastinate). The sync is skipped quietly when the HRMS is not configured."""

import logging

from django.conf import settings
from procrastinate.contrib.django import app

from integration.client import IntegrationError
from integration.hrms import sync_org, sync_staff

log = logging.getLogger(__name__)


@app.periodic(cron="30 1 * * *")  # 01:30 every night
@app.task(name="integration.sync_hrms", queue="integration")
def sync_hrms(timestamp: int | None = None) -> dict:
    if not settings.HRMS_API_URL or not settings.HRMS_API_KEY:
        log.info("integration.sync_hrms skipped: HRMS not configured")
        return {"skipped": True}
    try:
        result = {"org": sync_org(), "staff": sync_staff()}
    except IntegrationError:
        log.exception("integration.sync_hrms failed")
        return {"failed": True}
    log.info("integration.sync_hrms %s", result)
    return result
