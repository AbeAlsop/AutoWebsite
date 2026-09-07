(() => {
    const uploadForm = document.querySelector("#upload-form");
    const uploadResult = document.querySelector("#upload-result");
    if (uploadForm && uploadResult) {
        uploadForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            uploadResult.classList.remove("error");
            uploadResult.textContent = "Checking upload…";
            try {
                const response = await fetch(uploadForm.action, {
                    method: "POST",
                    body: new FormData(uploadForm),
                    headers: { Accept: "application/json" },
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || "Upload was rejected.");
                }
                uploadResult.textContent = `${result.filename} passed quarantine checks.`;
                uploadForm.reset();
                window.setTimeout(() => window.location.reload(), 250);
            } catch (error) {
                uploadResult.classList.add("error");
                uploadResult.textContent = error instanceof Error ? error.message : "Upload failed.";
            }
        });
    }

    const activeStatuses = new Set(["queued", "running"]);
    const terminalStatuses = new Set(["awaiting_review", "failed", "cancelled", "approved"]);
    const jobs = [...document.querySelectorAll("[data-job-id]")];

    for (const form of document.querySelectorAll(".delete-upload-form")) {
        form.addEventListener("submit", (event) => {
            if (form.dataset.inUse === "true") {
                event.preventDefault();
                window.alert(form.dataset.warning || "This upload is in use and cannot be deleted.");
                return;
            }
            if (!window.confirm(form.dataset.warning || "Delete this upload?")) {
                event.preventDefault();
            }
        });
    }

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
