from sqlalchemy.orm import Session
from datetime import date, timedelta

from app.models.heavytrack import (
    Proyecto, Personal, InventarioRepuesto, Proveedor,
    RolPersonal, EstadoProyecto
)


def seed_flota_inicial(db: Session):
    """Garantiza la existencia del usuario administrador inicial para el dashboard."""
    from app.core.security import hash_password

    admin_existente = db.query(Personal).filter(
        Personal.rol.in_([RolPersonal.SISTEMAS_ADMIN.value, RolPersonal.GERENCIA.value])
    ).first()

    if not admin_existente:
        admin_user = Personal(
            dni="admin",
            nombres="Administrador",
            apellidos="ACR Flota 360",
            telefono="+51 900 000 000",
            rol=RolPersonal.SISTEMAS_ADMIN.value,
            contrasena_hash=hash_password("admin360"),
            pin_acceso="1234",
            estado="activo"
        )
        db.add(admin_user)
        db.commit()

    # Auto-migración segura de columnas nuevas en tablas existentes
    from sqlalchemy import text
    columnas_nuevas = [
        ("turnos_operacion", "combustible_precio_galon", "FLOAT DEFAULT 0.0"),
        ("turnos_operacion", "combustible_total_soles", "FLOAT DEFAULT 0.0"),
        ("turnos_operacion", "observaciones_inicio", "TEXT"),
        ("turnos_operacion", "horas_calentamiento", "FLOAT DEFAULT 0.25"),
        ("turnos_operacion", "horas_motor_brutas", "FLOAT DEFAULT 0.0"),
        ("control_combustible", "precio_por_galon", "FLOAT DEFAULT 0.0"),
    ]
    for tabla, columna, definicion in columnas_nuevas:
        try:
            db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
            db.commit()
        except Exception:
            db.rollback()

    return

    hoy = date.today()

    # 1. Proyectos de Construcción / Minería
    p1 = Proyecto(
        codigo="PRJ-MIN-01",
        nombre="Tajo Abierto Quellaveco - Fase III",
        ubicacion="Moquegua, Perú",
        fecha_inicio=hoy - timedelta(days=180),
        estado=EstadoProyecto.ACTIVO.value
    )
    p2 = Proyecto(
        codigo="PRJ-VIA-02",
        nombre="Ampliación Autopista Central Tramo 4",
        ubicacion="Junín, Perú",
        fecha_inicio=hoy - timedelta(days=90),
        estado=EstadoProyecto.ACTIVO.value
    )
    p3 = Proyecto(
        codigo="PRJ-URB-03",
        nombre="Movimiento de Tierras Parque Logístico",
        ubicacion="Chilca, Lima",
        fecha_inicio=hoy - timedelta(days=45),
        estado=EstadoProyecto.ACTIVO.value
    )
    db.add_all([p1, p2, p3])
    db.commit()

    # 2. Personal y Operadores
    pers1 = Personal(
        dni="45892147",
        nombres="Juan Carlos",
        apellidos="Mamani Condori",
        telefono="+51 954 112 334",
        rol=RolPersonal.OPERADOR.value,
        brevete_numero="Q45892147",
        brevete_categoria="A-IIIc",
        brevete_vencimiento=hoy + timedelta(days=12),
        pin_acceso="1234",
        estado="activo"
    )
    pers2 = Personal(
        dni="41029384",
        nombres="Segundo Raúl",
        apellidos="Alvarado Ramos",
        telefono="+51 988 776 554",
        rol=RolPersonal.OPERADOR.value,
        brevete_numero="Q41029384",
        brevete_categoria="A-IIIb",
        brevete_vencimiento=hoy + timedelta(days=180),
        pin_acceso="4321",
        estado="activo"
    )
    pers3 = Personal(
        dni="10293847",
        nombres="Ing. Roberto",
        apellidos="Vargas Mendoza",
        telefono="+51 999 001 223",
        rol=RolPersonal.JEFE_MANTENIMIENTO.value,
        pin_acceso="9999",
        estado="activo"
    )
    pers4 = Personal(
        dni="09876543",
        nombres="Lic. Mariana",
        apellidos="Soto Palacios",
        telefono="+51 998 887 766",
        rol=RolPersonal.GERENCIA.value,
        pin_acceso="8888",
        estado="activo"
    )
    db.add_all([pers1, pers2, pers3, pers4])
    db.commit()

    # 3. Maquinaria y Equipos: Se inicia en blanco para que el usuario registre su flota real
    # (No se inyecta maquinaria ficticia para permitir ingreso limpio desde cero)

    # 4. Inventario de Repuestos
    r1 = InventarioRepuesto(
        codigo_parte="CAT-1R-0716",
        nombre="Filtro de Combustible Primario CAT 336",
        categoria="Filtros",
        stock_actual=14,
        stock_minimo=4,
        precio_unitario=185.0,
        ubicacion_almacen="Almacén Quellaveco - Bahía 2"
    )
    r2 = InventarioRepuesto(
        codigo_parte="VOL-21707134",
        nombre="Filtro de Aceite de Motor Volvo D13",
        categoria="Filtros",
        stock_actual=3,
        stock_minimo=5,
        precio_unitario=240.0,
        ubicacion_almacen="Taller Central Moquegua"
    )
    r3 = InventarioRepuesto(
        codigo_parte="LUB-15W40-DRUM",
        nombre="Aceite Mineral 15W40 Cilindro 55 Galones",
        categoria="Lubricantes",
        stock_actual=8,
        stock_minimo=2,
        precio_unitario=3450.0,
        ubicacion_almacen="Patio de Lubricantes"
    )
    db.add_all([r1, r2, r3])

    # 5. Proveedores
    prov1 = Proveedor(
        ruc="20100010751",
        razon_social="Ferreyros S.A.",
        telefono="+51 1 626 4000",
        correo="ventas.mineria@ferreyros.com.pe",
        direccion="Av. Industrial 675, Lima",
        rubro="Repuestos y Maquinaria Caterpillar"
    )
    prov2 = Proveedor(
        ruc="20251147890",
        razon_social="Volvo Perú S.A.",
        telefono="+51 1 317 1200",
        correo="postventa@volvo.com.pe",
        direccion="Panamericana Sur Km 23.8",
        rubro="Camiones y Tren de Fuerza"
    )
    db.add_all([prov1, prov2])

    db.commit()
