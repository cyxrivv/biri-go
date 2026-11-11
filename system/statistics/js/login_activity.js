(() => {
    "use strict";

    const table = document.getElementById("login-activity-table");
    if (!table) return;

    const body = table.querySelector("tbody");
    const message = document.getElementById("login-activity-message");
    const refresh = document.getElementById("login-activity-refresh");

    function cell(row, value) {
        const td = document.createElement("td");
        td.textContent = value == null || value === "" ? "—" : String(value);
        row.appendChild(td);
    }

    function render(items, canViewAll) {
        const head = table.querySelector("thead");
        const columns = canViewAll
            ? ["Account ID", "Role", "Activity", "Status", "IP Address", "Device / Browser", "Date & Time"]
            : ["Activity", "Status", "IP Address", "Device / Browser", "Date & Time"];
        const headerRow = document.createElement("tr");
        columns.forEach((label) => {
            const th = document.createElement("th");
            th.scope = "col";
            th.textContent = label;
            headerRow.appendChild(th);
        });
        head.replaceChildren(headerRow);
        body.replaceChildren();

        if (!items.length) {
            const row = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = columns.length;
            td.textContent = "No login activity has been recorded yet.";
            row.appendChild(td);
            body.appendChild(row);
            return;
        }

        items.forEach((item) => {
            const row = document.createElement("tr");
            if (canViewAll) {
                cell(row, item.account_code || (item.account_id ? "Account #" + item.account_id : "Unknown account"));
                cell(row, item.account_role);
            }
            cell(row, item.event_type);
            cell(row, item.status);
            cell(row, item.ip_address);
            cell(row, item.user_agent);
            const date = item.created_at ? new Date(item.created_at) : null;
            cell(row, date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : item.created_at);
            body.appendChild(row);
        });
    }

    async function load() {
        if (refresh) refresh.disabled = true;
        if (message) message.textContent = "Loading login activity…";
        try {
            const response = await fetch("/api/login-activity?limit=100", {
                method: "GET",
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
                cache: "no-store"
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || "Could not load login activity.");
            render(Array.isArray(data.items) ? data.items : [], data.can_view_all === true);
            if (message) {
                message.textContent = data.can_view_all
                    ? "Showing the latest " + data.items.length + " login events across all accounts."
                    : "Showing the latest " + data.items.length + " login events for your account.";
            }
        } catch (error) {
            if (message) message.textContent = error.message || "Could not load login activity.";
            body.replaceChildren();
        } finally {
            if (refresh) refresh.disabled = false;
        }
    }

    if (refresh) refresh.addEventListener("click", load);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", load, { once: true });
    } else {
        load();
    }
})();