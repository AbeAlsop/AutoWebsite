(() => {
    const activeStatuses = new Set(["queued", "running"]);
    const terminalStatuses = new Set(["awaiting_review", "failed", "cancelled", "approved"]);
    const jobs = [...document.querySelectorAll("[data-job-id]")];

    if (!jobs.some((job) => activeStatuses.has(job.dataset.jobStatus))) {
        return;
    }

    const poll = async () => {
        let shouldRefresh = false;

        for (const job of jobs) {
            if (!activeStatuses.has(job.dataset.jobStatus)) {
                continue;
            }

            try {
                const response = await fetch(`/jobs/${encodeURIComponent(job.dataset.jobId)}`, {
                    headers: { "Accept": "application/json" },
                    cache: "no-store",
                });
                if (!response.ok) {
                    continue;
                }
                const current = await response.json();
                if (terminalStatuses.has(current.status)) {
                    shouldRefresh = true;
                    break;
                }
            } catch (_error) {
                // A temporary network failure is harmless; the next poll retries.
            }
        }

        if (shouldRefresh) {
            window.location.reload();
            return;
        }
        window.setTimeout(poll, 1500);
    };

    window.setTimeout(poll, 1500);
})();
