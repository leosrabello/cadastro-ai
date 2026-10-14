"""Import of the previous dashboard's backup (backup_cadastros_*.json, version 2) into the database.

JSON is only the input format; PostgreSQL is the source of truth. The same file can be imported
again: records are matched by the id they had in the old dashboard (external_id), so a reimport
updates or leaves records alone and never duplicates them. A record edited here after its last
import is not overwritten by an older file.

Flow: build_plan() validates and compares without writing; apply() writes the plan in one transaction.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Commercial, DataImport, Modality, PortfolioClient, SignatureContract, SignatureTracking, utcnow
from app.portfolio import (
    CONTRACT_KINDS,
    ONE7_ANALYSIS_TYPES,
    ONE7_RESULTS,
    Catalog,
    clean_name,
    name_key,
    parse_iso_datetime,
)
from app.settings_store import get_setting, put_setting

MAX_BYTES = 10 * 1024 * 1024
SUPPORTED_VERSIONS = (1, 2)
PREVIEW_LIMIT = 300


class ImportFileError(Exception):
    """The file as a whole cannot be imported (not JSON, wrong shape, too big)."""


@dataclass
class Issue:
    entity: str  # arquivo | status | cliente | assinatura
    level: str  # error | warning
    message: str
    ref: str | None = None
    name: str | None = None

    def out(self) -> dict:
        return {"entity": self.entity, "level": self.level, "message": self.message, "ref": self.ref, "name": self.name}


@dataclass
class Plan:
    sha256: str
    filename: str
    version: int | None
    exported_at: str | None
    previously_imported_at: str | None
    statuses_added: list[dict] = field(default_factory=list)
    statuses_relabeled: list[dict] = field(default_factory=list)
    new_commercials: list[str] = field(default_factory=list)
    clients: list[dict] = field(default_factory=list)  # {action, ext, row, existing_id, reason}
    signatures: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    catalog: dict | None = None

    def counts(self, items: list[dict]) -> dict:
        out = {"create": 0, "update": 0, "unchanged": 0, "skipped": 0, "rejected": 0}
        for i in items:
            out[i["action"]] += 1
        return out

    def summary(self) -> dict:
        return {
            "file": {"name": self.filename, "sha256": self.sha256, "version": self.version, "exported_at": self.exported_at,
                     "previously_imported_at": self.previously_imported_at},
            "clients": self.counts(self.clients),
            "signatures": self.counts(self.signatures),
            "commercials": {"create": len(self.new_commercials), "names": self.new_commercials},
            "statuses": {"added": self.statuses_added, "relabeled": self.statuses_relabeled},
            "errors": sum(1 for i in self.issues if i.level == "error"),
            "warnings": sum(1 for i in self.issues if i.level == "warning"),
        }

    def out(self) -> dict:
        def preview(items):
            return [{"action": i["action"], "external_id": i["ext"], "reason": i.get("reason"), **i.get("preview", {})} for i in items[:PREVIEW_LIMIT]]

        return {**self.summary(), "issues": [i.out() for i in self.issues], "preview": {"clients": preview(self.clients), "signatures": preview(self.signatures)}}


# ---------------------------------------------------------------- parsing helpers

class RecordError(Exception):
    pass


def _str(v: Any, field_name: str, *, required: bool = False, max_len: int = 300) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise RecordError(f"{field_name}: esperado texto")
    v = v.strip()
    if required and not v:
        raise RecordError(f"{field_name} é obrigatório")
    if len(v) > max_len:
        raise RecordError(f"{field_name} com mais de {max_len} caracteres")
    return v


def _date(v: Any, field_name: str, *, required: bool = False) -> date | None:
    if v in (None, ""):
        if required:
            raise RecordError(f"{field_name} é obrigatória")
        return None
    if not isinstance(v, str):
        raise RecordError(f"{field_name}: data inválida")
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        raise RecordError(f"{field_name}: data inválida ({v})")
    if not (2000 <= d.year <= 2100):
        raise RecordError(f"{field_name}: data fora do intervalo ({v})")
    return d


def _bool(v: Any, field_name: str) -> bool:
    if v is None:
        return False
    if not isinstance(v, bool):
        raise RecordError(f"{field_name}: esperado verdadeiro/falso")
    return v


def _flags(v: Any, field_name: str, keys: tuple[str, ...]) -> dict:
    if v is None:
        return {k: False for k in keys}
    if not isinstance(v, dict):
        raise RecordError(f"{field_name}: formato inválido")
    return {k: _bool(v.get(k), f"{field_name}.{k}") for k in keys}


def _followups(v: Any, field_name: str, kind: str) -> list[dict]:
    if v in (None, ""):
        return []
    if not isinstance(v, list):
        raise RecordError(f"{field_name}: esperado lista")
    out = []
    for i, item in enumerate(v):
        if not isinstance(item, dict):
            raise RecordError(f"{field_name}[{i}]: formato inválido")
        d = _date(item.get("data"), f"{field_name}[{i}].data", required=True)
        out.append({"date": d.isoformat(), "note": _str(item.get("retorno"), f"{field_name}[{i}].retorno", max_len=2000), "kind": kind})
    return out


def _status_history(v: Any, fallback_status: str, created_at: datetime) -> list[dict]:
    hist = []
    for item in v or []:
        if not isinstance(item, dict):
            raise RecordError("statusHistory: formato inválido")
        at = parse_iso_datetime(item.get("at"))
        if not at or not isinstance(item.get("status"), str):
            raise RecordError("statusHistory: entrada sem status ou data")
        hist.append({"status": item["status"], "at": at.isoformat()})
    hist.sort(key=lambda h: h["at"])
    if not hist:
        hist = [{"status": fallback_status, "at": created_at.isoformat()}]
    return hist


def _legacy(v: Any) -> list[dict]:
    out = []
    for item in v or []:
        if isinstance(item, dict) and item.get("texto"):
            at = parse_iso_datetime(item.get("data"))
            out.append({"at": at.isoformat() if at else None, "user": str(item.get("usuario") or "")[:120], "text": str(item["texto"])[:1000]})
    return out


def _client_row(raw: dict, modality: str, cat_keys: set[str]) -> tuple[dict, list[str]]:
    """Validated database values for one client of the file, plus warnings."""
    warnings: list[str] = []
    name = clean_name(_str(raw.get("nome"), "nome", required=True))
    status = _str(raw.get("status"), "status", required=True, max_len=64)
    if status not in cat_keys:
        raise RecordError(f"status desconhecido: {status}")
    created_at = parse_iso_datetime(raw.get("createdAt")) or utcnow()
    row: dict[str, Any] = {
        "modality": modality,
        "name": name,
        "name_key": name_key(name),
        "commercial": clean_name(_str(raw.get("comercial"), "comercial", max_len=120)),
        "status": status,
        "notes": _str(raw.get("observacoes"), "observacoes", max_len=10_000),
        "created_at": created_at,
    }
    if modality == Modality.NORMAL:
        row.update(
            entry_date=_date(raw.get("dataEntrada"), "dataEntrada"),
            pre_committee_date=_date(raw.get("dataPreComite"), "dataPreComite"),
            committee_date=_date(raw.get("dataComite"), "dataComite"),
            contract_issued_date=_date(raw.get("dataEmissaoContrato"), "dataEmissaoContrato"),
            signature_completed_date=_date(raw.get("dataConclusaoAssinatura"), "dataConclusaoAssinatura"),
            risk_exit=_bool(raw.get("saidaRisco"), "saidaRisco"),
            limit_expired=_bool(raw.get("limiteVencido"), "limiteVencido"),
            milestones={
                "formalizacao": _flags(raw.get("formalizacao"), "formalizacao", ("cadastro", "homologado")),
                "contratos": _flags(raw.get("contratos"), "contratos", ("emissao", "processo", "assinado")),
            },
            extra={},
            followups=_followups(raw.get("cobrancas"), "cobrancas", "documentacao") + _followups(raw.get("cobrancasAssinatura"), "cobrancasAssinatura", "assinatura"),
        )
        if row["contract_issued_date"] and row["signature_completed_date"] and row["signature_completed_date"] < row["contract_issued_date"]:
            raise RecordError("dataConclusaoAssinatura anterior à dataEmissaoContrato")
        if raw.get("anexos"):
            warnings.append(f"{len(raw['anexos'])} anexo(s) do painel antigo não importado(s); anexe os documentos no cadastro")
    else:
        result = _str(raw.get("resultadoComite") or "em_analise", "resultadoComite", max_len=32)
        if result not in ONE7_RESULTS:
            raise RecordError(f"resultadoComite desconhecido: {result}")
        analysis = _str(raw.get("tipoAnalise"), "tipoAnalise", max_len=32)
        if analysis and analysis not in ONE7_ANALYSIS_TYPES:
            raise RecordError(f"tipoAnalise desconhecido: {analysis}")
        sent = _date(raw.get("dataEnvioComite"), "dataEnvioComite")
        row.update(
            entry_date=_date(raw.get("dataCadastroONE7"), "dataCadastroONE7"),
            pre_committee_date=_date(raw.get("dataComiteInterno"), "dataComiteInterno"),
            committee_date=_date(raw.get("dataComiteONE7"), "dataComiteONE7"),
            contract_issued_date=None,
            signature_completed_date=None,
            risk_exit=False,
            limit_expired=False,
            milestones={
                "formalizacao": _flags(raw.get("formalizacao"), "formalizacao", ("analiseComite", "aprovacaoSistema")),
                "cadastro": _flags(raw.get("cadastro"), "cadastro", ("cadastroFormalizacao",)),
            },
            extra={
                "data_envio_comite": sent.isoformat() if sent else None,
                "resultado_comite": result,
                "tipo_analise": analysis or None,
                "em_triagem": bool(analysis) and _bool(raw.get("noBloco"), "noBloco"),
            },
            followups=_followups(raw.get("cobrancas"), "cobrancas", "documentacao"),
        )
    if row["entry_date"] is None:
        label = "dataEntrada" if modality == Modality.NORMAL else "dataCadastroONE7"
        warnings.append(f"Incompleto: sem {label}. Importado; fica fora do tempo total e das entradas por mês até a data ser preenchida.")
    row["status_history"] = _status_history(raw.get("statusHistory"), status, created_at)
    row["legacy_history"] = _legacy(raw.get("historico"))
    return row, warnings


COMPARED = ("name", "status", "entry_date", "pre_committee_date", "committee_date", "contract_issued_date", "signature_completed_date",
            "notes", "risk_exit", "limit_expired", "milestones", "extra", "followups", "status_history", "legacy_history")


def _client_differs(c: PortfolioClient, row: dict, commercial_key: str) -> list[str]:
    diff = [k for k in COMPARED if getattr(c, k) != row[k]]
    current_key = c.commercial.name_key if c.commercial else ""
    if current_key != commercial_key:
        diff.append("commercial")
    return diff


def _edited_here(obj) -> bool:
    # apply() stamps updated_at and imported_at with the same instant; any later edit here moves updated_at
    return obj.imported_at is None or obj.updated_at > obj.imported_at


# ---------------------------------------------------------------- plan

def load_file(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ImportFileError("Arquivo maior que 10 MB.")
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFileError(f"O arquivo não é um JSON válido ({exc.__class__.__name__}).")
    if not isinstance(doc, dict):
        raise ImportFileError("Estrutura inesperada: o JSON deve ser um objeto com a lista \"clients\".")
    if not isinstance(doc.get("clients"), list):
        raise ImportFileError("Estrutura inesperada: falta a lista \"clients\" do backup do painel de cadastros.")
    version = doc.get("version")
    if version is not None and version not in SUPPORTED_VERSIONS:
        raise ImportFileError(f"Versão de backup não suportada: {version}.")
    for key in ("one7Clients", "assinaturas", "customStatuses"):
        if key in doc and not isinstance(doc[key], list):
            raise ImportFileError(f"Estrutura inesperada: \"{key}\" deve ser uma lista.")
    if "statusLabels" in doc and not isinstance(doc["statusLabels"], dict):
        raise ImportFileError("Estrutura inesperada: \"statusLabels\" deve ser um objeto.")
    return doc


def _merge_catalog(doc: dict, current: dict, plan: Plan) -> dict:
    """Statuses created or renamed in the old dashboard (customStatuses, statusLabels) join the Normal catalog."""
    merged = {m: [dict(s) for s in current.get(m, [])] for m in Modality.ALL}
    normal = {s["key"]: s for s in merged[Modality.NORMAL]}
    labels = {k: v for k, v in (doc.get("statusLabels") or {}).items() if isinstance(k, str) and isinstance(v, str) and v.strip()}
    for item in doc.get("customStatuses") or []:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not isinstance(item.get("label"), str):
            plan.issues.append(Issue("status", "warning", "Status personalizado sem chave ou nome ignorado."))
            continue
        key = item["key"].strip()
        if not key or len(key) > 64:
            continue
        if key not in normal:
            entry = {"key": key, "label": (labels.get(key) or item["label"]).strip()[:80]}
            merged[Modality.NORMAL].append(entry)
            normal[key] = entry
            plan.statuses_added.append({"key": key, "label": entry["label"]})
    for key, label in labels.items():
        label = label.strip()[:80]
        if key in normal and normal[key]["label"] != label:
            plan.statuses_relabeled.append({"key": key, "from": normal[key]["label"], "to": label})
            normal[key]["label"] = label
    return merged


def build_plan(db: Session, data: bytes, filename: str) -> Plan:
    doc = load_file(data)
    sha = hashlib.sha256(data).hexdigest()
    prev = db.execute(select(DataImport).where(DataImport.sha256 == sha).order_by(DataImport.imported_at.desc())).scalars().first()
    plan = Plan(sha256=sha, filename=filename[:255], version=doc.get("version"), exported_at=doc.get("exportedAt") if isinstance(doc.get("exportedAt"), str) else None,
                previously_imported_at=prev.imported_at.isoformat() if prev else None)
    if prev:
        plan.issues.append(Issue("arquivo", "warning", "Este mesmo arquivo já foi importado antes. Nada será duplicado."))

    plan.catalog = _merge_catalog(doc, get_setting(db, "client_statuses"), plan)
    cat = Catalog(plan.catalog)
    keys = {m: set(cat.by_modality[m]) for m in Modality.ALL}

    existing_clients = {c.external_id: c for c in db.execute(select(PortfolioClient).where(PortfolioClient.external_id.is_not(None))).scalars()}
    manual_by_name = {(c.modality, c.name_key): c for c in db.execute(select(PortfolioClient).where(PortfolioClient.external_id.is_(None))).scalars()}
    known_commercials = set(db.execute(select(Commercial.name_key)).scalars())
    new_commercials: dict[str, str] = {}

    seen_ids: set[str] = set()
    seen_names: dict[tuple[str, str], str] = {}
    file_clients: dict[str, dict] = {}  # external id -> row, for linking signatures

    for modality, items in ((Modality.NORMAL, doc.get("clients") or []), (Modality.ONE7, doc.get("one7Clients") or [])):
        for idx, raw in enumerate(items):
            entity = "cliente" if modality == Modality.NORMAL else "cliente One7"
            if not isinstance(raw, dict):
                plan.clients.append({"action": "rejected", "ext": None, "reason": "registro não é um objeto"})
                plan.issues.append(Issue(entity, "error", f"Registro {idx + 1}: não é um objeto."))
                continue
            ext = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id").strip() else None
            nm = raw.get("nome") if isinstance(raw.get("nome"), str) else None
            preview = {"modality": modality, "name": clean_name(nm or ""), "commercial": clean_name(raw.get("comercial") or "") if isinstance(raw.get("comercial"), str) else None}
            if ext is None:
                plan.clients.append({"action": "rejected", "ext": None, "reason": "sem id", "preview": preview})
                plan.issues.append(Issue(entity, "error", "Registro sem id: não há como reconhecê-lo numa nova importação.", name=nm))
                continue
            if ext in seen_ids:
                plan.clients.append({"action": "rejected", "ext": ext, "reason": "id repetido no arquivo", "preview": preview})
                plan.issues.append(Issue(entity, "error", "Id repetido no arquivo; só a primeira ocorrência é importada.", ref=ext, name=nm))
                continue
            seen_ids.add(ext)
            try:
                row, warnings = _client_row(raw, modality, keys[modality])
            except RecordError as exc:
                plan.clients.append({"action": "rejected", "ext": ext, "reason": str(exc), "preview": preview})
                plan.issues.append(Issue(entity, "error", str(exc), ref=ext, name=nm))
                continue
            for w in warnings:
                plan.issues.append(Issue(entity, "warning", w, ref=ext, name=row["name"]))
            preview.update(name=row["name"], commercial=row["commercial"] or None, status_label=cat.label(modality, row["status"]),
                           entry_date=row["entry_date"].isoformat() if row["entry_date"] else None)
            dup = seen_names.get((modality, row["name_key"]))
            if dup:
                plan.issues.append(Issue(entity, "warning", f"Mesmo nome de outro registro do arquivo ({dup}); os dois foram mantidos. Confira se é a mesma pasta.", ref=ext, name=row["name"]))
            seen_names[(modality, row["name_key"])] = ext
            ck = name_key(row["commercial"]) if row["commercial"] else ""
            if ck and ck not in known_commercials and ck not in new_commercials:
                new_commercials[ck] = row["commercial"]
            file_clients[ext] = row

            current = existing_clients.get(ext)
            if current is None:
                manual = manual_by_name.get((modality, row["name_key"]))
                if manual:
                    plan.issues.append(Issue(entity, "warning", "Já existe um cliente com este nome criado no sistema; o importado entra separado. Remova um dos dois se forem a mesma pasta.", ref=ext, name=row["name"]))
                plan.clients.append({"action": "create", "ext": ext, "row": row, "preview": preview})
                continue
            if current.modality != modality:
                plan.clients.append({"action": "rejected", "ext": ext, "reason": "id já usado por um cliente de outra modalidade", "preview": preview})
                plan.issues.append(Issue(entity, "error", "O id já pertence a um cliente da outra modalidade.", ref=ext, name=row["name"]))
                continue
            diff = _client_differs(current, row, ck)
            if not diff:
                plan.clients.append({"action": "unchanged", "ext": ext, "existing_id": current.id, "preview": preview})
            elif _edited_here(current):
                plan.clients.append({"action": "skipped", "ext": ext, "existing_id": current.id, "reason": "alterado no sistema depois da última importação", "preview": preview})
                plan.issues.append(Issue(entity, "warning", "Alterado no CadastroAI depois da última importação; mantido como está no sistema.", ref=ext, name=row["name"]))
            else:
                plan.clients.append({"action": "update", "ext": ext, "existing_id": current.id, "row": row, "reason": ", ".join(diff), "preview": preview})

    _plan_signatures(db, doc, plan, file_clients, existing_clients, known_commercials, new_commercials)
    plan.new_commercials = sorted(new_commercials.values(), key=name_key)
    return plan


def _plan_signatures(db, doc, plan, file_clients, existing_clients, known_commercials, new_commercials) -> None:
    existing = {t.external_id: t for t in db.execute(select(SignatureTracking).where(SignatureTracking.external_id.is_not(None))).scalars()}
    by_name: dict[str, list[tuple[str, str]]] = {}
    for ext, row in file_clients.items():
        by_name.setdefault(row["name_key"], []).append((ext, row["modality"]))
    for c in existing_clients.values():
        if c.external_id not in file_clients:
            by_name.setdefault(c.name_key, []).append((c.external_id, c.modality))
    seen: set[str] = set()
    linked_to: dict[str, str] = {}

    for idx, raw in enumerate(doc.get("assinaturas") or []):
        if not isinstance(raw, dict):
            plan.signatures.append({"action": "rejected", "ext": None, "reason": "registro não é um objeto"})
            plan.issues.append(Issue("assinatura", "error", f"Registro {idx + 1}: não é um objeto."))
            continue
        ext = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id").strip() else None
        company = raw.get("empresa") if isinstance(raw.get("empresa"), str) else ""
        preview = {"name": clean_name(company), "commercial": clean_name(raw.get("comercial") or "") if isinstance(raw.get("comercial"), str) else None}
        if ext is None or ext in seen:
            reason = "sem id" if ext is None else "id repetido no arquivo"
            plan.signatures.append({"action": "rejected", "ext": ext, "reason": reason, "preview": preview})
            plan.issues.append(Issue("assinatura", "error", f"Registro {reason}.", ref=ext, name=company))
            continue
        seen.add(ext)
        try:
            name = clean_name(_str(company, "empresa", required=True))
            commercial = clean_name(_str(raw.get("comercial"), "comercial", max_len=120))
            contracts = {}
            for kind, key in (("SEC", "contratoSEC"), ("FIDC", "contratoFIDC")):
                k = raw.get(key) or {}
                if not isinstance(k, dict):
                    raise RecordError(f"{key}: formato inválido")
                issued = _date(k.get("dataEmissao"), f"{key}.dataEmissao")
                signed = _date(k.get("dataAssinatura"), f"{key}.dataAssinatura")
                if signed and issued and signed < issued:
                    raise RecordError(f"{key}: assinatura anterior à emissão")
                contracts[kind] = {"process_number": _str(k.get("numeroProcesso"), f"{key}.numeroProcesso", max_len=80),
                                   "created_date": _date(k.get("dataCriacao"), f"{key}.dataCriacao"), "issued_date": issued, "signed_date": signed}
                if signed and not issued:
                    plan.issues.append(Issue("assinatura", "warning", f"Contrato {kind} com assinatura e sem emissão: não entra no tempo médio.", ref=ext, name=name))
            followups = _followups(raw.get("cobrancas"), "cobrancas", "assinatura")
        except RecordError as exc:
            plan.signatures.append({"action": "rejected", "ext": ext, "reason": str(exc), "preview": preview})
            plan.issues.append(Issue("assinatura", "error", str(exc), ref=ext, name=company))
            continue

        client_ext = raw.get("clientId") if isinstance(raw.get("clientId"), str) else None
        modality = Modality.NORMAL
        link_note = None
        if client_ext:
            row = file_clients.get(client_ext)
            cur = existing_clients.get(client_ext)
            if row:
                modality = row["modality"]
            elif cur:
                modality = cur.modality
            else:
                plan.issues.append(Issue("assinatura", "warning", "Cliente vinculado não está no arquivo nem no sistema; importado sem vínculo.", ref=ext, name=name))
                client_ext = None
        else:
            matches = by_name.get(name_key(name), [])
            if len(matches) == 1:
                client_ext, modality = matches[0]
                link_note = "vinculado ao cliente pelo nome"
                plan.issues.append(Issue("assinatura", "warning", "Sem vínculo no arquivo; vinculado ao cliente de mesmo nome.", ref=ext, name=name))
        if client_ext and client_ext in linked_to:
            plan.issues.append(Issue("assinatura", "warning", f"Outro registro de assinatura já aponta para o mesmo cliente ({linked_to[client_ext]}). Confira se é repetido.", ref=ext, name=name))
        if client_ext:
            linked_to.setdefault(client_ext, ext)
        ck = name_key(commercial) if commercial else ""
        if ck and ck not in known_commercials and ck not in new_commercials:
            new_commercials[ck] = commercial

        row = {"company_name": name, "commercial": commercial, "modality": modality, "client_ext": client_ext, "contracts": contracts,
               "followups": followups, "created_at": parse_iso_datetime(raw.get("createdAt")) or utcnow()}
        preview.update(name=name, commercial=commercial or None, modality=modality, linked=bool(client_ext), link_note=link_note,
                       sec=_contract_preview(contracts["SEC"]), fidc=_contract_preview(contracts["FIDC"]))
        current = existing.get(ext)
        if current is None:
            plan.signatures.append({"action": "create", "ext": ext, "row": row, "preview": preview})
            continue
        diff = _tracking_differs(current, row, ck)
        if not diff:
            plan.signatures.append({"action": "unchanged", "ext": ext, "existing_id": current.id, "preview": preview})
        elif _edited_here(current):
            plan.signatures.append({"action": "skipped", "ext": ext, "existing_id": current.id, "reason": "alterado no sistema depois da última importação", "preview": preview})
            plan.issues.append(Issue("assinatura", "warning", "Alterado no CadastroAI depois da última importação; mantido como está no sistema.", ref=ext, name=name))
        else:
            plan.signatures.append({"action": "update", "ext": ext, "existing_id": current.id, "row": row, "reason": ", ".join(diff), "preview": preview})


def _contract_preview(k: dict) -> dict:
    return {"issued_date": k["issued_date"].isoformat() if k["issued_date"] else None, "signed_date": k["signed_date"].isoformat() if k["signed_date"] else None}


def _tracking_differs(t: SignatureTracking, row: dict, commercial_key: str) -> list[str]:
    diff = []
    if t.company_name != row["company_name"]:
        diff.append("empresa")
    if (t.commercial.name_key if t.commercial else "") != commercial_key:
        diff.append("comercial")
    if (t.client.external_id if t.client else None) != row["client_ext"]:
        diff.append("vínculo")
    if (t.followups or []) != row["followups"]:
        diff.append("cobranças")
    current = {k.kind: k for k in t.contracts}
    for kind in CONTRACT_KINDS:
        k, new = current.get(kind), row["contracts"][kind]
        if k is None or (k.process_number, k.created_date, k.issued_date, k.signed_date) != (new["process_number"], new["created_date"], new["issued_date"], new["signed_date"]):
            diff.append(f"contrato {kind}")
    return diff


# ---------------------------------------------------------------- apply

def apply(db: Session, plan: Plan, user_id) -> dict:
    now = utcnow()
    if plan.statuses_added or plan.statuses_relabeled:
        put_setting(db, "client_statuses", plan.catalog, user_id)

    commercials = {c.name_key: c for c in db.execute(select(Commercial)).scalars()}

    def commercial_for(name: str):
        if not name:
            return None
        key = name_key(name)
        if key not in commercials:
            com = Commercial(name=name, name_key=key, created_at=now, updated_at=now)
            db.add(com)
            commercials[key] = com
        return commercials[key]

    clients_by_ext = {c.external_id: c for c in db.execute(select(PortfolioClient).where(PortfolioClient.external_id.is_not(None))).scalars()}
    for item in plan.clients:
        if item["action"] not in ("create", "update"):
            continue
        row = dict(item["row"])
        com = commercial_for(row.pop("commercial"))
        if item["action"] == "create":
            c = PortfolioClient(external_id=item["ext"], source="import")
            db.add(c)
            clients_by_ext[item["ext"]] = c
        else:
            c = clients_by_ext[item["ext"]]
        for k, v in row.items():
            if k == "created_at" and item["action"] == "update":
                continue
            setattr(c, k, v)
        c.commercial = com
        c.updated_at = now
        c.imported_at = now
    db.flush()

    trackings_by_ext = {t.external_id: t for t in db.execute(select(SignatureTracking).where(SignatureTracking.external_id.is_not(None))).scalars()}
    for item in plan.signatures:
        if item["action"] not in ("create", "update"):
            continue
        row = item["row"]
        if item["action"] == "create":
            t = SignatureTracking(external_id=item["ext"], created_at=row["created_at"])
            t.contracts = [SignatureContract(kind=k) for k in CONTRACT_KINDS]
            db.add(t)
        else:
            t = trackings_by_ext[item["ext"]]
        t.company_name = row["company_name"]
        t.commercial = commercial_for(row["commercial"])
        t.modality = row["modality"]
        t.client = clients_by_ext.get(row["client_ext"]) if row["client_ext"] else None
        t.followups = row["followups"]
        by_kind = {k.kind: k for k in t.contracts}
        for kind in CONTRACT_KINDS:
            k = by_kind.get(kind)
            if k is None:
                k = SignatureContract(kind=kind)
                t.contracts.append(k)
            for attr, value in row["contracts"][kind].items():
                setattr(k, attr, value)
        t.updated_at = now
        t.imported_at = now

    result = plan.summary()
    db.add(DataImport(filename=plan.filename, sha256=plan.sha256, imported_by_id=user_id, imported_at=now, summary=result))
    db.flush()
    return result
