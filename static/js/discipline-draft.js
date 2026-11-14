(() => {
  const root = document.getElementById("discipline-assistant");
  if (!root) return;
  const student = document.getElementById("student-select");
  const facts = document.getElementById("facts-summary");
  const origin = document.getElementById("facts-source-student");
  const status = document.getElementById("discipline-status");
  const reports = document.getElementById("discipline-reports");
  const load = document.getElementById("discipline-load");
  const generate = document.getElementById("discipline-generate");
  const selection = document.getElementById("discipline-selection");
  const preview = document.getElementById("discipline-preview");
  const draft = document.getElementById("discipline-draft");
  let revision = 0;
  let sourceHash = "";
  let draftStudent = "";

  function url(base, id) {
    return new URL(base.replace("/0/", `/${encodeURIComponent(id)}/`), window.location.origin);
  }

  async function jsonResponse(response) {
    if (!(response.headers.get("content-type") || "").includes("application/json")) {
      throw new Error("La sesión no está disponible. Vuelve a entrar en la app.");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se ha podido completar la consulta.");
    return data;
  }

  function checkFacts() {
    if (!facts.value.trim()) origin.value = "";
    facts.setCustomValidity(origin.value && origin.value !== student.value
      ? "El borrador corresponde a otro alumno. Borra el texto anterior o vuelve a seleccionar ese alumno." : "");
  }

  function reset() {
    revision += 1;
    reports.replaceChildren();
    selection.hidden = true;
    preview.hidden = true;
    sourceHash = "";
    draftStudent = "";
    generate.disabled = true;
    document.getElementById("discipline-count").textContent = "0 partes seleccionados";
    load.disabled = !student.value;
    status.textContent = "Sin partes consultados.";
    checkFacts();
  }

  function selectedIds() {
    return [...reports.querySelectorAll("input:checked")].map(input => input.value);
  }

  reports.addEventListener("change", () => {
    revision += 1;
    const count = selectedIds().length;
    generate.disabled = count === 0 || count > 50;
    document.getElementById("discipline-count").textContent = count === 1 ? "1 parte seleccionado" : `${count} partes seleccionados`;
    preview.hidden = true;
  });
  student.addEventListener("change", reset);
  facts.addEventListener("input", checkFacts);

  load.addEventListener("click", async () => {
    reset();
    const current = revision;
    const id = student.value;
    if (!id) return;
    const endpoint = url(root.dataset.reportsUrl, id);
    endpoint.searchParams.set("start", document.getElementById("discipline-start").value);
    endpoint.searchParams.set("end", document.getElementById("discipline-end").value);
    load.disabled = true;
    status.textContent = "Consultando partes…";
    try {
      const data = await jsonResponse(await fetch(endpoint, { credentials: "same-origin" }));
      if (current !== revision || student.value !== id) return;
      sourceHash = data.source_sha256;
      data.reports.forEach(report => {
        const label = document.createElement("label");
        label.className = "discipline-report";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = report.id;
        const content = document.createElement("span");
        const heading = document.createElement("strong");
        heading.textContent = `${report.date.split("-").reverse().join("/")} · ${report.student_name} · ${report.unit}`;
        content.appendChild(heading);
        [report.incident, report.conduct && `Conducta registrada: ${report.conduct}`,
          report.correction && `Corrección registrada: ${report.correction}`,
          `Hoja ${report.source_sheet}, fila ${report.source_row}`].filter(Boolean).forEach(value => {
          const paragraph = document.createElement("span");
          paragraph.textContent = value;
          content.appendChild(paragraph);
        });
        label.append(checkbox, content);
        reports.appendChild(label);
      });
      selection.hidden = data.reports.length === 0;
      const modified = new Date(data.source_modified_at);
      const stamp = Number.isNaN(modified.getTime()) ? "" : ` Excel actualizado: ${modified.toLocaleString("es-ES")}.`;
      status.textContent = `${data.total} partes coincidentes. Curso ${data.school_year}.${stamp}`;
      if (data.total > 200) status.textContent += " Se muestran los últimos 200; acota las fechas para consultar los anteriores.";
      if (data.excluded_unit) status.textContent += ` Hay ${data.excluded_unit} registros con ese nombre en otra unidad que no se han incluido.`;
    } catch (error) {
      if (current === revision) status.textContent = error.message;
    } finally {
      if (current === revision) load.disabled = !student.value;
    }
  });

  generate.addEventListener("click", async () => {
    const current = revision;
    const id = student.value;
    const ids = selectedIds();
    generate.disabled = true;
    status.textContent = "Preparando borrador…";
    try {
      const data = await jsonResponse(await fetch(url(root.dataset.draftUrl, id), {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": root.closest("form").querySelector('[name="csrf_token"]').value },
        body: JSON.stringify({ report_ids: ids, source_sha256: sourceHash }),
      }));
      if (current !== revision || student.value !== id) return;
      draft.value = data.draft;
      draftStudent = id;
      preview.hidden = false;
      status.textContent = `Borrador preparado con ${data.count} ${data.count === 1 ? "parte" : "partes"} para revisión de Jefatura.`;
    } catch (error) {
      if (current === revision) status.textContent = error.message;
    } finally {
      if (current === revision) generate.disabled = selectedIds().length === 0 || selectedIds().length > 50;
    }
  });

  document.getElementById("discipline-apply").addEventListener("click", () => {
    if (draftStudent !== student.value || !draft.value.trim()) return;
    if (origin.value && origin.value !== student.value && facts.value.trim()) {
      status.textContent = "Borra el borrador del alumno anterior antes de añadir otro.";
      return;
    }
    const text = draft.value.trim();
    if (!facts.value.includes(text)) facts.value = [facts.value.trim(), text].filter(Boolean).join("\n\n");
    origin.value = student.value;
    checkFacts();
    facts.focus();
    status.textContent = "Borrador añadido a Hechos. Pendiente de guardar el expediente.";
  });
  reset();
})();
