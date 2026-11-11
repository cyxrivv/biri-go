(() => {
    "use strict";

    const table = document.getElementById("login-activity-table");
    if (!table) return;

    const body = table.querySelector("tbody");
    const message = document.getElementById("login-activity-message");
    const refresh = document.getElementById("login-activity-refresh");

    const responsiveStyle = document.createElement("style");
    responsiveStyle.textContent = `
        .login-activity-panel { display: block; width: 100%; max-width: 100%; min-width: 0; margin-top: 1.25rem; }
        .login-activity-wrap { display: block; width: 100%; max-width: 100%; min-width: 0; overflow-x: auto; }
        #login-activity-table { width: 100%; min-width: 1050px; border-collapse: collapse; table-layout: fixed; }
        #login-activity-table th, #login-activity-table td {
            padding: 12px 14px;
            vertical-align: top;
            text-align: left;
        }
        #login-activity-table th { white-space: nowrap; }
        #login-activity-table td { white-space: normal; overflow-wrap: anywhere; }
        #login-activity-table th:nth-child(1) { width: 12%; }
        #login-activity-table th:nth-child(2) { width: 8%; }
        #login-activity-table th:nth-child(3) { width: 10%; }
        #login-activity-table th:nth-child(4) { width: 10%; }
        #login-activity-table th:nth-child(5) { width: 13%; }
        #login-activity-table th:nth-child(6) { width: 25%; }
        #login-activity-table th:nth-child(7) { width: 22%; }
        @media (max-width: 640px) {
            .login-activity-panel { margin-top: 1rem; }
            .login-activity-wrap { overflow: visible; }
            #login-activity-table, #login-activity-table tbody { display: block; width: 100%; }
            #login-activity-table thead {
                position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
                overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
            }
            #login-activity-table tbody { display: grid; gap: 10px; }
            #login-activity-table tbody tr {
                display: block; padding: 6px 12px; border: 1px solid #dce3e8;
                border-radius: 10px; background: #fff;
            }
            #login-activity-table tbody td {
                display: grid; grid-template-columns: minmax(105px, 38%) minmax(0, 1fr);
                gap: 10px; padding: 9px 0; border: 0; border-bottom: 1px solid #edf0f2;
                text-align: left; overflow-wrap: anywhere;
            }
            #login-activity-table tbody td:last-child { border-bottom: 0; }
            #login-activity-table tbody td::before {
                content: attr(data-label); color: #64748b; font-weight: 600;
            }
            #login-activity-table tbody td[colspan] { display: block; border: 0; }
            #login-activity-table tbody td[colspan]::before { content: none; }
        }
    `;
    document.head.appendChild(responsiveStyle);
    const tableWrap = table.closest(".table-container, .table-wrap");
    if (tableWrap) tableWrap.classList.add("login-activity-wrap");

    function cell(row, value, label) {
        const td = document.createElement("td");
        td.textContent = value == null || value === "" ? "—" : String(value);
        td.dataset.label = label;
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
                cell(row, item.account_code || (item.account_id ? "Account #" + item.account_id : "Unknown account"), "Account ID");
                cell(row, item.account_role, "Role");
            }
            cell(row, item.event_type, "Activity");
            cell(row, item.status, "Status");
            cell(row, item.ip_address, "IP Address");
            cell(row, item.user_agent, "Device / Browser");
            const date = item.created_at ? new Date(item.created_at) : null;
            cell(row, date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : item.created_at, "Date & Time");
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