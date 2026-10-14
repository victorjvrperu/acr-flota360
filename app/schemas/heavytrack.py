from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from app.models.heavytrack import (
    RolPersonal, EstadoProyecto, TipoMaquinaria, EstadoOperativo,
    SeveridadIncidente, EstadoIncidente, TipoOrdenMantenimiento,
    EstadoOrdenMantenimiento, EstadoSync
)


# ==========================================
# AUTH & PERSONAL
# ==========================================
class LoginRequest(BaseModel):
    dni: str = Field(..., example="45892147")
    password_o_pin: str = Field(..., example="123456")


class VerificarAccesoRequest(BaseModel):
    dni: str = Field(..., example="00000000")
    clave: str = Field(..., example="1234")


class CambiarClaveRequest(BaseModel):
    dni: str = Field(..., example="00000000")
    clave_actual: str = Field(..., example="1234")
    nueva_clave: str = Field(..., example="5678")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    personal_id: int
    dni: str
    nombres: str
    apellidos: str
    rol: str
    brevete_alerta: Optional[str] = None


class PersonalBase(BaseModel):
    dni: str
    nombres: str
    apellidos: str
    telefono: Optional[str] = None
    rol: RolPersonal = RolPersonal.OPERADOR
    brevete_numero: Optional[str] = None
    brevete_categoria: Optional[str] = None
    brevete_vencimiento: Optional[date] = None
    pin_acceso: Optional[str] = "1234"
    tiene_certificacion: Optional[bool] = False
    certificado_nombre: Optional[str] = None
    certificado_vencimiento: Optional[date] = None
    certificado_archivo_url: Optional[str] = None
    estado: str = "activo"

    @field_validator("brevete_vencimiento", "certificado_vencimiento", mode="before")
    @classmethod
    def validar_fechas_opcionales(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(v.strip(), fmt).date()
                except ValueError:
                    pass
        return v

    @field_validator("telefono", "brevete_numero", "brevete_categoria", "certificado_nombre", "certificado_archivo_url", mode="before")
    @classmethod
    def limpiar_strings_vacios(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class PersonalCreate(PersonalBase):
    contrasena: Optional[str] = "123456"


class PersonalUpdate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    rol: Optional[RolPersonal] = None
    brevete_numero: Optional[str] = None
    brevete_categoria: Optional[str] = None
    brevete_vencimiento: Optional[date] = None
    pin_acceso: Optional[str] = None
    tiene_certificacion: Optional[bool] = None
    certificado_nombre: Optional[str] = None
    certificado_vencimiento: Optional[date] = None
    certificado_archivo_url: Optional[str] = None
    estado: Optional[str] = None

    @field_validator("brevete_vencimiento", "certificado_vencimiento", mode="before")
    @classmethod
    def validar_fechas_opcionales(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(v.strip(), fmt).date()
                except ValueError:
                    pass
        return v

    @field_validator("telefono", "brevete_numero", "brevete_categoria", "certificado_nombre", "certificado_archivo_url", mode="before")
    @classmethod
    def limpiar_strings_vacios(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class PersonalResponse(PersonalBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# PROYECTOS
# ==========================================
class ProyectoBase(BaseModel):
    codigo: str
    nombre: str
    ubicacion: str
    fecha_inicio: date
    estado: EstadoProyecto = EstadoProyecto.ACTIVO


class ProyectoCreate(ProyectoBase):
    pass


class ProyectoResponse(ProyectoBase):
    id: int
    equipos_count: Optional[int] = 0
    horas_totales: Optional[float] = 0.0
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# MAQUINARIA & EQUIPOS
# ==========================================
class MaquinariaEquipoBase(BaseModel):
    nombre: Optional[str] = None
    codigo_interno: str = Field(..., example="EX-01")
    placa: Optional[str] = None
    tipo: TipoMaquinaria = TipoMaquinaria.PESADA
    tipo_control: str = "HOROMETRO"  # HOROMETRO, KILOMETRAJE, AMBOS
    marca: str
    modelo: str
    serie_chasis: Optional[str] = None
    anio: int
    horometro_actual: float = 0.0
    odometro_actual: float = 0.0
    horometro_proximo_servicio: float = 250.0
    intervalo_servicio: float = 250.0
    poliza_seguro: Optional[str] = None
    poliza_vencimiento: Optional[date] = None
    soat_numero: Optional[str] = None
    soat_vencimiento: Optional[date] = None
    proyecto_actual_id: Optional[int] = None
    operador_asignado_id: Optional[int] = None
    estado_operativo: EstadoOperativo = EstadoOperativo.OPERATIVO
    ficha_tecnica_url: Optional[str] = None


class MaquinariaEquipoCreate(MaquinariaEquipoBase):
    pass


class AsignarEquipoRequest(BaseModel):
    proyecto_id: Optional[int] = None
    operador_id: Optional[int] = None


class MaquinariaEquipoResponse(MaquinariaEquipoBase):
    ultima_latitud: Optional[float] = None
    ultima_longitud: Optional[float] = None
    ultima_ubicacion_fecha: Optional[datetime] = None
    id: int
    semaforo_mantenimiento: Optional[str] = None  # "verde", "amarillo", "rojo"
    horas_para_servicio: Optional[float] = None
    proyecto_nombre: Optional[str] = None
    operador_asignado_nombre: Optional[str] = None
    creado_en: datetime

    class Config:
        from_attributes = True


class TelemetriaGPSRequest(BaseModel):
    equipo_id: int
    operador_id: int
    latitud: float
    longitud: float
    timestamp: Optional[datetime] = None


# ==========================================
# TURNOS OPERACION (CHECK-IN / CHECK-OUT)
# ==========================================
class TurnoCheckInCreate(BaseModel):
    uuid_local: str
    equipo_id: int
    operador_id: int
    proyecto_id: int
    fecha: date
    horometro_inicio: Optional[float] = 0.0
    foto_horometro_inicio: Optional[str] = None  # Base64 o Storage URL (Tablero horómetro/odómetro)
    kilometraje_inicio: Optional[float] = 0.0
    latitud_inicio: Optional[float] = None
    longitud_inicio: Optional[float] = None
    # Combustible al iniciar
    abastecio_combustible: Optional[bool] = False
    combustible_galones: Optional[float] = 0.0
    combustible_precio_galon: Optional[float] = 0.0
    combustible_total_soles: Optional[float] = 0.0
    foto_combustible: Optional[str] = None
    # Observaciones registradas al Check-In
    observaciones_inicio: Optional[str] = None
    # Inspección inicial 360° (4 vistas obligatorias)
    foto_inicio_delantera: Optional[str] = None
    foto_inicio_trasera: Optional[str] = None
    foto_inicio_izquierda: Optional[str] = None
    foto_inicio_derecha: Optional[str] = None


class TurnoCheckOutUpdate(BaseModel):
    uuid_local: str
    horometro_fin: Optional[float] = None
    foto_horometro_fin: Optional[str] = None
    horas_motor_brutas: Optional[float] = None
    horas_calentamiento: Optional[float] = 0.25
    horas_trabajadas: Optional[float] = None
    kilometraje_fin: Optional[float] = None
    latitud_fin: Optional[float] = None
    longitud_fin: Optional[float] = None
    # Inspección final 360° (4 vistas obligatorias)
    foto_fin_delantera: Optional[str] = None
    foto_fin_trasera: Optional[str] = None
    foto_fin_izquierda: Optional[str] = None
    foto_fin_derecha: Optional[str] = None
    # Percances / Incidencias
    hubo_incidencia: Optional[bool] = False
    incidencia_descripcion: Optional[str] = None
    descripcion_incidencia: Optional[str] = None
    foto_incidencia: Optional[str] = None


class TurnoOperacionResponse(BaseModel):
    id: int
    uuid_local: str
    equipo_id: int
    operador_id: int
    proyecto_id: int
    fecha: date
    horometro_inicio: Optional[float] = 0.0
    horometro_fin: Optional[float] = None
    horas_trabajadas: Optional[float] = None
    horas_motor_brutas: Optional[float] = None
    horas_calentamiento: Optional[float] = None
    kilometraje_inicio: Optional[float] = 0.0
    kilometraje_fin: Optional[float] = None
    km_recorridos: Optional[float] = None
    combustible_precio_galon: Optional[float] = None
    combustible_total_soles: Optional[float] = None
    observaciones_inicio: Optional[str] = None
    estado_sync: str
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# CONTROL DE COMBUSTIBLE
# ==========================================
class ControlCombustibleCreate(BaseModel):
    uuid_local: str
    equipo_id: int
    operador_id: int
    proyecto_id: int
    horometro_tanqueo: float
    galones_cargados: float
    precio_por_galon: Optional[float] = 0.0
    tipo_combustible: str = "Diesel D2 B5"
    foto_comprobante: str
    costo_total: float = 0.0
    fecha_hora: Optional[datetime] = None


class ControlCombustibleResponse(ControlCombustibleCreate):
    id: int
    estado_sync: str

    class Config:
        from_attributes = True


# ==========================================
# INCIDENTES CHECKPOINT
# ==========================================
class IncidenteCheckpointCreate(BaseModel):
    uuid_local: str
    equipo_id: int
    operador_id: int
    tipo: str
    severidad: SeveridadIncidente = SeveridadIncidente.BAJA
    descripcion: str
    foto_evidencia: str
    fecha_hora: Optional[datetime] = None


class IncidenteCheckpointResponse(IncidenteCheckpointCreate):
    id: int
    estado: str

    class Config:
        from_attributes = True


# ==========================================
# INVENTARIO DE REPUESTOS
# ==========================================
class InventarioRepuestoBase(BaseModel):
    codigo_parte: str
    nombre: str
    categoria: str
    stock_actual: int
    stock_minimo: int = 5
    precio_unitario: float
    ubicacion_almacen: Optional[str] = None


class InventarioRepuestoCreate(InventarioRepuestoBase):
    pass


class InventarioRepuestoResponse(InventarioRepuestoBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# PROVEEDORES
# ==========================================
class ProveedorBase(BaseModel):
    ruc: str
    razon_social: str
    telefono: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    rubro: str
    estado: str = "activo"


class ProveedorCreate(ProveedorBase):
    pass


class ProveedorResponse(ProveedorBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# ÓRDENES DE MANTENIMIENTO
# ==========================================
class RepuestoItemInput(BaseModel):
    repuesto_id: int
    cantidad: int


class OrdenMantenimientoCreate(BaseModel):
    codigo_ot: str
    equipo_id: int
    mecanico_id: Optional[int] = None
    proyecto_id: Optional[int] = None
    tipo: TipoOrdenMantenimiento = TipoOrdenMantenimiento.PREVENTIVO_FICHA
    horometro_al_servicio: float
    diagnostico: str
    costo_mano_obra: float = 0.0
    fecha_programada: date
    repuestos: List[RepuestoItemInput] = []


class OrdenMantenimientoResponse(BaseModel):
    id: int
    codigo_ot: str
    equipo_id: int
    mecanico_id: Optional[int] = None
    proyecto_id: Optional[int] = None
    tipo: str
    horometro_al_servicio: float
    diagnostico: str
    costo_mano_obra: float
    costo_repuestos: float
    costo_total: float
    estado: str
    fecha_programada: date
    fecha_cierre: Optional[datetime] = None
    creado_en: datetime

    class Config:
        from_attributes = True


# ==========================================
# BATCH OFFLINE SYNC (REQUERIMIENTO 4)
# ==========================================
class BatchSyncRequest(BaseModel):
    device_id: Optional[str] = "mobile-pwa"
    timestamp_envio: Optional[datetime] = None
    turnos: List[TurnoCheckInCreate] = []
    turnos_checkout: List[TurnoCheckOutUpdate] = []
    combustibles: List[ControlCombustibleCreate] = []
    incidentes: List[IncidenteCheckpointCreate] = []


class BatchSyncItemStatus(BaseModel):
    uuid_local: str
    tipo: str
    status: str  # "creado", "actualizado", "duplicado_ignorado", "error"
    mensaje: Optional[str] = None


class BatchSyncResponse(BaseModel):
    success: bool
    total_recibidos: int
    total_procesados: int
    total_duplicados: int
    detalles: List[BatchSyncItemStatus]
    timestamp_servidor: datetime
