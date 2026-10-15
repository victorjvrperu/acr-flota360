// ACR Flota360 - Dashboard Frontend Logic

document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  cargarDashboard();
});

// Navegación por pestañas
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach(item => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      const target = item.getAttribute("data-section");
      
      navItems.forEach(n => n.classList.remove("active"));
      item.classList.add("active");

      document.querySelectorAll(".section-view").forEach(sec => sec.classList.remove("active"));
      const activeSection = document.getElementById(`section-${target}`);
      if (activeSection) activeSection.classList.add("active");

      const titles = {
        dashboard: "Dashboard General 360°",
        vehiculos: "Control de Flota Vehicular",
        conductores: "Gestión de Conductores",
        mantenimientos: "Mantenimientos Preventivos y Correctivos",
        combustible: "Control y Rendimiento de Combustible",
        viajes: "Despacho y Registro de Viajes"
      };
      document.getElementById("topbar-title-text").textContent = titles[target] || "ACR Flota360";

      // Cargar datos de la sección seleccionada
      if (target === "dashboard") cargarDashboard();
      if (target === "vehiculos") cargarVehiculos();
      if (target === "conductores") cargarConductores();
      if (target === "mantenimientos") cargarMantenimientos();
      if (target === "combustible") cargarCombustible();
      if (target === "viajes") cargarViajes();
    });
  });
}

// Cargar métricas del Dashboard
async function cargarDashboard() {
  try {
    const res = await fetch("/api/v1/dashboard/stats");
    if (!res.ok) throw new Error("Error al obtener estadísticas");
    const data = await res.json();

    document.getElementById("stat-total-vehiculos").textContent = data.total_vehiculos;
    document.getElementById("stat-operativos").textContent = data.vehiculos_operativos;
    document.getElementById("stat-en-ruta").textContent = data.vehiculos_en_ruta;
    document.getElementById("stat-taller").textContent = data.vehiculos_en_mantenimiento;
    document.getElementById("stat-viajes-curso").textContent = data.viajes_en_curso;
    document.getElementById("stat-gasto-combustible").textContent = `S/ ${data.gasto_combustible_mes.toLocaleString('es-PE', { minimumFractionDigits: 2 })}`;

    // Render alertas
    const alertList = document.getElementById("alertas-container");
    alertList.innerHTML = "";
    if (data.alertas && data.alertas.length > 0) {
      data.alertas.forEach(a => {
        const item = document.createElement("div");
        item.className = `alert-item alert-${a.nivel}`;
        item.innerHTML = `
          <div>
            <strong>${a.titulo}</strong>
            <p style="margin-top: 2px; font-size: 0.8rem; opacity: 0.9;">${a.mensaje}</p>
          </div>
          <span class="badge badge-${a.nivel === 'urgente' ? 'fuera_servicio' : 'mantenimiento'}">${a.nivel.toUpperCase()}</span>
        `;
        alertList.appendChild(item);
      });
    } else {
      alertList.innerHTML = `<div style="color: var(--text-muted); font-size: 0.85rem; padding: 8px;">✅ Todas las unidades, documentos y revisiones se encuentran al día.</div>`;
    }

    // Cargar tabla rápida de vehículos en dashboard
    cargarVehiculosPreview();
  } catch (err) {
    console.error(err);
  }
}

