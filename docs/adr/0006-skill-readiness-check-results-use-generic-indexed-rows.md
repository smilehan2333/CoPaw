# Skill readiness check results use generic indexed rows

Skill readiness stores each per-user check outcome as a generic row keyed by run id, user id, check name, and status, rather than querying only inside a JSON array or adding one database column per check type. This keeps new readiness checks extensible through the check-name registry while making administrator queries such as "failed users for cron_auth_valid" use ordinary indexes instead of JSON scans.
