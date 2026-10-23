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
