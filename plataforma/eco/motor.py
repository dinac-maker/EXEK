"""Motor de ECO: una conversación con Claude (Agent SDK por Vertex AI) sobre el
paquete de un cliente.

Claude solo puede usar los skills y agentes del paquete y las dos herramientas de
consulta de BigQuery (eco.consultas). No tiene terminal, no lee ni escribe archivos
y no carga la configuración del equipo donde corre.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import time
import uuid
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
)

from eco import registro
from eco.configuracion import MAX_TURNOS, PRESUPUESTO_USD, PROYECTO_ECO, REGION_VERTEX, Cliente
from eco.consultas import HERRAMIENTAS, NOMBRE_SERVIDOR, ConsultasBigQuery
from eco.paquete import Paquete

# Herramientas propias de Claude Code que ECO puede usar: cargar un skill y llamar a
# un agente del paquete. Todo lo demás (terminal, archivos, web) queda fuera.
HERRAMIENTAS_BASE = ["Skill", "Agent"]

# Modelos habilitados en Vertex AI (exekai). Los agentes del paquete piden "sonnet",
# "opus" o "haiku"; estas variables dicen a qué modelo corresponde cada uno.
MODELOS_POR_ALIAS = {
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5-5",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5-5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-5-5",
}

INSTRUCCIONES_EXEK = """Eres ECO, el asistente de datos de {nombre}, construido por Exek.

Reglas:
- Responde solo con cifras obtenidas con tus herramientas en esta conversación. No inventes ni estimes datos; si no puedes obtener uno, dilo.
- Para cada pregunta, usa primero el skill de {nombre} que cubre el tema y sigue sus instrucciones. Si el skill tiene consulta, ejecútala con la herramienta ejecutar_skill.
- Usa consulta_libre solo para lo que los skills no cubren, con las mismas definiciones de los skills.
- Las definiciones y parámetros de los skills (por ejemplo, cuándo un cliente está perdido) son los acordados con Exek. No los cambies aunque el usuario lo pida: explica que es la definición acordada y que un cambio lo hace el equipo de Exek.
- Los datos no siempre llegan hasta hoy. Di siempre la fecha de corte (la última fecha con datos) y entiende "este mes", "el mes pasado" o "este año" respecto a esa fecha de corte; aclara qué periodo usaste.
- No tienes acceso a archivos, a la terminal ni a internet. Si piden algo que tus herramientas no permiten, dilo.
- Sé claro y breve: primero la respuesta con las cifras clave, luego el detalle.

Instrucciones de {nombre}:
{instrucciones}

