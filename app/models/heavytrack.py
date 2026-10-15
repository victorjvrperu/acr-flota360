from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, Enum as SQLEnum, Index, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


# ==========================================
# ENUMS
# ==========================================

class RolPersonal(str, enum.Enum):
    GERENCIA = "gerencia"
    JEFE_MANTENIMIENTO = "jefe_mantenimiento"
    SISTEMAS_ADMIN = "sistemas_admin"
    OPERADOR = "operador"


class EstadoProyecto(str, enum.Enum):
    ACTIVO = "activo"
    PAUSADO = "pausado"
    CERRADO = "cerrado"


class TipoMaquinaria(str, enum.Enum):
    PESADA = "pesada"       # Excavadoras, Rodillos, Tractores, Cargadores
    CAMION = "camion"       # Volquetes, Cisternas
    LIVIANO = "liviano"     # Camionetas de supervisión, Vans


class EstadoOperativo(str, enum.Enum):
    OPERATIVO = "operativo"     # Horómetro < próximo servicio - 25
    CRITICO = "critico"         # Próximo a servicio (<25h) o vencido
    TALLER = "taller"           # En reparación u OT abierta


class SeveridadIncidente(str, enum.Enum):
    BAJA = "baja"
    MEDIA = "media"
    DETIENE_EQUIPO = "detiene_equipo"


class EstadoIncidente(str, enum.Enum):
    ABIERTO = "abierto"
    ATENDIDO = "atendido"
    CERRADO = "cerrado"


class TipoOrdenMantenimiento(str, enum.Enum):
    PREVENTIVO_FICHA = "preventivo_ficha"
    CORRECTIVO = "correctivo"


class EstadoOrdenMantenimiento(str, enum.Enum):
    PROGRAMADO = "programado"
    EN_PROCESO = "en_proceso"
    COMPLETADO = "completado"


class EstadoSync(str, enum.Enum):
    PENDIENTE = "pendiente"
    SINCRONIZADO = "sincronizado"


# ==========================================
# 1. PROYECTOS
# ==========================================
class Proyecto(Base):
    __tablename__ = "proyectos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    ubicacion = Column(String(200), nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    estado = Column(String(30), default=EstadoProyecto.ACTIVO.value, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    equipos = relationship("MaquinariaEquipo", back_populates="proyecto_actual")
    turnos = relationship("TurnoOperacion", back_populates="proyecto", cascade="all, delete-orphan")
    cargas_combustible = relationship("ControlCombustible", back_populates="proyecto", cascade="all, delete-orphan")
    ordenes_mantenimiento = relationship("OrdenMantenimiento", back_populates="proyecto")


