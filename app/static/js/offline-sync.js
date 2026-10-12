/**
 * HeavyTrack Enterprise - Motor Offline-First (IndexedDB + Cola de Sincronización)
 */

const DB_NAME = 'heavytrack_offline_db';
const DB_VERSION = 1;

class HeavyTrackDB {
  constructor() {
    this.db = null;
    this.isOnline = navigator.onLine;
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
      };

      request.onsuccess = (e) => {
        this.db = e.target.result;
        resolve(this.db);
      };

      request.onerror = (e) => reject(e.target.error);
    });
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
    return turnos.length + combustibles.length + incidentes.length;
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

  const pendientes = await window.heavyDB.contarPendientes();

  if (navigator.onLine) {
    if (pendientes > 0) {
      banner.className = 'network-badge badge-syncing';
      banner.innerHTML = `<span class="pulse-dot bg-amber"></span> 🟠 En línea (${pendientes} subiendo...)`;
    } else {
      banner.className = 'network-badge badge-online';
      banner.innerHTML = `<span class="pulse-dot bg-emerald"></span> 🟢 En línea (Sincronizado)`;
    }
  } else {
    banner.className = 'network-badge badge-offline';
    banner.innerHTML = `<span class="pulse-dot bg-rose"></span> 🟠 Modo sin señal (${pendientes} pendientes de subir)`;
  }
}
