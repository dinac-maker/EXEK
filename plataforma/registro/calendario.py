"""Cuándo toca correr una programación.

Una programación corre en su zona horaria (America/Bogota por defecto), solo entre su
fecha de inicio y su fecha de fin (ambas incluidas), con una de estas frecuencias:
- diaria: todos los días a la hora indicada;
- semanal: los días indicados (lun, mar, mie, jue, vie, sab, dom) a la hora indicada;
- mensual: el día del mes indicado (si el mes es más corto, el último día) a la hora indicada;
- horas: cada N horas, desde la hora indicada hasta el final del día.

El reloj despierta cada 15 minutos y corre la última hora programada que todavía no tenga
ejecución, si no tiene más de VENTANA de atraso. Así, si el reloj se detuvo un rato, la
tarea corre una vez al volver (no una vez por cada hora perdida).
"""
from __future__ import annotations

import calendar
import datetime as dt
from zoneinfo import ZoneInfo

DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
NOMBRES_DIAS = {"lun": "lunes", "mar": "martes", "mie": "miércoles", "jue": "jueves", "vie": "viernes",
                "sab": "sábado", "dom": "domingo"}
FRECUENCIAS = ("diaria", "semanal", "mensual", "horas")
VENTANA = dt.timedelta(hours=24)


def _hora(texto: str) -> dt.time:
    h, m = (int(x) for x in texto.split(":"))
    return dt.time(h, m)


def _toca_el_dia(p: dict, dia: dt.date) -> bool:
    if p.get("fecha_inicio") and dia < p["fecha_inicio"]:
        return False
    if p.get("fecha_fin") and dia > p["fecha_fin"]:
        return False
    f = p["frecuencia"]
    if f == "semanal":
        return DIAS[dia.weekday()] in (p.get("dias") or [])
    if f == "mensual":
        ultimo = calendar.monthrange(dia.year, dia.month)[1]
        return dia.day == min(int(p["dia_mes"]), ultimo)
    return True  # diaria y horas


def _horas_del_dia(p: dict) -> list[dt.time]:
    inicio = _hora(p["hora"])
    if p["frecuencia"] != "horas":
        return [inicio]
    paso = max(1, int(p["cada_horas"]))
    return [dt.time(h, inicio.minute) for h in range(inicio.hour, 24, paso)]


def ocurrencias(p: dict, desde: dt.datetime, hasta: dt.datetime) -> list[dt.datetime]:
    """Horas programadas (en UTC) entre `desde` y `hasta`, ambas incluidas."""
    zona = ZoneInfo(p.get("zona_horaria") or "America/Bogota")
    dia = desde.astimezone(zona).date() - dt.timedelta(days=1)
    ultimo = hasta.astimezone(zona).date() + dt.timedelta(days=1)
    salida = []
    while dia <= ultimo:
        if _toca_el_dia(p, dia):
            for h in _horas_del_dia(p):
                momento = dt.datetime.combine(dia, h, tzinfo=zona).astimezone(dt.timezone.utc)
                if desde <= momento <= hasta:
                    salida.append(momento)
        dia += dt.timedelta(days=1)
    return salida


def pendiente(p: dict, ahora: dt.datetime, ya_atendidas: set[dt.datetime]) -> dt.datetime | None:
    """La hora programada que hay que correr ahora, o None."""
    if not p.get("activa"):
        return None
    for momento in reversed(ocurrencias(p, ahora - VENTANA, ahora)):
        return None if momento in ya_atendidas else momento
    return None


def proxima(p: dict, ahora: dt.datetime) -> dt.datetime | None:
    """La siguiente hora programada después de `ahora` (en el próximo año), o None."""
    if not p.get("activa"):
        return None
    futuras = ocurrencias(p, ahora + dt.timedelta(seconds=1), ahora + dt.timedelta(days=370))
    return futuras[0] if futuras else None


def describir(p: dict) -> str:
    """'Lunes a las 07:00' / 'Todos los días a las 06:00' / 'Cada 4 horas desde las 08:00'."""
    f, hora = p["frecuencia"], p["hora"]
    if f == "diaria":
        texto = f"Todos los días a las {hora}"
    elif f == "semanal":
        dias = [NOMBRES_DIAS[d] for d in DIAS if d in (p.get("dias") or [])]
        lista = dias[0] if len(dias) == 1 else ", ".join(dias[:-1]) + " y " + dias[-1]
        texto = f"{lista[:1].upper()}{lista[1:]} a las {hora}"
    elif f == "mensual":
        texto = f"El día {p['dia_mes']} de cada mes a las {hora}"
    else:
        texto = f"Cada {p['cada_horas']} horas desde las {hora}"
    return texto + f" ({p.get('zona_horaria') or 'America/Bogota'})"
