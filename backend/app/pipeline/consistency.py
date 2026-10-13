"""Cross-document consistency for one registration. Discrepancies are review items, not fraud verdicts."""

from difflib import SequenceMatcher

from app.models import Document, Registration
from app.pipeline.findings import FindingDraft, evidence
from app.pipeline.normalize import digits, format_cnpj, format_cpf, name_tokens

IDENTITY_TYPES = {"rg", "cin", "cnh"}


def _field(doc: Document, name: str):
    return next((f for f in doc.fields if f.name == name and f.value), None)


def names_compatible(a: str, b: str, rules: dict) -> tuple[bool, float, str]:
    ignore = set(rules.get("ignore_tokens", []))
    ta, tb = name_tokens(a, ignore), name_tokens(b, ignore)
    if not ta or not tb:
        return False, 0.0, "nome vazio"
    if ta == tb:
        return True, 1.0, "idênticos"
    if ta[0] != tb[0] or ta[-1] != tb[-1]:
        sim = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
        return False, sim, "primeiro ou último nome diferente"
    if rules.get("allow_abbreviated_middle_names", True):
        short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        it = iter(long_)
        ok = all(any(tok == other or (len(tok) == 1 and other.startswith(tok)) for other in it) for tok in short)
        if ok:
            return True, 0.95, "sobrenomes intermediários abreviados ou omitidos"
    sim = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return False, sim, "nomes intermediários diferentes"


