# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

from novacore_ph.statutory.reports import contribution_report


def execute(filters=None):
	return contribution_report(filters, "SSS", "sss_number", "SSS Number", include_ec=True)
