/**
 * HeavyTrack Enterprise - Motor Offline-First (IndexedDB + Cola de Sincronización)
 */

const DB_NAME = 'heavytrack_offline_db';
const DB_VERSION = 2; // v2: agrega store fotos_pendientes_ia

class HeavyTrackDB {
  constructor() {
    this.db = null;
    this._initPromise = null;
    this.isOnline = navigator.onLine;
    this.isSyncing = false;
    this.ultimoErrorSync = null;
    this.ultimoSyncExitoso = null;
    // Callbacks registrados por la UI para recibir resultados IA al reconectar
    this._onIAResultadoCallbacks = {};
  }

  async init() {
    if (this._initPromise) return this._initPromise;

    this._initPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains('turnos')) {
          db.createObjectStore('turnos', { keyPath: 'uuid_local' });
        }
        if (!db.objectStoreNames.contains('combustibles')) {
          db.createObjectStore('combustibles', { keyPath: 'uuid_local' });
        }
        if (!db.objectStoreNames.contains('incidentes')) {
          db.createObjectStore('incidentes', { keyPath: 'uuid_local' });
        }
        if (!db.objectStoreNames.contains('catalogos')) {
          db.createObjectStore('catalogos', { keyPath: 'tipo' });
        }
        // v2: Cola de fotos de tablero pendientes de análisis IA
        if (!db.objectStoreNames.contains('fotos_pendientes_ia')) {
          db.createObjectStore('fotos_pendientes_ia', { keyPath: 'uuid_local' });
        }
      };

      request.onsuccess = (e) => {
        this.db = e.target.result;
        resolve(this.db);
      };

      request.onerror = (e) => {
        console.error('[IndexedDB] Error al inicializar DB:', e.target.error);
        resolve(null);
      };
    });

    return this._initPromise;
  }

  async asegurarDB() {
    if (!this.db) {
      await this.init();
    }
    return this.db;
  }

  /**
   * Registra un callback que será invocado cuando se procese una foto
   * pendiente IA y vuelva un resultado.
   */
  onIAResultado(tipo, callback) {
    this._onIAResultadoCallbacks[tipo] = callback;
  }

  /**
   * Guarda una foto de tablero en IndexedDB para ser procesada por Gemini
   * cuando se recupere la conexión.
   * Evita acumulación masiva reemplazando fotos previas del mismo tipo.
   */
  async encolarFotoIA(params) {
    try {
      await this.asegurarDB();
      // Eliminar fotos previas del mismo tipo para no acumular fotos desactualizadas
      const anteriores = await this.obtenerTodos('fotos_pendientes_ia');
      for (const item of anteriores) {
        if (item.tipo === params.tipo) {
          await this.eliminarItem('fotos_pendientes_ia', item.uuid_local);
        }
      }

      const item = {
        uuid_local: this.generarUUID(),
        _timestamp_local: new Date().toISOString(),
        tipo: params.tipo,
        imagen_base64: params.imagen_base64,
        lectura_ingresada: params.lectura_ingresada ?? null,
        tipo_control: params.tipo_control || 'HOROMETRO',
        equipo_codigo: params.equipo_codigo || 'EQ-MAQ',
        intentos: 0
      };
      await this.guardarItem('fotos_pendientes_ia', item);
      console.log(`[IA-Queue] Foto de tablero (${item.tipo}) encolada. UUID: ${item.uuid_local}`);
      return item;
    } catch (e) {
      console.warn('[IA-Queue] No se pudo encolar foto IA:', e);
      return null;
    }
  }

  /**
   * Limpia fotos de IA pendientes ya sea porque el turno ya se envió
   * o porque el operador completó el paso.
   */
  async limpiarFotosIAPendientes() {
    try {
      await this.asegurarDB();
      const items = await this.obtenerTodos('fotos_pendientes_ia');
      for (const item of items) {
        await this.eliminarItem('fotos_pendientes_ia', item.uuid_local);
      }
      console.log(`[IA-Queue] Cola de fotos IA limpiada (${items.length} eliminadas)`);
    } catch (e) {
      console.warn('[IA-Queue] Error al limpiar fotos IA:', e);
    }
  }

  /**
   * Purgado explícito de toda la cola de fotos IA (invocable desde el modal de sync)
   */
  async purgarFotosPendientesIA() {
    try {
      await this.asegurarDB();
      const items = await this.obtenerTodos('fotos_pendientes_ia');
      for (const item of items) {
        await this.eliminarItem('fotos_pendientes_ia', item.uuid_local);
      }
      console.log(`[IA-Queue] Purgadas todas las fotos IA acumuladas (${items.length}).`);
      return items.length;
    } catch (e) {
      console.warn('[IA-Queue] Error al purgar fotos IA:', e);
      return 0;
    }
  }

  /**
   * Auto-limpieza de fotos zombies acumuladas: conserva máximo las 2 más recientes
   * y descarta fotos de más de 30 minutos de antigüedad.
   */
  async autoLimpiarFotosObsoletas() {
    try {
      await this.asegurarDB();
      const items = await this.obtenerTodos('fotos_pendientes_ia');
      if (items && items.length > 0) {
        const ahora = Date.now();
        // Ordenar por fecha descendente (más recientes primero)
        items.sort((a, b) => new Date(b._timestamp_local || 0) - new Date(a._timestamp_local || 0));

        let purgadas = 0;
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          const edadMs = ahora - new Date(item._timestamp_local || 0).getTime();
          // Descartar si excede el límite de 2 fotos o tiene más de 30 min o falló 2+ veces
          if (i >= 2 || edadMs > 1800000 || (item.intentos || 0) >= 2) {
            await this.eliminarItem('fotos_pendientes_ia', item.uuid_local);
            purgadas++;
          }
        }
        if (purgadas > 0) {
          console.log(`[IA-Queue] Auto-limpieza ejecutada: ${purgadas} fotos obsoletas purgadas.`);
        }
      }
    } catch (e) {
      console.warn('[IA-Queue] Error en autoLimpiarFotosObsoletas:', e);
    }
  }

  /**
   * Procesa fotos pendientes con Gemini usando timeout no bloqueante.
   */
  async procesarFotosPendientesIA() {
    if (!navigator.onLine) return { procesadas: 0, motivo: 'offline' };

    await this.autoLimpiarFotosObsoletas();

    const pendientes = await this.obtenerTodos('fotos_pendientes_ia');
    if (pendientes.length === 0) return { procesadas: 0 };

    console.log(`[IA-Queue] Procesando ${pendientes.length} foto(s) pendiente(s) con Gemini...`);
    let procesadas = 0;

    for (const foto of pendientes) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        const resp = await fetch('/api/v1/heavy/ia/analizar-tablero', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            imagen_base64: foto.imagen_base64,
            lectura_ingresada: foto.lectura_ingresada,
            tipo_control: foto.tipo_control,
            equipo_codigo: foto.equipo_codigo,
          }),
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (!resp.ok) {
          // Descartar para no bloquear indefinidamente la cola
          await this.eliminarItem('fotos_pendientes_ia', foto.uuid_local);
          continue;
        }

        const resultado = await resp.json();
        resultado._uuid_foto = foto.uuid_local;
        resultado._tipo = foto.tipo;
        resultado._procesado_offline = true;

        console.log(`[IA-Queue] ✅ Foto (${foto.tipo}) procesada:`, resultado);

        const cb = this._onIAResultadoCallbacks[foto.tipo];
        if (typeof cb === 'function') {
          try { cb(resultado); } catch (e) { console.warn('[IA-Queue] Error en callback UI:', e); }
        }

        window.dispatchEvent(new CustomEvent('ia-resultado-offline', {
          detail: resultado
        }));

        await this.eliminarItem('fotos_pendientes_ia', foto.uuid_local);
        procesadas++;

      } catch (err) {
        console.warn(`[IA-Queue] Error procesando foto ${foto.uuid_local}:`, err.message || err);
        // Si falló por red o timeout, descartar la foto para desatascar la cola
        await this.eliminarItem('fotos_pendientes_ia', foto.uuid_local);
        break; // Detener bucle para no demorar el hilo
      }
    }

    console.log(`[IA-Queue] ${procesadas}/${pendientes.length} fotos procesadas.`);
    return { procesadas, total: pendientes.length };
  }

  async contarFotosPendientesIA() {
    const items = await this.obtenerTodos('fotos_pendientes_ia');
    return items.length;
  }

  // Generador universal de UUID local para idempotencia
  generarUUID() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return 'uuid-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9);
  }

  // Operaciones genéricas de almacenamiento con protección DB
  async guardarItem(storeName, data) {
    await this.asegurarDB();
    if (!data.uuid_local) data.uuid_local = this.generarUUID();
    data._timestamp_local = new Date().toISOString();

    return new Promise((resolve, reject) => {
      try {
        const tx = this.db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const req = store.put(data);
        req.onsuccess = () => resolve(data);
        req.onerror = (e) => reject(e.target.error);
      } catch (err) {
        console.warn(`[IndexedDB] Error en guardarItem (${storeName}):`, err);
        resolve(data);
      }
    });
  }

  async obtenerItem(storeName, key) {
    await this.asegurarDB();
    return new Promise((resolve) => {
      try {
        const tx = this.db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const req = store.get(key);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => resolve(null);
      } catch (err) {
        resolve(null);
      }
    });
  }

  async obtenerTodos(storeName) {
    await this.asegurarDB();
    return new Promise((resolve) => {
      try {
        const tx = this.db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => resolve([]);
      } catch (err) {
        resolve([]);
      }
    });
  }

  async eliminarItem(storeName, key) {
    await this.asegurarDB();
    return new Promise((resolve) => {
      try {
        const tx = this.db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const req = store.delete(key);
        req.onsuccess = () => resolve();
        req.onerror = () => resolve();
      } catch (err) {
        resolve();
      }
    });
  }

  // Obtener conteo consolidado de registros pendientes por sincronizar
  async contarPendientes() {
    await this.autoLimpiarFotosObsoletas();

    const turnos = await this.obtenerTodos('turnos');
    const combustibles = await this.obtenerTodos('combustibles');
    const incidentes = await this.obtenerTodos('incidentes');
    const fotosIA = await this.obtenerTodos('fotos_pendientes_ia');
    return {
      total: turnos.length + combustibles.length + incidentes.length + fotosIA.length,
      turnos: turnos.length,
      combustibles: combustibles.length,
      incidentes: incidentes.length,
      fotosIA: fotosIA.length
    };
  }

  // Sincronización en lote con el backend FastAPI (/api/sync/batch) con Timeout Seguro
  async sincronizarBatch(forzar = false) {
    if (!navigator.onLine && !forzar) {
      console.warn('[Sync] Dispositivo sin señal. Sincronización postergada.');
      return { success: false, motivo: 'offline' };
    }

    if (this.isSyncing) {
      console.log('[Sync] Sincronización ya en curso...');
      return { success: false, motivo: 'en_curso' };
    }

    this.isSyncing = true;
    actualizarBannerConectividad();

    try {
      await this.autoLimpiarFotosObsoletas();

      const turnos = await this.obtenerTodos('turnos');
      const combustibles = await this.obtenerTodos('combustibles');
      const incidentes = await this.obtenerTodos('incidentes');

      const totalPendientes = turnos.length + combustibles.length + incidentes.length;
      if (totalPendientes === 0) {
        // También procesar fotos IA si hubiese alguna pendiente
        await this.procesarFotosPendientesIA();
        this.ultimoErrorSync = null;
        return { success: true, total: 0 };
      }

      // Filtrar Check-Ins (los que tienen equipo_id e inicio)
      const turnosCheckIn = turnos.filter(t => t.equipo_id && (
        (t.horometro_inicio !== undefined && t.horometro_inicio !== null) ||
        (t.kilometraje_inicio !== undefined && t.kilometraje_inicio !== null)
      ));

      // Filtrar Check-Outs (los que tienen datos de cierre)
      const turnosCheckOut = turnos.filter(t => (
        (t.horometro_fin !== undefined && t.horometro_fin !== null) ||
        (t.kilometraje_fin !== undefined && t.kilometraje_fin !== null)
      ));

      const payload = {
        device_id: 'pwa-' + (navigator.userAgent.substring(0, 30)),
        turnos: turnosCheckIn,
        turnos_checkout: turnosCheckOut,
        combustibles: combustibles,
        incidentes: incidentes
      };

      console.log(`[Sync] Enviando lote al servidor (${turnosCheckIn.length} checkin, ${turnosCheckOut.length} checkout, ${combustibles.length} comb)...`);

      // Control de Timeout (10 segundos)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);

      const response = await fetch('/api/sync/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Servidor HTTP ${response.status}: ${errorText.substring(0, 100)}`);
      }

      const resData = await response.json();
      console.log('[Sync] Respuesta de servidor exitosa:', resData);

      // Limpiar turnos ya procesados
      for (const item of turnos) {
        await this.eliminarItem('turnos', item.uuid_local);
      }
      for (const item of combustibles) {
        await this.eliminarItem('combustibles', item.uuid_local);
      }
      for (const item of incidentes) {
        await this.eliminarItem('incidentes', item.uuid_local);
      }

      // Procesar fotos IA si hubiera
      await this.procesarFotosPendientesIA();

      this.ultimoErrorSync = null;
      this.ultimoSyncExitoso = new Date();
      return { success: true, resData };

    } catch (err) {
      const msg = err.name === 'AbortError' 
        ? 'Tiempo de espera agotado (Servidor inalcanzable)'
        : (err.message || 'Error de conexión');
      console.error('[Sync] Error al sincronizar lote:', msg);
      this.ultimoErrorSync = msg;
      return { success: false, error: msg };
    } finally {
      this.isSyncing = false;
      actualizarBannerConectividad();
    }
  }

  // Descarga y cachea catálogos para permitir selectores sin conexión
  async refrescarCatalogos() {
    if (!navigator.onLine) return;
    try {
      await this.asegurarDB();
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);
      const res = await fetch('/api/sync/catalogos', { signal: controller.signal });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        const tx = this.db.transaction('catalogos', 'readwrite');
        const store = tx.objectStore('catalogos');
        store.put({ tipo: 'equipos', data: data.equipos });
        store.put({ tipo: 'proyectos', data: data.proyectos });
        store.put({ tipo: 'operadores', data: data.operadores });
        console.log('[Sync] Catálogos cacheados localmente para modo offline');
      }
    } catch (e) {
      console.warn('[Sync] No se pudo actualizar catálogos:', e.message || e);
    }
  }

  async obtenerCatalogoLocal(tipo) {
    await this.asegurarDB();
    return new Promise((resolve) => {
      try {
        const tx = this.db.transaction('catalogos', 'readonly');
        const store = tx.objectStore('catalogos');
        const req = store.get(tipo);
        req.onsuccess = () => resolve(req.result ? req.result.data : []);
        req.onerror = () => resolve([]);
      } catch (e) {
        resolve([]);
      }
    });
  }
}

