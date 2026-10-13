"""Deterministic validity rules, configured per document type.

Validity answers "is this document within its accepted period?" — never "is it authentic?".
Every result names the values and the rule that produced it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.pipeline.findings import FindingDraft, evidence

NOT_AUTH = "Estar dentro da validade não comprova que o documento é autêntico."


@dataclass
class ValidityResult:
    state: str  # valid | expired | too_old | no_expiry | unknown | contradictory
    summary: str
    rule: str
    reference_date: str
    findings: list[FindingDraft] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"state": self.state, "summary": self.summary, "rule": self.rule, "reference_date": self.reference_date}


def _d(fields: dict, name: str) -> date | None:
    fv = fields.get(name)
    if fv is None or not fv.value:
        return None
    try:
        return date.fromisoformat(fv.value)
    except ValueError:
        return None


def _ev(fields, name, doc_id, label):
    fv = fields.get(name)
    return evidence(label, fv.raw if fv else None, document_id=doc_id, field=name,
                    page=fv.page if fv else None, bbox=fv.bbox if fv else None)


def evaluate(doc_type: str, type_spec: dict, fields: dict, doc_id, today: date) -> ValidityResult:
    rule = type_spec.get("validity", {})
    label = type_spec.get("label", doc_type)
    ref = today.isoformat()
    findings: list[FindingDraft] = []

    # logical consistency of dates, whatever the rule
    birth = _d(fields, "data_nascimento")
    issue = _d(fields, "data_expedicao") or _d(fields, "data_emissao")
    issue_name = "data_expedicao" if _d(fields, "data_expedicao") else "data_emissao"
    expiry = _d(fields, rule.get("expiry_field", "validade")) if rule.get("has_expiry") else None

    for name in ("data_nascimento", "data_expedicao", "data_emissao", "validade"):
        fv = fields.get(name)
        if fv is not None and fv.raw and fv.value is None:
            findings.append(FindingDraft(
                code="DATE_UNREADABLE", category="quality", severity="medium", field_name=name,
                title=f"Data ilegível: {name.replace('_', ' ')}",
                explanation=f"O texto '{fv.raw}' foi encontrado onde deveria estar a data, mas não forma uma data válida.",
                recommended_action="Confira a data no documento original e corrija o campo.",
                evidence=[_ev(fields, name, doc_id, "Texto lido")], document_id=doc_id, rule_id="date.parse",
            ))
    if birth and birth > today:
        findings.append(_contradiction(doc_id, fields, "data_nascimento", "A data de nascimento está no futuro.", "birth.future"))
    if birth and issue and issue < birth:
        findings.append(_contradiction(doc_id, fields, issue_name, "A data de emissão é anterior à data de nascimento.", "issue.before_birth", extra="data_nascimento"))
    if issue and issue > today:
        findings.append(_contradiction(doc_id, fields, issue_name, "A data de emissão está no futuro.", "issue.future"))
    if issue and expiry and expiry < issue:
        findings.append(_contradiction(doc_id, fields, "validade", "A validade é anterior à data de emissão.", "expiry.before_issue", extra=issue_name))

    contradictory = any(f.code == "DATE_CONTRADICTION" for f in findings)

    if rule.get("has_expiry"):
        name = rule.get("expiry_field", "validade")
        grace = int(rule.get("grace_days", 0))
        rule_txt = f"{label}: válido até a data de validade" + (f" + {grace} dias" if grace else "")
        if expiry is None:
            findings.append(FindingDraft(
                code="EXPIRY_MISSING", category="validity", severity="medium", field_name=name,
                title="Validade não encontrada",
                explanation=f"{label} tem data de validade, mas ela não foi lida com segurança. Sem ela não é possível concluir se o documento está vigente.",
                recommended_action="Localize a validade no original e preencha o campo, ou peça uma cópia legível.",
                evidence=[_ev(fields, name, doc_id, "Validade lida")], document_id=doc_id, rule_id="expiry.missing",
            ))
            return ValidityResult("unknown", "Validade não lida.", rule_txt, ref, findings)
        if expiry + timedelta(days=grace) < today:
            days = (today - expiry).days
            findings.append(FindingDraft(
                code="DOC_EXPIRED", category="validity", severity="high", field_name=name,
                title=f"Documento vencido há {days} dias",
                explanation=f"A validade lida é {expiry.strftime('%d/%m/%Y')} e a data de referência é {today.strftime('%d/%m/%Y')}. Regra: {rule_txt}. {NOT_AUTH}",
                recommended_action="Solicite um documento dentro da validade.",
                evidence=[_ev(fields, name, doc_id, "Validade")], document_id=doc_id, rule_id="expiry.passed",
            ))
            return ValidityResult("expired", f"Vencido em {expiry.strftime('%d/%m/%Y')}.", rule_txt, ref, findings)
        state = "contradictory" if contradictory else "valid"
        return ValidityResult(state, f"Dentro da validade até {expiry.strftime('%d/%m/%Y')}. {NOT_AUTH}", rule_txt, ref, findings)

    max_age = rule.get("max_age_days")
    if max_age:
        src = rule.get("max_age_from", "data_emissao")
        base = _d(fields, src)
        rule_txt = f"{label}: emitido há no máximo {max_age} dias (campo {src})"
        if base is None:
            findings.append(FindingDraft(
                code="ISSUE_DATE_MISSING", category="validity", severity="medium", field_name=src,
                title="Data de emissão não encontrada",
                explanation=f"A regra para {label} depende da data de emissão, que não foi lida. {rule.get('note', '')}".strip(),
                recommended_action="Preencha a data a partir do original ou peça uma cópia legível.",
                evidence=[_ev(fields, src, doc_id, "Data lida")], document_id=doc_id, rule_id="age.missing",
            ))
            result = ValidityResult("unknown", "Data de emissão não lida.", rule_txt, ref, findings)
        elif (today - base).days > int(max_age):
            age = (today - base).days
            findings.append(FindingDraft(
                code="DOC_TOO_OLD", category="validity", severity=rule.get("max_age_severity", "medium"), field_name=src,
                title=f"Emitido há {age} dias (limite {max_age})",
                explanation=f"Emissão em {base.strftime('%d/%m/%Y')}; a política aceita até {max_age} dias. {rule.get('note', '')} {NOT_AUTH}".strip(),
                recommended_action="Solicite uma versão mais recente ou registre a exceção com justificativa.",
                evidence=[_ev(fields, src, doc_id, "Data de emissão")], document_id=doc_id, rule_id="age.exceeded",
            ))
            result = ValidityResult("too_old", f"Emitido há {age} dias; limite de {max_age}.", rule_txt, ref, findings)
        else:
            result = ValidityResult("contradictory" if contradictory else "valid",
                                    f"Emitido em {base.strftime('%d/%m/%Y')}, dentro do limite de {max_age} dias. {NOT_AUTH}", rule_txt, ref, findings)
    else:
        result = ValidityResult("contradictory" if contradictory else "no_expiry",
                                f"{label} não expira. {rule.get('note', '')}".strip(), f"{label}: sem validade", ref, findings)

    for who in rule.get("requires_signatures") or []:
        fname, label = ("crc_contador", "do contador (registro no CRC)") if who == "contador" else ("assinatura_representante", "do representante legal")
        if not fields.get(fname) or not fields[fname].value:
            findings.append(FindingDraft(
                code="SIGNATURE_NOT_FOUND", category="validity", severity="medium", field_name=fname, key=who,
                title=f"Identificação {label} não encontrada",
                explanation=f"{label.capitalize()} não foi identificada no texto do documento. A regra exige {label.split('(')[0].strip()} assinando. A leitura automática procura o bloco de assinatura; a assinatura em si é conferida por uma pessoa.",
                recommended_action="Confira a assinatura no original. Se faltar, peça o documento assinado.",
                document_id=doc_id, rule_id=f"signature.{who}",
            ))

    gap = rule.get("current_year_max_gap_days")
    year_f, end_f = fields.get("exercicio"), fields.get("periodo_fim")
    if gap and year_f and year_f.value == str(today.year) and end_f and end_f.value:
        try:
            end = date.fromisoformat(end_f.value)
            if (today - end).days > int(gap):
                findings.append(FindingDraft(
                    code="REVENUE_OUTDATED", category="validity", severity="high", field_name="periodo_fim",
                    title=f"Faturamento {today.year} desatualizado",
                    explanation=f"O último mês informado termina em {end.strftime('%d/%m/%Y')}, {(today - end).days} dias antes da data de referência. A regra aceita intervalo máximo de cerca de 2 meses.",
                    recommended_action="Peça o faturamento atualizado, assinado pelo contador e pelo representante legal.",
                    evidence=[_ev(fields, "periodo_fim", doc_id, "Último mês")], document_id=doc_id, rule_id="revenue.gap",
                ))
                result.state = "too_old"
                result.summary = f"Faturamento até {end.strftime('%m/%Y')}; desatualizado."
        except ValueError:
            pass

    for fname, allowed in (rule.get("required_values") or {}).items():
        fv = fields.get(fname)
        if fv is None or not fv.value:
            findings.append(FindingDraft(
                code="REQUIRED_VALUE_MISSING", category="validity", severity="medium", field_name=fname,
                title=f"Campo obrigatório não lido: {fname.replace('_', ' ')}",
                explanation=f"A regra exige {fname} igual a {', '.join(allowed)}, mas o campo não foi encontrado.",
                recommended_action="Confira no original e preencha o campo.",
                evidence=[], document_id=doc_id, rule_id=f"value.{fname}",
            ))
            result.state = "unknown"
        elif fv.value.upper() not in allowed:
            findings.append(FindingDraft(
                code="REQUIRED_VALUE_MISMATCH", category="validity", severity="high", field_name=fname,
                title=f"{fname.replace('_', ' ').capitalize()}: {fv.value}",
                explanation=f"A regra exige {', '.join(allowed)}; o documento indica {fv.value}.",
                recommended_action="Não prossiga sem análise do supervisor.",
                evidence=[_ev(fields, fname, doc_id, fname)], document_id=doc_id, rule_id=f"value.{fname}",
            ))
            result.state = "invalid"
            result.summary = f"{fname.replace('_', ' ').capitalize()} {fv.value}."
    return result


def _contradiction(doc_id, fields, name, text, rule_id, extra=None) -> FindingDraft:
    ev = [_ev(fields, name, doc_id, name.replace("_", " "))]
    if extra:
        ev.append(_ev(fields, extra, doc_id, extra.replace("_", " ")))
    return FindingDraft(
        code="DATE_CONTRADICTION", category="validity", severity="high", field_name=name, key=rule_id,
        title="Datas contraditórias",
        explanation=f"{text} Pode ser erro de leitura ou indício de alteração.",
        recommended_action="Compare as datas com o original. Se a leitura estiver certa, escale para o supervisor.",
        evidence=ev, document_id=doc_id, rule_id=rule_id,
    )
