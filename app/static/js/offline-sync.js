/**
 * HeavyTrack Enterprise - Motor Offline-First (IndexedDB + Cola de Sincronización)
 */

const DB_NAME = 'heavytrack_offline_db';
const DB_VERSION = 2; // v2: agrega store fotos_pendientes_ia

class HeavyTrackDB {
  constructor() {
    this.db = null;
    this.isOnline = navigator.onLine;
    // Callbacks registrados por la UI para recibir resultados IA al reconectar
    this._onIAResultadoCallbacks = {};
  }

  async init() {
    return new Promise((resolve, reject) => {
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

      request.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Registra un callback que será invocado cuando se procese una foto
   * pendiente IA y vuelva un resultado. La UI lo usa para auto-rellenar
   * el campo de horómetro cuando el operador aún está en el formulario.
   *
   * @param {string} tipo - 'inicio' | 'fin'
   * @param {Function} callback - fn(resultado) donde resultado es el JSON del backend
   */
  onIAResultado(tipo, callback) {
    this._onIAResultadoCallbacks[tipo] = callback;
  }

  /**
   * Guarda una foto de tablero en IndexedDB para ser procesada por Gemini
   * cuando se recupere la conexión.
   */
  async encolarFotoIA(params) {
    const item = {
      uuid_local: this.generarUUID(),
      _timestamp_local: new Date().toISOString(),
      tipo: params.tipo,                         // 'inicio' | 'fin'
      imagen_base64: params.imagen_base64,       // dataURL completo
      lectura_ingresada: params.lectura_ingresada ?? null,
      tipo_control: params.tipo_control || 'HOROMETRO',
      equipo_codigo: params.equipo_codigo || 'EQ-MAQ',
    };
    await this.guardarItem('fotos_pendientes_ia', item);
    console.log(`[IA-Queue] Foto de tablero (${item.tipo}) encolada offline. UUID: ${item.uuid_local}`);
    return item;
  }

  /**
   * Procesa todas las fotos pendientes de análisis IA contra el backend
   * (que a su vez llama a Gemini). Se invoca automáticamente al recuperar
   * la conexión. Dispara callbacks registrados para que la UI actualice
   * el campo de horómetro si el operador sigue en el formulario.
   */
  async procesarFotosPendientesIA() {
    if (!navigator.onLine) return { procesadas: 0, motivo: 'offline' };

    const pendientes = await this.obtenerTodos('fotos_pendientes_ia');
    if (pendientes.length === 0) return { procesadas: 0 };

    console.log(`[IA-Queue] Procesando ${pendientes.length} foto(s) pendiente(s) con Gemini...`);
    let procesadas = 0;

    for (const foto of pendientes) {
      try {
        const resp = await fetch('/api/v1/heavy/ia/analizar-tablero', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            imagen_base64: foto.imagen_base64,
            lectura_ingresada: foto.lectura_ingresada,
            tipo_control: foto.tipo_control,
            equipo_codigo: foto.equipo_codigo,
          })
        });

        if (!resp.ok) {
          console.warn(`[IA-Queue] Error HTTP ${resp.status} al procesar foto ${foto.uuid_local}`);
          continue;
        }

        const resultado = await resp.json();
        resultado._uuid_foto = foto.uuid_local;
        resultado._tipo = foto.tipo;
        resultado._procesado_offline = true;

        console.log(`[IA-Queue] ✅ Foto (${foto.tipo}) procesada:`, resultado);

        // Notificar a la UI si hay un callback registrado para este tipo
        const cb = this._onIAResultadoCallbacks[foto.tipo];
        if (typeof cb === 'function') {
          try { cb(resultado); } catch (e) { console.warn('[IA-Queue] Error en callback UI:', e); }
        }

        // Emitir evento global para que cualquier parte de la app pueda reaccionar
        window.dispatchEvent(new CustomEvent('ia-resultado-offline', {
          detail: resultado
        }));

        await this.eliminarItem('fotos_pendientes_ia', foto.uuid_local);
        procesadas++;

      } catch (err) {
        console.warn(`[IA-Queue] Error procesando foto ${foto.uuid_local}:`, err);
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

  // Operaciones genéricas de almacenamiento
  async guardarItem(storeName, data) {
    if (!data.uuid_local) data.uuid_local = this.generarUUID();
    data._timestamp_local = new Date().toISOString();

    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      const req = store.put(data);
      req.onsuccess = () => resolve(data);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async obtenerTodos(storeName) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(storeName, 'readonly');
      const store = tx.objectStore(storeName);
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async eliminarItem(storeName, key) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      const req = store.delete(key);
      req.onsuccess = () => resolve();
      req.onerror = (e) => reject(e.target.error);
    });
  }

  // Obtener conteo consolidado de registros pendientes por sincronizar
  async contarPendientes() {
    const turnos = await this.obtenerTodos('turnos');
    const combustibles = await this.obtenerTodos('combustibles');
    const incidentes = await this.obtenerTodos('incidentes');
    const fotosIA = await this.obtenerTodos('fotos_pendientes_ia');
    return {
      total: turnos.length + combustibles.length + incidentes.length + fotosIA.length,
      fotosIA: fotosIA.length
    };
  }

  // Sincronización en lote con el backend FastAPI (/api/sync/batch)
  async sincronizarBatch() {
    if (!navigator.onLine) {
      console.warn('[Sync] Dispositivo sin señal. Sincronización postergada.');
      return { success: false, motivo: 'offline' };
    }

    const turnos = await this.obtenerTodos('turnos');
    const combustibles = await this.obtenerTodos('combustibles');
    const incidentes = await this.obtenerTodos('incidentes');

    const totalPendientes = turnos.length + combustibles.length + incidentes.length;
    if (totalPendientes === 0) {
      return { success: true, total: 0 };
    }

    const payload = {
      device_id: 'pwa-' + (navigator.userAgent.substring(0, 30)),
      turnos: turnos.filter(t => (t.horometro_inicio !== undefined && t.horometro_inicio !== null) || (t.kilometraje_inicio !== undefined && t.kilometraje_inicio !== null)),
      turnos_checkout: turnos.filter(t => (t.horometro_fin !== undefined && t.horometro_fin !== null) || (t.kilometraje_fin !== undefined && t.kilometraje_fin !== null)),
      combustibles: combustibles,
      incidentes: incidentes
    };

    try {
      const response = await fetch('/api/sync/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`Error en servidor: ${response.status}`);
      }

      const resData = await response.json();
      console.log('[Sync] Respuesta de servidor exitosa:', resData);

      // Limpiar ítems procesados exitosamente del almacenamiento local
      for (const item of turnos) {
        await this.eliminarItem('turnos', item.uuid_local);
      }
      for (const item of combustibles) {
        await this.eliminarItem('combustibles', item.uuid_local);
      }
      for (const item of incidentes) {
        await this.eliminarItem('incidentes', item.uuid_local);
      }

      return { success: true, resData };
    } catch (err) {
      console.error('[Sync] Error al enviar lote:', err);
      return { success: false, error: err.message };
    }
  }

  // Descarga y cachea catálogos para permitir selectores sin conexión
  async refrescarCatalogos() {
    if (!navigator.onLine) return;
    try {
      const res = await fetch('/api/sync/catalogos');
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
      console.warn('[Sync] No se pudo actualizar catálogos:', e);
    }
  }

  async obtenerCatalogoLocal(tipo) {
    return new Promise((resolve) => {
      const tx = this.db.transaction('catalogos', 'readonly');
      const store = tx.objectStore('catalogos');
      const req = store.get(tipo);
      req.onsuccess = () => resolve(req.result ? req.result.data : []);
      req.onerror = () => resolve([]);
    });
  }
}

// Inicializar singleton
window.heavyDB = new HeavyTrackDB();

document.addEventListener('DOMContentLoaded', async () => {
  await window.heavyDB.init();
  await window.heavyDB.refrescarCatalogos();
  actualizarBannerConectividad();

  // Escuchadores de estado de red
  window.addEventListener('online', async () => {
    actualizarBannerConectividad();
    console.log('[Red] Conexión recuperada. Disparando sincronización en lote...');
    await window.heavyDB.sincronizarBatch();
    // Procesar fotos de tablero que quedaron pendientes de análisis IA
    const iaRes = await window.heavyDB.procesarFotosPendientesIA();
    if (iaRes.procesadas > 0) {
      console.log(`[Red] ${iaRes.procesadas} foto(s) de tablero analizadas con Gemini Vision.`);
    }
    actualizarBannerConectividad();
  });

  window.addEventListener('offline', () => {
    actualizarBannerConectividad();
  });

  // Intentar sincronizar cada 45 segundos si hay señal
  setInterval(async () => {
    if (navigator.onLine) {
      await window.heavyDB.sincronizarBatch();
      actualizarBannerConectividad();
    }
  }, 45000);
});

// Función de interfaz persistente para el estado de conectividad
async function actualizarBannerConectividad() {
  const banner = document.getElementById('network-status-banner');
  if (!banner) return;

  const conteo = await window.heavyDB.contarPendientes();
  const pendientes = typeof conteo === 'object' ? conteo.total : conteo;
  const fotosIA = typeof conteo === 'object' ? conteo.fotosIA : 0;

  if (navigator.onLine) {
    if (pendientes > 0) {
      banner.className = 'network-badge badge-syncing';
      banner.innerHTML = `<span class="pulse-dot bg-amber"></span> 🟠 En línea (${pendientes} subiendo...)`;
    } else {
      banner.className = 'network-badge badge-online';
      banner.innerHTML = `<span class="pulse-dot bg-emerald"></span> 🟢 En línea (Sincronizado)`;
    }
  } else {
    const extraIA = fotosIA > 0 ? ` · 📸 ${fotosIA} foto(s) IA en cola` : '';
    banner.className = 'network-badge badge-offline';
    banner.innerHTML = `<span class="pulse-dot bg-rose"></span> 🔴 Sin señal (${pendientes} pendientes${extraIA})`;
  }
}