// Inicializar singleton
window.heavyDB = new HeavyTrackDB();

document.addEventListener('DOMContentLoaded', async () => {
  await window.heavyDB.init();
  await window.heavyDB.autoLimpiarFotosObsoletas();
  await window.heavyDB.refrescarCatalogos();
  actualizarBannerConectividad();

  // Escuchadores de estado de red del navegador
  window.addEventListener('online', async () => {
    console.log('[Red] Evento online detectado. Sincronizando lote...');
    actualizarBannerConectividad();
    await window.heavyDB.sincronizarBatch();
  });

  window.addEventListener('offline', () => {
    console.log('[Red] Evento offline detectado.');
    actualizarBannerConectividad();
  });

  // Intentar sincronizar cada 40 segundos si hay señal
  setInterval(async () => {
    if (navigator.onLine && !window.heavyDB.isSyncing) {
      await window.heavyDB.sincronizarBatch();
    }
  }, 40000);
});

// Función de interfaz persistente para el estado de conectividad
async function actualizarBannerConectividad() {
  const banner = document.getElementById('network-status-banner');
  if (!banner) return;

  const conteo = await window.heavyDB.contarPendientes();
  const pendientes = typeof conteo === 'object' ? conteo.total : conteo;
  const isSyncing = window.heavyDB.isSyncing;
  const ultimoError = window.heavyDB.ultimoErrorSync;

  // Hacer el banner interactivo al tacto
  banner.style.cursor = 'pointer';
  banner.setAttribute('title', 'Toca para ver el estado de sincronización o forzar subida');
  banner.onclick = () => {
    if (typeof window.abrirModalSincronizacion === 'function') {
      window.abrirModalSincronizacion();
    } else {
      window.heavyDB.sincronizarBatch(true);
    }
  };

  if (!navigator.onLine) {
    banner.className = 'network-badge badge-offline cursor-pointer active:scale-95 transition';
    banner.innerHTML = `<span class="pulse-dot bg-rose"></span> <span class="hidden sm:inline">🔴 Sin señal (${pendientes})</span><span class="sm:hidden">🔴 (${pendientes})</span>`;
  } else if (isSyncing) {
    banner.className = 'network-badge badge-syncing cursor-pointer active:scale-95 transition';
    banner.innerHTML = `<span class="pulse-dot bg-amber animate-pulse"></span> <span class="hidden sm:inline">🟡 Subiendo (${pendientes}...)</span><span class="sm:hidden">🟡 (${pendientes}...)</span>`;
  } else if (pendientes > 0) {
    banner.className = 'network-badge badge-syncing cursor-pointer active:scale-95 transition';
    banner.innerHTML = `<span class="pulse-dot bg-amber"></span> <span class="hidden sm:inline">🟠 ${pendientes} pendientes</span><span class="sm:hidden">🟠 (${pendientes})</span>`;
  } else {
    banner.className = 'network-badge badge-online cursor-pointer active:scale-95 transition';
    banner.innerHTML = `<span class="pulse-dot bg-emerald"></span> <span class="hidden sm:inline">🟢 Sincronizado</span><span class="sm:hidden">🟢 OK</span>`;
  }
}
