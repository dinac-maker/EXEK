// Filtros de las tablas: un buscador (texto, sin importar tildes ni mayúsculas) y listas
// por columna. Cada fila lleva data-<columna> con sus valores separados por "|".
(function () {
  const norm = s => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  document.querySelectorAll(".filtros").forEach(barra => {
    const tabla = document.getElementById(barra.dataset.tabla);
    if (!tabla) return;
    const filas = [...tabla.querySelectorAll("tbody tr")];
    const contador = barra.querySelector(".contador");
    const clave = "filtros:" + location.pathname + ":" + barra.dataset.tabla;
    const controles = [...barra.querySelectorAll("input, select")];
    // Si la página llega con una búsqueda (por ejemplo, desde el buscador del encabezado),
    // manda esa búsqueda y no se recuperan los filtros guardados.
    if (!("sinMemoria" in barra.dataset)) {
      try { const g = JSON.parse(sessionStorage.getItem(clave) || "{}"); controles.forEach(c => { if (g[c.name] !== undefined) c.value = g[c.name]; }); } catch (e) {}
    }
    function aplicar() {
      const q = norm(barra.querySelector("input[type=search]")?.value);
      const listas = [...barra.querySelectorAll("select[data-col]")].filter(s => s.value);
      let n = 0;
      filas.forEach(f => {
        const ve = (!q || norm(f.textContent).includes(q)) &&
          listas.every(s => (f.dataset[s.dataset.col] || "").split("|").includes(s.value));
        f.hidden = !ve; if (ve) n++;
      });
      if (contador) contador.textContent = n + " de " + filas.length;
      try { sessionStorage.setItem(clave, JSON.stringify(Object.fromEntries(controles.map(c => [c.name, c.value])))); } catch (e) {}
    }
    controles.forEach(c => c.addEventListener("input", aplicar));
    barra.querySelector(".limpiar")?.addEventListener("click", () => { controles.forEach(c => c.value = ""); aplicar(); });
    aplicar();
  });
})();

// "Buscar en": al cambiar entre el cliente y todos los clientes se lleva el texto del filtro.
document.querySelectorAll("a[data-lleva-busqueda]").forEach(a => a.addEventListener("click", e => {
  const texto = document.querySelector(".filtros input[type=search]")?.value.trim();
  if (!texto) return;
  e.preventDefault();
  const url = new URL(a.href, location.href);
  url.searchParams.set("q", texto);
  location.href = url.toString();
}));

// Confirmación dentro de la página (no con la ventana del navegador, que algunos
// navegadores bloquean y entonces el botón parece no hacer nada). Sirve para formularios
// con data-confirmar y para botones con data-confirmar (por ejemplo "Eliminar").
document.addEventListener("submit", e => {
  const form = e.target;
  const origen = e.submitter && e.submitter.dataset.confirmar ? e.submitter : form;
  const pregunta = origen.dataset.confirmar;
  if (!pregunta || form.dataset.confirmado === "si") return;
  e.preventDefault();
  if (form.nextElementSibling && form.nextElementSibling.classList.contains("confirmar")) return;
  const caja = document.createElement("div");
  caja.className = "confirmar";
  caja.setAttribute("role", "alertdialog");
  const texto = document.createElement("span");
  texto.textContent = pregunta;
  const si = document.createElement("button");
  si.type = "button"; si.className = "primario chico"; si.textContent = origen.dataset.confirmarBoton || "Sí, continuar";
  const no = document.createElement("button");
  no.type = "button"; no.className = "chico"; no.textContent = "Cancelar";
  caja.append(texto, si, no);
  form.after(caja);
  si.focus();
  const boton = e.submitter;
  si.addEventListener("click", () => {
    form.dataset.confirmado = "si";
    si.disabled = true; si.textContent = "Enviando…";
    form.requestSubmit(boton || undefined);
  });
  no.addEventListener("click", () => caja.remove());
});