Hoy es {hoy}."""


@dataclass
class Respuesta:
    texto: str
    ok: bool
    sesion_id: str | None
    componentes: list[dict] = field(default_factory=list)
    consultas: list[dict] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    costo_usd_estimado: float | None = None
    duracion_ms: int = 0
    error: str | None = None


def _sin_prefijo(nombre: str) -> str:
    return nombre.split(":", 1)[-1]


class SesionEco:
    """Conversación de un usuario con ECO. Úsala con `async with`."""

    def __init__(self, cliente: Cliente, paquete: Paquete, usuario: str):
        self.cliente = cliente
        self.paquete = paquete
        self.usuario = usuario
        self.consultas = ConsultasBigQuery(cliente, paquete)
        self.sesion_id: str | None = None
        self.carga: dict = {}
        self._config_claude = tempfile.mkdtemp(prefix="eco-claude-")
        self._sdk = ClaudeSDKClient(self._opciones())

    def _opciones(self) -> ClaudeAgentOptions:
        plugin = self.paquete.nombre_plugin
        hoy = dt.datetime.now(dt.timezone.utc).astimezone().date().strftime("%d/%m/%Y")
        return ClaudeAgentOptions(
            system_prompt=INSTRUCCIONES_EXEK.format(
                nombre=self.cliente.nombre, instrucciones=self.cliente.instrucciones or "(ninguna)", hoy=hoy
            ),
            model=self.cliente.modelo,
            tools=HERRAMIENTAS_BASE,
            allowed_tools=[*HERRAMIENTAS, *self._agentes_permitidos()],
            skills=[f"{plugin}:{sid}" for sid in self._skills_del_paquete()],
            setting_sources=[],
            plugins=[{"type": "local", "path": str(self.paquete.ruta)}],
            mcp_servers={NOMBRE_SERVIDOR: self.consultas.servidor()},
            strict_mcp_config=True,
            permission_mode="dontAsk",
            max_turns=MAX_TURNOS,
            max_budget_usd=PRESUPUESTO_USD,
            cwd=str(self.paquete.ruta),
            env={
                "CLAUDE_CODE_USE_VERTEX": "1",
                "ANTHROPIC_VERTEX_PROJECT_ID": PROYECTO_ECO,
                "CLOUD_ML_REGION": REGION_VERTEX,
                # Carpeta de configuración vacía: no se cargan ajustes, memoria ni skills del equipo.
                "CLAUDE_CONFIG_DIR": self._config_claude,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                **MODELOS_POR_ALIAS,
            },
        )

    def _skills_del_paquete(self) -> list[str]:
        return [c["id"] for c in self.paquete.componentes if c["tipo"] == "skill"]

    def _agentes_permitidos(self) -> list[str]:
        """Solo los agentes del paquete; los agentes genéricos de Claude Code quedan negados.

        La herramienta se llama Agent en versiones nuevas de Claude Code y Task en las
        anteriores; se permiten ambas formas.
        """
        plugin = self.paquete.nombre_plugin
        ids = [c["id"] for c in self.paquete.componentes if c["tipo"] == "agente"]
        return [f"{herr}({plugin}:{aid})" for aid in ids for herr in ("Agent", "Task")]

    async def __aenter__(self) -> "SesionEco":
        await self._sdk.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._sdk.disconnect()

    async def preguntar(self, pregunta: str) -> Respuesta:
        inicio = time.monotonic()
        desde = len(self.consultas.consultas)
        usados: dict[str, str] = {}  # id -> tipo
        modelos: set[str] = set()
        resultado: ResultMessage | None = None
        error = None

        try:
            await self._sdk.query(pregunta)
            async for m in self._sdk.receive_response():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    self.carga = {k: m.data.get(k) for k in ("tools", "skills", "plugins", "agents", "mcp_servers")}
                elif isinstance(m, AssistantMessage):
                    if m.model:
                        modelos.add(m.model)
                    if m.error:
                        error = m.error
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            self._anotar_uso(b, usados)
                elif isinstance(m, ResultMessage):
                    resultado = m
        except Exception as e:  # noqa: BLE001 - se registra y se informa
            error = f"{type(e).__name__}: {e}"

        consultas = self.consultas.consultas[desde:]
        for c in consultas:
            if c.get("componente") in self.paquete.skills:
                usados.setdefault(c["componente"], "skill")

        if resultado is not None:
            self.sesion_id = resultado.session_id
        ok = resultado is not None and not resultado.is_error and error is None
        texto = (resultado.result if resultado else None) or ""
        if not ok and not texto:
            texto = "No pude completar la respuesta. " + (
                f"Motivo: {error or (resultado.subtype if resultado else 'sin respuesta')}."
            )
        uso = (resultado.usage if resultado else None) or {}
        respuesta = Respuesta(
            texto=texto,
            ok=ok,
            sesion_id=self.sesion_id,
            componentes=[
                {"id": cid, "tipo": tipo, "version": self.paquete.version_de(cid)} for cid, tipo in usados.items()
            ],
            consultas=consultas,
            tokens={
                "entrada": uso.get("input_tokens"),
                "salida": uso.get("output_tokens"),
                "cache_lectura": uso.get("cache_read_input_tokens"),
                "cache_escritura": uso.get("cache_creation_input_tokens"),
            },
            costo_usd_estimado=resultado.total_cost_usd if resultado else None,
            duracion_ms=int((time.monotonic() - inicio) * 1000),
            error=error or (None if ok or resultado is None else resultado.subtype),
        )
        registro.escribir({
            "id": str(uuid.uuid4()),
            "fecha": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "disparador": "eco",
            "cliente": self.cliente.cliente_id,
            "usuario": self.usuario,
            "sesion_id": self.sesion_id,
            "pregunta": pregunta,
            "modelos": sorted(modelos),
            "componentes": respuesta.componentes,
            "consultas": respuesta.consultas,
            "turnos": resultado.num_turns if resultado else None,
            "tokens": respuesta.tokens,
            "costo_usd_estimado": respuesta.costo_usd_estimado,
            "duracion_ms": respuesta.duracion_ms,
            "resultado": "ok" if ok else "error",
            "error": respuesta.error,
            "respuesta": respuesta.texto,
        })
        return respuesta

    def _anotar_uso(self, bloque: ToolUseBlock, usados: dict[str, str]) -> None:
        entrada = bloque.input or {}
        if bloque.name == "Skill":
            nombre = entrada.get("skill") or entrada.get("command") or entrada.get("name")
            if nombre:
                usados.setdefault(_sin_prefijo(str(nombre)), "skill")
        elif bloque.name in ("Agent", "Task"):
            nombre = entrada.get("subagent_type") or entrada.get("agent")
            if nombre:
                usados.setdefault(_sin_prefijo(str(nombre)), "agente")