def analyze(reg: Registration, docs: list[Document], rules: dict, profile: dict) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    name_rules = rules.get("name_match", {})
    applies = set(name_rules.get("applies_to", IDENTITY_TYPES))
    identity_docs = [d for d in docs if d.doc_type in applies]

    # names across identity documents and against the registration
    named = [(d, _field(d, "nome")) for d in identity_docs]
    named = [(d, f) for d, f in named if f]
    if rules.get("registration_name_match", {}).get("enabled", True) and reg.kind == "PF":
        for d, f in named:
            ok, sim, why = names_compatible(f.value, reg.subject_name, name_rules)
            if not ok:
                out.append(FindingDraft(
                    code="NAME_MISMATCH_REGISTRATION", category="consistency",
                    severity="high" if sim < name_rules.get("min_similarity_for_review", 0.8) else "medium",
                    field_name="nome", document_id=d.id, key="registration",
                    title="Nome do documento difere do cadastro",
                    explanation=f"O documento traz '{f.value}' e o cadastro está em nome de '{reg.subject_name}' ({why}; semelhança {sim:.0%}). Pode ser abreviação, mudança de nome por casamento, erro de digitação no cadastro ou documento de outra pessoa.",
                    recommended_action="Confirme o nome correto. Se houve mudança de nome, peça a certidão; se for erro de digitação, corrija o cadastro.",
                    evidence=[
                        evidence("Nome no documento", f.value, document_id=d.id, field="nome", page=f.page, bbox=f.bbox),
                        evidence("Nome no cadastro", reg.subject_name),
                    ],
                    confidence=round(sim, 2), confidence_basis="Semelhança textual entre os nomes.",
                    rule_id="consistency.name.registration",
                ))
    pairs = [] if reg.kind != "PF" else [(a, b) for i, a in enumerate(named) for b in named[i + 1:]]
    for (da, fa), (db_, fb) in pairs:
        ok, sim, why = names_compatible(fa.value, fb.value, name_rules)
        if not ok:
            out.append(FindingDraft(
                code="NAME_MISMATCH_DOCUMENTS", category="consistency", severity="high",
                field_name="nome", document_id=da.id, key=str(db_.id),
                title="Nomes diferentes entre documentos",
                explanation=f"'{fa.value}' e '{fb.value}' não correspondem ({why}; semelhança {sim:.0%}).",
                recommended_action="Verifique se os dois documentos são da mesma pessoa.",
                evidence=[
                    evidence(da.original_filename, fa.value, document_id=da.id, field="nome", page=fa.page, bbox=fa.bbox),
                    evidence(db_.original_filename, fb.value, document_id=db_.id, field="nome", page=fb.page, bbox=fb.bbox),
                ],
                confidence=round(sim, 2), confidence_basis="Semelhança textual entre os nomes.",
                rule_id="consistency.name.documents",
            ))

    # tax ids across documents and against the registration
    kind = profile.get("tax_id_kind", "cpf")
    if rules.get("tax_id_match", {}).get("enabled", True):
        with_id = [(d, _field(d, kind)) for d in docs]
        with_id = [(d, f) for d, f in with_id if f and f.valid is not False]
        if reg.tax_id:
            for d, f in with_id:
                if digits(f.value) != reg.tax_id:
                    out.append(FindingDraft(
                        code="TAX_ID_MISMATCH", category="consistency", severity="critical",
                        field_name=kind, document_id=d.id, key="registration",
                        title=f"{kind.upper()} do documento difere do cadastro",
                        explanation=f"O documento traz {kind.upper()} {f.value}, diferente do informado no cadastro. Números de identificação não admitem variação.",
                        recommended_action="Confira a leitura no original. Se o número estiver correto no documento, escale para o supervisor.",
                        evidence=[
                            evidence(f"{kind.upper()} no documento", f.value, document_id=d.id, field=kind, page=f.page, bbox=f.bbox),
                            evidence(f"{kind.upper()} no cadastro", format_cpf(reg.tax_id) if kind == "cpf" else format_cnpj(reg.tax_id)),
                        ],
                        confidence=f.confidence, confidence_basis="Leitura do número com dígitos verificadores válidos.",
                        rule_id="consistency.tax_id.registration",
                    ))
        seen: dict[str, tuple] = {}
        for d, f in with_id:
            seen.setdefault(digits(f.value), (d, f))
        if len(seen) > 1:
            items = list(seen.values())
            out.append(FindingDraft(
                code="TAX_ID_CONFLICT", category="consistency", severity="critical",
                field_name=kind, document_id=items[0][0].id, key="documents",
                title=f"Documentos com {kind.upper()} diferentes",
                explanation=f"Foram lidos {len(seen)} números de {kind.upper()} distintos entre os documentos deste cadastro.",
                recommended_action="Confira cada leitura. Documentos de pessoas diferentes no mesmo cadastro exigem escalonamento.",
                evidence=[evidence(d.original_filename, f.value, document_id=d.id, field=kind, page=f.page, bbox=f.bbox) for d, f in items],
                rule_id="consistency.tax_id.documents",
            ))

    # a company file holds several people's documents: each must be someone in the shareholder structure
    if reg.kind != "PF":
        partners = []
        for d in docs:
            if d.doc_type in ("contrato_social", "certidao_simplificada", "estatuto_social"):
                f = _field(d, "socios")
                if f:
                    partners += [p.strip() for p in f.value.split(";") if p.strip()]
        if partners:
            for d in docs:
                if d.doc_type not in ("rg", "cin", "cnh", "irpf"):
                    continue
                f = _field(d, "nome")
                if not f:
                    continue
                if not any(names_compatible(f.value, p, name_rules)[0] for p in partners):
                    out.append(FindingDraft(
                        code="PERSON_NOT_IN_PARTNERS", category="consistency", severity="low",
                        field_name="nome", document_id=d.id, key="partners",
                        title="Pessoa fora do quadro societário",
                        explanation=f"'{f.value}' não consta entre os sócios lidos ({'; '.join(partners)}). Pode ser cônjuge, devedor solidário ou representante legal.",
                        recommended_action="Confirme o vínculo da pessoa com a empresa.",
                        evidence=[evidence("Nome no documento", f.value, document_id=d.id, field="nome", page=f.page, bbox=f.bbox),
                                  evidence("Sócios", "; ".join(partners))],
                        rule_id="consistency.partners",
                    ))

    # birth dates (one person per registration only)
    if reg.kind == "PF" and rules.get("birth_date_match", {}).get("enabled", True):
        births = [(d, _field(d, "data_nascimento")) for d in identity_docs]
        births = [(d, f) for d, f in births if f]
        distinct = {f.value for _, f in births}
        if len(distinct) > 1:
            out.append(FindingDraft(
                code="BIRTH_DATE_CONFLICT", category="consistency", severity="high",
                field_name="data_nascimento", document_id=births[0][0].id, key="documents",
                title="Datas de nascimento diferentes",
                explanation="Os documentos de identidade trazem datas de nascimento diferentes.",
                recommended_action="Confira as leituras no original; se confirmadas, escale.",
                evidence=[evidence(d.original_filename, f.raw_value or f.value, document_id=d.id, field="data_nascimento", page=f.page, bbox=f.bbox) for d, f in births],
                rule_id="consistency.birth_date",
            ))

    # proof of address held by someone else
    if reg.kind == "PF":
        for d in docs:
            if d.doc_type != "comprovante_endereco":
                continue
            f = _field(d, "nome")
            if not f:
                continue
            ok, sim, why = names_compatible(f.value, reg.subject_name, name_rules)
            if not ok:
                allowed = name_rules.get("address_holder_may_differ", True)
                out.append(FindingDraft(
                    code="ADDRESS_HOLDER_DIFFERS", category="consistency", severity="low" if allowed else "medium",
                    field_name="nome", document_id=d.id, key="holder",
                    title="Comprovante em nome de outra pessoa",
                    explanation=f"O comprovante está em nome de '{f.value}'. É comum (cônjuge, pais, locador), mas a política pode exigir declaração de residência.",
                    recommended_action="Peça declaração de residência assinada pelo titular do comprovante, se a política exigir.",
                    evidence=[evidence("Titular do comprovante", f.value, document_id=d.id, field="nome", page=f.page, bbox=f.bbox),
                              evidence("Cliente", reg.subject_name)],
                    rule_id="consistency.address_holder",
                ))

    # repeated submissions of the same type with different content
    by_type: dict[str, list[Document]] = {}
    for d in docs:
        if d.doc_type:
            by_type.setdefault(d.doc_type, []).append(d)
    for t, group in by_type.items():
        if len(group) > 1 and len({d.sha256 for d in group}) > 1:
            out.append(FindingDraft(
                code="MULTIPLE_SAME_TYPE", category="consistency", severity="info",
                document_id=group[0].id, key=t,
                title="Mais de um documento do mesmo tipo",
                explanation=f"Há {len(group)} documentos classificados como {t}. Pode ser frente e verso, reenvio ou substituição.",
                recommended_action="Confirme qual documento vale e descarte os demais na decisão.",
                evidence=[evidence("Arquivo", d.original_filename, document_id=d.id) for d in group],
                rule_id="consistency.duplicates",
            ))
    return out