# ==========================================
# 2. PERSONAL
# ==========================================
class Personal(Base):
    __tablename__ = "personal"

    id = Column(Integer, primary_key=True, index=True)
    dni = Column(String(20), unique=True, nullable=False, index=True)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    telefono = Column(String(30), nullable=True)
    rol = Column(String(40), default=RolPersonal.OPERADOR.value, nullable=False)
    brevete_numero = Column(String(40), nullable=True)
    brevete_categoria = Column(String(20), nullable=True)
    brevete_vencimiento = Column(Date, nullable=True)
    contrasena_hash = Column(String(255), nullable=True)
    pin_acceso = Column(String(10), nullable=True)  # PIN rápido de 4 a 6 dígitos para móvil

    # Certificación / Homologación de Operador
    tiene_certificacion = Column(Boolean, default=False, nullable=False)
    certificado_nombre = Column(String(150), nullable=True)
    certificado_vencimiento = Column(Date, nullable=True)
    certificado_archivo_url = Column(Text, nullable=True)  # Archivo digitalizado (PDF, JPG, PNG)

    estado = Column(String(30), default="activo", nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    turnos = relationship("TurnoOperacion", back_populates="operador")
    combustibles = relationship("ControlCombustible", back_populates="operador")
    incidentes = relationship("IncidenteCheckpoint", back_populates="operador")


# ==========================================
# 3. MAQUINARIA Y EQUIPOS
# ==========================================
class MaquinariaEquipo(Base):
    __tablename__ = "maquinaria_equipos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(120), nullable=True)  # ej: Excavadora Oruga CAT 336D
    codigo_interno = Column(String(50), unique=True, nullable=False, index=True)  # ej: EX-01, VOL-04
    placa = Column(String(20), nullable=True)  # Placa de rodaje (para volquetes, camionetas)
    tipo = Column(String(30), default=TipoMaquinaria.PESADA.value, nullable=False)
    tipo_control = Column(String(30), default="HOROMETRO", nullable=False)  # HOROMETRO, KILOMETRAJE, AMBOS
    marca = Column(String(80), nullable=False)
    modelo = Column(String(80), nullable=False)
    serie_chasis = Column(String(100), unique=True, nullable=True)
    anio = Column(Integer, nullable=False)
    
    # Horómetro y Kilometraje
    horometro_actual = Column(Float, default=0.0, nullable=False)
    odometro_actual = Column(Float, default=0.0, nullable=False)
    horometro_proximo_servicio = Column(Float, default=250.0, nullable=False)
    intervalo_servicio = Column(Float, default=250.0, nullable=False)  # ciclos habituales de 250h / 500h
    
    # Documentos y Seguros (Póliza / SOAT / Revisión Técnica)
    poliza_seguro = Column(String(100), nullable=True)
    poliza_vencimiento = Column(Date, nullable=True)
    soat_numero = Column(String(100), nullable=True)
    soat_vencimiento = Column(Date, nullable=True)
    revision_tecnica_numero = Column(String(100), nullable=True)
    revision_tecnica_vencimiento = Column(Date, nullable=True)
    
    proyecto_actual_id = Column(Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True)
    operador_asignado_id = Column(Integer, ForeignKey("personal.id", ondelete="SET NULL"), nullable=True)
    estado_operativo = Column(String(30), default=EstadoOperativo.OPERATIVO.value, nullable=False)
    ficha_tecnica_url = Column(String(255), nullable=True)

    # Geolocalización GPS en Tiempo Real (activa únicamente durante turno logueado)
    ultima_latitud = Column(Float, nullable=True)
    ultima_longitud = Column(Float, nullable=True)
    ultima_ubicacion_fecha = Column(DateTime, nullable=True)

    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    proyecto_actual = relationship("Proyecto", back_populates="equipos")
    operador_asignado = relationship("Personal")
    turnos = relationship("TurnoOperacion", back_populates="equipo")
    cargas_combustible = relationship("ControlCombustible", back_populates="equipo")
    incidentes = relationship("IncidenteCheckpoint", back_populates="equipo")
    ordenes_mantenimiento = relationship("OrdenMantenimiento", back_populates="equipo")


# ==========================================
# 4. TURNOS DE OPERACIÓN (OFFLINE FIRST)
# ==========================================
class TurnoOperacion(Base):
    __tablename__ = "turnos_operacion"

    id = Column(Integer, primary_key=True, index=True)
    uuid_local = Column(String(64), unique=True, nullable=False, index=True)  # Idempotencia offline
    equipo_id = Column(Integer, ForeignKey("maquinaria_equipos.id", ondelete="RESTRICT"), nullable=False)
    operador_id = Column(Integer, ForeignKey("personal.id", ondelete="RESTRICT"), nullable=False)
    proyecto_id = Column(Integer, ForeignKey("proyectos.id", ondelete="RESTRICT"), nullable=False)
    
    fecha = Column(Date, nullable=False)
    horometro_inicio = Column(Float, default=0.0, nullable=True)
    foto_horometro_inicio = Column(Text, nullable=True)  # URL o Base64 DataURI (Foto tablero/odómetro/horómetro)
    
    horometro_fin = Column(Float, nullable=True)
    foto_horometro_fin = Column(Text, nullable=True)
    horas_trabajadas = Column(Float, default=0.0, nullable=True)  # Horas efectivas netas
    horas_motor_brutas = Column(Float, default=0.0, nullable=True)  # Diferencia total de horómetro
    horas_calentamiento = Column(Float, default=0.25, nullable=True)  # Resma de 15 min (0.25h) calentamiento de motor
    
    # Control de Odómetro / Kilometraje (Volquetes, Camiones, Camionetas)
    kilometraje_inicio = Column(Float, default=0.0, nullable=True)
    kilometraje_fin = Column(Float, default=0.0, nullable=True)
    km_recorridos = Column(Float, default=0.0, nullable=True)
    
    # Verificación de Combustible al Iniciar (SÍ con foto voucher o NO con foto medidor)
    abastecio_combustible = Column(Boolean, default=False, nullable=True)
    combustible_galones = Column(Float, default=0.0, nullable=True)
    combustible_precio_galon = Column(Float, default=0.0, nullable=True)
    combustible_total_soles = Column(Float, default=0.0, nullable=True)
    foto_combustible = Column(Text, nullable=True)

    # Observaciones registradas al finalizar el Check-In
    observaciones_inicio = Column(Text, nullable=True)

    # Inspección Inicial 360° (4 vistas obligatorias)
    foto_inicio_delantera = Column(Text, nullable=True)
    foto_inicio_trasera = Column(Text, nullable=True)
    foto_inicio_izquierda = Column(Text, nullable=True)
    foto_inicio_derecha = Column(Text, nullable=True)

    # Inspección Final 360° (4 vistas obligatorias)
    foto_fin_delantera = Column(Text, nullable=True)
    foto_fin_trasera = Column(Text, nullable=True)
    foto_fin_izquierda = Column(Text, nullable=True)
    foto_fin_derecha = Column(Text, nullable=True)

    # Reporte de Incidencia / Percance al Cierre
    hubo_incidencia = Column(Boolean, default=False, nullable=True)
    incidencia_descripcion = Column(Text, nullable=True)
    foto_incidencia = Column(Text, nullable=True)

    # Coordenadas GPS del Turno (inicio y cierre)
    latitud_inicio = Column(Float, nullable=True)
    longitud_inicio = Column(Float, nullable=True)
    latitud_fin = Column(Float, nullable=True)
    longitud_fin = Column(Float, nullable=True)

    estado_sync = Column(String(30), default=EstadoSync.SINCRONIZADO.value, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    equipo = relationship("MaquinariaEquipo", back_populates="turnos")
    operador = relationship("Personal", back_populates="turnos")
    proyecto = relationship("Proyecto", back_populates="turnos")


# ==========================================
# 5. CONTROL DE COMBUSTIBLE
# ==========================================
class ControlCombustible(Base):
    __tablename__ = "control_combustible"

    id = Column(Integer, primary_key=True, index=True)
    uuid_local = Column(String(64), unique=True, nullable=False, index=True)
    equipo_id = Column(Integer, ForeignKey("maquinaria_equipos.id", ondelete="RESTRICT"), nullable=False)
    operador_id = Column(Integer, ForeignKey("personal.id", ondelete="RESTRICT"), nullable=False)
    proyecto_id = Column(Integer, ForeignKey("proyectos.id", ondelete="RESTRICT"), nullable=False)
    
    horometro_tanqueo = Column(Float, nullable=False)
    galones_cargados = Column(Float, nullable=False)
    precio_por_galon = Column(Float, default=0.0, nullable=True)
    tipo_combustible = Column(String(40), default="Diesel D2 B5", nullable=False)
    foto_comprobante = Column(Text, nullable=False)
    costo_total = Column(Float, default=0.0, nullable=False)
    fecha_hora = Column(DateTime, default=datetime.utcnow, nullable=False)
    estado_sync = Column(String(30), default=EstadoSync.SINCRONIZADO.value, nullable=False)

    # Control y Liquidación de Pagos con Jefatura / Finanzas
    estado_pago = Column(String(30), default="pendiente", nullable=False)  # pendiente, pagado, en_revision
    numero_operacion_pago = Column(String(100), nullable=True)  # Factura, Nro Operación, Voucher
    fecha_pago = Column(DateTime, nullable=True)
    observaciones_pago = Column(Text, nullable=True)

    # Relaciones
    equipo = relationship("MaquinariaEquipo", back_populates="cargas_combustible")
    operador = relationship("Personal", back_populates="combustibles")
    proyecto = relationship("Proyecto", back_populates="cargas_combustible")


# ==========================================
# 6. INCIDENTES Y CHECKPOINTS
# ==========================================
class IncidenteCheckpoint(Base):
    __tablename__ = "incidentes_checkpoint"

    id = Column(Integer, primary_key=True, index=True)
    uuid_local = Column(String(64), unique=True, nullable=False, index=True)
    equipo_id = Column(Integer, ForeignKey("maquinaria_equipos.id", ondelete="RESTRICT"), nullable=False)
    operador_id = Column(Integer, ForeignKey("personal.id", ondelete="RESTRICT"), nullable=False)
    
    tipo = Column(String(80), nullable=False)  # golpe, rayon, fuga_hidraulica, rotura_vidrio, llanta
    severidad = Column(String(30), default=SeveridadIncidente.BAJA.value, nullable=False)
    descripcion = Column(Text, nullable=False)
    foto_evidencia = Column(Text, nullable=False)
    estado = Column(String(30), default=EstadoIncidente.ABIERTO.value, nullable=False)
    fecha_hora = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    equipo = relationship("MaquinariaEquipo", back_populates="incidentes")
    operador = relationship("Personal", back_populates="incidentes")


# ==========================================
# 7. ÓRDENES DE MANTENIMIENTO
# ==========================================
class OrdenMantenimiento(Base):
    __tablename__ = "ordenes_mantenimiento"

    id = Column(Integer, primary_key=True, index=True)
    codigo_ot = Column(String(50), unique=True, nullable=False, index=True)
    equipo_id = Column(Integer, ForeignKey("maquinaria_equipos.id", ondelete="RESTRICT"), nullable=False)
    mecanico_id = Column(Integer, ForeignKey("personal.id", ondelete="SET NULL"), nullable=True)
    proyecto_id = Column(Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True)
    
    tipo = Column(String(40), default=TipoOrdenMantenimiento.PREVENTIVO_FICHA.value, nullable=False)
    horometro_al_servicio = Column(Float, nullable=False)
    diagnostico = Column(Text, nullable=False)
    costo_mano_obra = Column(Float, default=0.0, nullable=False)
    costo_repuestos = Column(Float, default=0.0, nullable=False)
    costo_total = Column(Float, default=0.0, nullable=False)
    estado = Column(String(30), default=EstadoOrdenMantenimiento.PROGRAMADO.value, nullable=False)
    fecha_programada = Column(Date, nullable=False)
    fecha_cierre = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    equipo = relationship("MaquinariaEquipo", back_populates="ordenes_mantenimiento")
    mecanico = relationship("Personal")
    proyecto = relationship("Proyecto", back_populates="ordenes_mantenimiento")
    repuestos_utilizados = relationship("MantenimientoRepuesto", back_populates="orden", cascade="all, delete-orphan")


# ==========================================
# 8. INVENTARIO DE REPUESTOS
# ==========================================
class InventarioRepuesto(Base):
    __tablename__ = "inventario_repuestos"

    id = Column(Integer, primary_key=True, index=True)
    codigo_parte = Column(String(60), unique=True, nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(String(80), nullable=False)  # Filtros, Lubricantes, Orings, Cadenas, Puntas
    stock_actual = Column(Integer, default=0, nullable=False)
    stock_minimo = Column(Integer, default=5, nullable=False)
    precio_unitario = Column(Float, default=0.0, nullable=False)
    ubicacion_almacen = Column(String(80), nullable=True)  # Estante A-3, Bahía 2
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    ordenes = relationship("MantenimientoRepuesto", back_populates="repuesto")


# ==========================================
# 9. PROVEEDORES
# ==========================================
class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)
    ruc = Column(String(20), unique=True, nullable=False, index=True)
    razon_social = Column(String(200), nullable=False)
    telefono = Column(String(30), nullable=True)
    correo = Column(String(100), nullable=True)
    direccion = Column(String(200), nullable=True)
    rubro = Column(String(100), nullable=False)  # Lubricantes, Repuestos CAT/Komatsu, Filtros
    estado = Column(String(20), default="activo", nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


# ==========================================
# 10. MANTENIMIENTO_REPUESTOS (INTERMEDIA)
# ==========================================
class MantenimientoRepuesto(Base):
    __tablename__ = "mantenimiento_repuestos"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes_mantenimiento.id", ondelete="CASCADE"), nullable=False)
    repuesto_id = Column(Integer, ForeignKey("inventario_repuestos.id", ondelete="RESTRICT"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_historico = Column(Float, nullable=False)

    # Relaciones
    orden = relationship("OrdenMantenimiento", back_populates="repuestos_utilizados")
    repuesto = relationship("InventarioRepuesto", back_populates="ordenes")


# ==========================================
# 11. NOTIFICACIONES Y ALERTAS
# ==========================================
class TipoNotificacion(str, enum.Enum):
    MANTENIMIENTO_ENTRADA = "mantenimiento_entrada"       # Equipo entra a taller / OT abierta
    MANTENIMIENTO_PROXIMO = "mantenimiento_proximo"       # Próximo a servicio (<25h o <500km)
    MANTENIMIENTO_VENCIDO = "mantenimiento_vencido"       # Horómetro superó límite de mantenimiento
    REVISION_TECNICA = "revision_tecnica"                 # Revisión técnica por vencer / vencida
    SOAT_POLIZA = "soat_poliza"                           # SOAT o póliza por vencer / vencida
    INCONGRUENCIA_DATOS = "incongruencia_datos"           # Lectura menor a la anterior, salto anómalo
    INCIDENCIA_FALLA = "incidencia_falla"                 # Operador reportó falla en checklist


class NotificacionAlerta(Base):
    __tablename__ = "notificaciones_alertas"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(50), nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    mensaje = Column(Text, nullable=False)
    severidad = Column(String(20), default="warning", nullable=False)  # info, warning, critical
    equipo_id = Column(Integer, ForeignKey("maquinaria_equipos.id", ondelete="SET NULL"), nullable=True)
    leido = Column(Boolean, default=False, nullable=False)
    canal_whatsapp_enviado = Column(Boolean, default=False, nullable=False)
    whatsapp_link = Column(Text, nullable=True)
    datos_extra = Column(Text, nullable=True)  # JSON string con detalles técnicos
    creado_en = Column(DateTime, default=datetime.utcnow, index=True)

    # Relación
    equipo = relationship("MaquinariaEquipo")


# ==========================================
# 12. AJUSTES Y CONFIGURACIÓN DEL SISTEMA
# ==========================================
class AjusteSistema(Base):
    __tablename__ = "ajustes_sistema"

    id = Column(Integer, primary_key=True, index=True)
    clave = Column(String(100), unique=True, nullable=False, index=True)
    valor = Column(Text, nullable=True)
    descripcion = Column(String(255), nullable=True)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