// Cargar lista de vehículos
async function cargarVehiculos() {
  try {
    const res = await fetch("/api/v1/vehiculos");
    const data = await res.json();
    const tbody = document.getElementById("tabla-vehiculos-body");
    tbody.innerHTML = "";

    data.forEach(v => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong style="color: var(--accent-blue);">${v.placa}</strong></td>
        <td>${v.marca} ${v.modelo}</td>
        <td>${v.tipo.toUpperCase()} (${v.anio})</td>
        <td>${v.odometro_actual.toLocaleString()} km</td>
        <td><span class="badge badge-${v.estado}">${v.estado.replace('_', ' ')}</span></td>
        <td>${v.soat_vencimiento || '-'}</td>
        <td>${v.revision_tecnica_vencimiento || '-'}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="eliminarVehiculo(${v.id})">Eliminar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

async function cargarVehiculosPreview() {
  try {
    const res = await fetch("/api/v1/vehiculos");
    const data = await res.json();
    const tbody = document.getElementById("tabla-preview-vehiculos");
    tbody.innerHTML = "";

    data.slice(0, 5).forEach(v => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${v.placa}</strong></td>
        <td>${v.marca} ${v.modelo}</td>
        <td>${v.odometro_actual.toLocaleString()} km</td>
        <td><span class="badge badge-${v.estado}">${v.estado.replace('_', ' ')}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// Cargar Conductores
async function cargarConductores() {
  try {
    const res = await fetch("/api/v1/conductores");
    const data = await res.json();
    const tbody = document.getElementById("tabla-conductores-body");
    tbody.innerHTML = "";

    data.forEach(c => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${c.nombres} ${c.apellidos}</strong></td>
        <td>${c.dni}</td>
        <td>${c.licencia_numero} (${c.licencia_categoria})</td>
        <td>${c.licencia_vencimiento}</td>
        <td>${c.telefono || '-'}</td>
        <td><span class="badge badge-${c.estado}">${c.estado}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="eliminarConductor(${c.id})">Eliminar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// Cargar Mantenimientos
async function cargarMantenimientos() {
  try {
    const res = await fetch("/api/v1/mantenimientos");
    const data = await res.json();
    const tbody = document.getElementById("tabla-mantenimientos-body");
    tbody.innerHTML = "";

    data.forEach(m => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${m.id}</td>
        <td>Vehículo #${m.vehiculo_id}</td>
        <td><span class="badge badge-${m.tipo === 'correctivo' ? 'fuera_servicio' : 'mantenimiento'}">${m.tipo}</span></td>
        <td>${m.descripcion}</td>
        <td>${m.taller || 'Taller Interno'}</td>
        <td>S/ ${m.costo.toFixed(2)}</td>
        <td>${m.fecha_programada}</td>
        <td><span class="badge badge-${m.estado}">${m.estado}</span></td>
        <td>
          ${m.estado !== 'completado' ? `<button class="btn btn-primary btn-sm" onclick="completarMantenimiento(${m.id})">Completar</button>` : 'Listo'}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// Cargar Combustible
async function cargarCombustible() {
  try {
    const res = await fetch("/api/v1/combustible");
    const data = await res.json();
    const tbody = document.getElementById("tabla-combustible-body");
    tbody.innerHTML = "";

    data.forEach(c => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${c.fecha}</td>
        <td>Vehículo #${c.vehiculo_id}</td>
        <td>${c.cantidad} ${c.unidad_medida}</td>
        <td>S/ ${c.precio_unitario.toFixed(2)}</td>
        <td><strong>S/ ${c.costo_total.toFixed(2)}</strong></td>
        <td>${c.odometro.toLocaleString()} km</td>
        <td>${c.rendimiento_km_unidad ? `${c.rendimiento_km_unidad} km/gal` : '-'}</td>
        <td>${c.estacion || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// Cargar Viajes
async function cargarViajes() {
  try {
    const res = await fetch("/api/v1/viajes");
    const data = await res.json();
    const tbody = document.getElementById("tabla-viajes-body");
    tbody.innerHTML = "";

    data.forEach(v => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${v.codigo}</strong></td>
        <td>Vehículo #${v.vehiculo_id}</td>
        <td>Conductor #${v.conductor_id}</td>
        <td>${v.origen} ➔ ${v.destino}</td>
        <td>${new Date(v.fecha_salida).toLocaleString('es-PE')}</td>
        <td>${v.distancia_recorrida ? `${v.distancia_recorrida} km` : '-'}</td>
        <td><span class="badge badge-${v.estado}">${v.estado}</span></td>
        <td>
          ${v.estado === 'en_curso' ? `<button class="btn btn-primary btn-sm" onclick="finalizarViajePrompt(${v.id})">Finalizar</button>` : 'Cerrado'}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// Modales
function abrirModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("active");
}

function cerrarModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("active");
}

// Handlers de formulación
async function crearVehiculoSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const payload = {
    placa: form.placa.value,
    marca: form.marca.value,
    modelo: form.modelo.value,
    anio: parseInt(form.anio.value),
    tipo: form.tipo.value,
    odometro_actual: parseFloat(form.odometro.value || 0),
    combustible_tipo: form.combustible_tipo.value,
    soat_vencimiento: form.soat.value || null,
    revision_tecnica_vencimiento: form.revision.value || null
  };

  try {
    const res = await fetch("/api/v1/vehiculos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      alert("Error: " + (err.detail || "No se pudo registrar"));
      return;
    }
    cerrarModal("modal-vehiculo");
    form.reset();
    cargarVehiculos();
    cargarDashboard();
  } catch (err) {
    alert("Error de conexión");
  }
}

async function eliminarVehiculo(id) {
  if (!confirm("¿Seguro de eliminar este vehículo?")) return;
  await fetch(`/api/v1/vehiculos/${id}`, { method: "DELETE" });
  cargarVehiculos();
  cargarDashboard();
}

async function eliminarConductor(id) {
  if (!confirm("¿Seguro de eliminar este conductor?")) return;
  await fetch(`/api/v1/conductores/${id}`, { method: "DELETE" });
  cargarConductores();
}

async function completarMantenimiento(id) {
  await fetch(`/api/v1/mantenimientos/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ estado: "completado" })
  });
  cargarMantenimientos();
  cargarDashboard();
}

async function finalizarViajePrompt(id) {
  const odo = prompt("Ingrese el odómetro de llegada (km):");
  if (!odo) return;
  await fetch(`/api/v1/viajes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      estado: "finalizado",
      odometro_llegada: parseFloat(odo)
    })
  });
  cargarViajes();
  cargarDashboard();
}
