document.addEventListener("DOMContentLoaded", () => {
  const money = n => Number(n).toLocaleString("en-KE", {minimumFractionDigits: 2, maximumFractionDigits: 2});

  // Success messages fade away
  document.querySelectorAll(".msg.success").forEach(m => setTimeout(() => m.remove(), 6000));

  // Live table filter: <input data-filter="#tableId">
  document.querySelectorAll("[data-filter]").forEach(input => {
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase();
      document.querySelectorAll(input.dataset.filter + " tbody tr").forEach(tr => {
        tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  });

  const customer = document.getElementById("id_customer");

  // Meter reading form: auto-fill previous reading and preview the bill
  const preview = document.getElementById("preview");
  const current = document.getElementById("id_current_reading");
  const previous = document.getElementById("id_previous_reading");
  if (preview && customer && current && previous) {
    let info = null;
    const render = () => {
      if (!info) { preview.textContent = "Select a customer to preview the bill."; return; }
      const units = parseFloat(current.value || 0) - parseFloat(previous.value || 0);
      if (isNaN(units) || units < 0) { preview.innerHTML = '<span class="bad">Current reading cannot be lower than the previous reading.</span>'; return; }
      const energy = units * info.rate, vat = (energy + info.fixed) * info.vat / 100;
      preview.innerHTML = `<b>${info.name}</b> (meter ${info.meter}) &mdash; Units: <b>${units.toFixed(2)}</b> | Energy: ${money(energy)} | Fixed: ${money(info.fixed)} | VAT: ${money(vat)} | <b>Estimated total: KES ${money(energy + info.fixed + vat)}</b>`;
    };
    customer.addEventListener("change", async () => {
      if (!customer.value) { info = null; render(); return; }
      info = await (await fetch(`/api/customers/${customer.value}/info/`)).json();
      previous.value = info.previous;
      previous.readOnly = info.has_previous;
      render();
    });
    current.addEventListener("input", render);
    previous.addEventListener("input", render);
    if (customer.value) customer.dispatchEvent(new Event("change"));
  }

  // Payment form: list only the selected customer's open bills
  const bill = document.getElementById("id_bill");
  if (bill && customer && !preview) {
    const load = async () => {
      const keep = bill.value;
      bill.innerHTML = '<option value="">— Auto-apply to oldest unpaid bill —</option>';
      if (!customer.value) return;
      const bills = await (await fetch(`/api/customers/${customer.value}/open-bills/`)).json();
      bills.forEach(b => bill.add(new Option(b.label, b.id)));
      if (keep) bill.value = keep;
    };
    customer.addEventListener("change", load);
    if (customer.value) load();
  }
});
