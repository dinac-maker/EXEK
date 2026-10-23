"""Paquetes de cada commit en Cloud Storage.

Cuando un cambio llega a main, GitHub deja dos archivos por cliente que cambió:
    gs://exekai-paquetes/<cliente>/commits/<commit>.zip    el paquete completo
    gs://exekai-paquetes/<cliente>/commits/<commit>.json   su manifiesto (se sube al final)

Con el manifiesto, la consola registra las versiones nuevas; con el zip, arma el
paquete publicado. PaquetesLocal hace lo mismo sobre una carpeta, para las pruebas.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BUCKET = "exekai-paquetes"


class Paquetes:
    def uri(self, cliente_id: str, commit: str) -> str:
        raise NotImplementedError

    def manifiestos(self, cliente_id: str) -> list[dict]:
        """Manifiestos de los paquetes guardados, del más viejo al más nuevo."""
        raise NotImplementedError

    def existe(self, cliente_id: str, commit: str) -> bool:
        raise NotImplementedError

    def subir(self, cliente_id: str, commit: str, zip_local: Path, manifiesto: dict) -> None:
        raise NotImplementedError

    def descargar(self, cliente_id: str, commit: str, destino: Path) -> Path:
        """Descarga y descomprime el paquete de un commit en `destino`."""
        raise NotImplementedError


def _ordenar(manifiestos: list[dict]) -> list[dict]:
    return sorted(manifiestos, key=lambda m: m.get("generado") or "")


class PaquetesGCS(Paquetes):
    def __init__(self, bucket: str = BUCKET, cliente_gcs=None):
        from google.cloud import storage

        self.bucket_nombre = bucket
        self.gcs = cliente_gcs or storage.Client()
        self.bucket = self.gcs.bucket(bucket)
        self._leidos: dict[str, dict] = {}  # los manifiestos no cambian: se descargan una sola vez

    def uri(self, cliente_id, commit):
        return f"gs://{self.bucket_nombre}/{cliente_id}/commits/{commit}.zip"

    def manifiestos(self, cliente_id):
        salida = []
        for blob in self.gcs.list_blobs(self.bucket_nombre, prefix=f"{cliente_id}/commits/"):
            if blob.name.endswith(".json"):
                if blob.name not in self._leidos:
                    m = json.loads(blob.download_as_text(encoding="utf-8"))
                    m.setdefault("commit", Path(blob.name).stem)
                    self._leidos[blob.name] = m
                salida.append(self._leidos[blob.name])
        return _ordenar(salida)

    def existe(self, cliente_id, commit):
        return self.bucket.blob(f"{cliente_id}/commits/{commit}.json").exists()

    def subir(self, cliente_id, commit, zip_local, manifiesto):
        base = f"{cliente_id}/commits/{commit}"
        self.bucket.blob(base + ".zip").upload_from_filename(str(zip_local), content_type="application/zip")
        self.bucket.blob(base + ".json").upload_from_string(
            json.dumps(manifiesto, ensure_ascii=False, indent=2), content_type="application/json")

    def descargar(self, cliente_id, commit, destino):
        destino.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "paquete.zip"
            self.bucket.blob(f"{cliente_id}/commits/{commit}.zip").download_to_filename(str(archivo))
            with zipfile.ZipFile(archivo) as z:
                z.extractall(destino)
        return destino


class PaquetesLocal(Paquetes):
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)

    def _base(self, cliente_id, commit) -> Path:
        return self.carpeta / cliente_id / "commits" / commit

    def uri(self, cliente_id, commit):
        return self._base(cliente_id, commit).with_suffix(".zip").as_uri()

    def manifiestos(self, cliente_id):
        carpeta = self.carpeta / cliente_id / "commits"
        salida = []
        for f in sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []:
            m = json.loads(f.read_text(encoding="utf-8"))
            m.setdefault("commit", f.stem)
            salida.append(m)
        return _ordenar(salida)

    def existe(self, cliente_id, commit):
        return self._base(cliente_id, commit).with_suffix(".json").exists()

    def subir(self, cliente_id, commit, zip_local, manifiesto):
        base = self._base(cliente_id, commit)
        base.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(zip_local, base.with_suffix(".zip"))
        base.with_suffix(".json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")

    def descargar(self, cliente_id, commit, destino):
        destino.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self._base(cliente_id, commit).with_suffix(".zip")) as z:
            z.extractall(destino)
        return destino


def armar_publicado(cliente_id: str, elegidos: list[dict], publicados: list[dict], paquetes: Paquetes,
                    cache: Path, destino: Path) -> Path:
    """Arma un paquete con la versión en producción de cada componente elegido.

    elegidos / publicados: componentes del registro con `version_produccion` y `commit`
    (el commit de esa versión). Los publicados sirven para agregar las skills que usa un
    agente elegido aunque el rol no las tenga directamente.
    Cada componente sale del paquete de su propio commit, así que puede haber versiones
    de commits distintos en el mismo paquete.
    """
    por_id = {c["componente_id"]: c for c in publicados}

    def abrir(commit: str) -> tuple[Path, dict]:
        carpeta = cache / cliente_id / commit
        if not (carpeta / "exek" / "manifiesto.json").exists():
            tmp = carpeta.with_name(commit + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            paquetes.descargar(cliente_id, commit, tmp)
            shutil.rmtree(carpeta, ignore_errors=True)
            tmp.rename(carpeta)
        return carpeta, json.loads((carpeta / "exek" / "manifiesto.json").read_text(encoding="utf-8"))

    incluir, pendientes = {}, list(elegidos)
    while pendientes:
        c = pendientes.pop()
        if c["componente_id"] in incluir:
            continue
        carpeta, manifiesto = abrir(c["commit"])
        ficha = next((x for x in manifiesto["componentes"] if x["id"] == c["componente_id"]), None)
        if ficha is None:
            raise RuntimeError(f"El paquete {c['commit']} no trae {c['componente_id']}")
        incluir[c["componente_id"]] = (c, carpeta, manifiesto, ficha)
        for skill in ficha.get("usa_skills") or []:
            if skill in por_id and skill not in incluir:
                pendientes.append(por_id[skill])

    shutil.rmtree(destino, ignore_errors=True)
    (destino / ".claude-plugin").mkdir(parents=True)
    (destino / "exek").mkdir()
    for cid, (c, carpeta, _m, _f) in sorted(incluir.items()):
        tipo = c["tipo"]
        if tipo == "skill":
            shutil.copytree(carpeta / "skills" / cid, destino / "skills" / cid)
        elif tipo == "agente":
            (destino / "agents").mkdir(exist_ok=True)
            shutil.copy(carpeta / "agents" / f"{cid}.md", destino / "agents" / f"{cid}.md")
            (destino / "exek" / "agentes").mkdir(exist_ok=True)
            shutil.copy(carpeta / "exek" / "agentes" / f"{cid}.yaml", destino / "exek" / "agentes" / f"{cid}.yaml")
        else:
            sub = "artefactos" if tipo == "artefacto" else "plugins"
            shutil.copytree(carpeta / "exek" / sub / cid, destino / "exek" / sub / cid)

    # Las fuentes y la configuración del cliente salen del paquete más reciente que se usó.
    _, carpeta_nueva, manifiesto_nuevo, _ = max(incluir.values(), key=lambda x: x[2].get("generado") or "") \
        if incluir else (None, None, {}, None)
    if carpeta_nueva and (carpeta_nueva / "exek" / "fuentes").is_dir():
        shutil.copytree(carpeta_nueva / "exek" / "fuentes", destino / "exek" / "fuentes")
    (destino / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": f"exek-{cliente_id}", "version": "publicado",
        "description": f"Componentes publicados de {manifiesto_nuevo.get('nombre', cliente_id)} (I-NA · Exek)",
        "author": {"name": "Exek"}}, ensure_ascii=False, indent=2), encoding="utf-8")
    (destino / "exek" / "manifiesto.json").write_text(json.dumps({
        **{k: manifiesto_nuevo.get(k) for k in ("cliente_id", "nombre", "eco", "gcp", "zona_horaria", "moneda")},
        "cliente_id": cliente_id, "publicado": True,
        "componentes": [{**f, "commit": c["commit"]} for c, _carpeta, _m, f in
                        (incluir[k] for k in sorted(incluir))],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def armar_desde_git(cliente_id: str, commit: str, salida: Path) -> tuple[Path, dict]:
    """Arma el paquete de un cliente tal como estaba en un commit viejo.

    Sirve para guardar los paquetes de las versiones anteriores a este paso, que
    nunca pasaron por la subida automática de GitHub."""
    sys.path.insert(0, str(RAIZ / "herramientas"))
    from empaquetar import empaquetar  # noqa: E402

    salida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archivo = Path(tmp) / "fuente.zip"
        r = subprocess.run(["git", "archive", "--format=zip", "-o", str(archivo), commit, f"clientes/{cliente_id}"],
                           cwd=RAIZ, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"git archive {commit}: {r.stderr.strip()}")
        with zipfile.ZipFile(archivo) as z:
            z.extractall(tmp)
        destino = empaquetar(Path(tmp) / "clientes" / cliente_id, salida / commit, None, commit=commit)
        zip_local = Path(shutil.make_archive(str(salida / f"{commit}"), "zip", destino))
        manifiesto = json.loads((destino / "exek" / "manifiesto.json").read_text(encoding="utf-8"))
    return zip_local, manifiesto
