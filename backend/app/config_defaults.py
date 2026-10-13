"""Default operational configuration, seeded into app_settings on first start.

Every value here is editable by an administrator from the Settings screen. The defaults
reflect common practice for Brazilian onboarding (cadastro) and are assumptions to be
confirmed by the compliance team, not legal advice. See docs/assumptions.md.
"""

DOCUMENT_TYPES = {
    "rg": {
        "label": "Carteira de identidade (RG)",
        "keywords": ["REPUBLICA FEDERATIVA", "CARTEIRA DE IDENTIDADE", "REGISTRO GERAL", "SECRETARIA DA SEGURANCA", "SSP"],
        "fields": ["nome", "cpf", "rg_numero", "data_nascimento", "data_expedicao", "orgao_expedidor"],
        "validity": {
            "has_expiry": False,
            "max_age_days": 3650,
            "max_age_from": "data_expedicao",
            "max_age_severity": "medium",
            "note": "RG antigo não tem validade impressa. Política padrão: aceitar até 10 anos da expedição, com revisão humana acima disso.",
        },
    },
    "cin": {
        "label": "Carteira de Identidade Nacional (CIN)",
        "keywords": ["CARTEIRA DE IDENTIDADE NACIONAL", "CIN", "IDENTIDADE NACIONAL"],
        "fields": ["nome", "cpf", "data_nascimento", "data_expedicao", "validade", "orgao_expedidor"],
        "validity": {"has_expiry": True, "expiry_field": "validade", "grace_days": 0},
    },
    "cnh": {
        "label": "Carteira Nacional de Habilitação (CNH)",
        "keywords": ["CARTEIRA NACIONAL DE HABILITACAO", "HABILITACAO", "DETRAN", "PERMISSAO PARA DIRIGIR", "DENATRAN", "SENATRAN"],
        "fields": ["nome", "cpf", "cnh_registro", "data_nascimento", "data_emissao", "validade", "orgao_expedidor"],
        "validity": {
            "has_expiry": True,
            "expiry_field": "validade",
            "grace_days": 0,
            "note": "A tolerância de 30 dias do CTB vale para dirigir, não para identificação cadastral.",
        },
    },
    "comprovante_endereco": {
        "label": "Comprovante de endereço",
        "keywords": ["CONTA DE ENERGIA", "CONTA DE AGUA", "FATURA", "VENCIMENTO", "CONSUMO", "ENDERECO DE ENTREGA", "SEGUNDA VIA", "KWH", "NOTA FISCAL/FATURA"],
        "fields": ["nome", "endereco", "cep", "data_emissao", "emissor"],
        "validity": {
            "has_expiry": False,
            "max_age_days": 90,
            "max_age_from": "data_emissao",
            "max_age_severity": "high",
            "note": "Comprovante emitido há no máximo 90 dias.",
        },
    },
    "cartao_cnpj": {
        "label": "Comprovante de inscrição CNPJ",
        "keywords": ["COMPROVANTE DE INSCRICAO E DE SITUACAO CADASTRAL", "CADASTRO NACIONAL DA PESSOA JURIDICA", "SITUACAO CADASTRAL", "RECEITA FEDERAL"],
        "fields": ["cnpj", "razao_social", "situacao_cadastral", "data_emissao", "endereco"],
        "validity": {
            "has_expiry": False,
            "max_age_days": 30,
            "max_age_from": "data_emissao",
            "max_age_severity": "medium",
            "required_values": {"situacao_cadastral": ["ATIVA"]},
            "note": "Emitido há no máximo 30 dias e com situação cadastral ATIVA.",
        },
    },
    "contrato_social": {
        "label": "Contrato social / alteração consolidada",
        "keywords": ["CONTRATO SOCIAL", "ALTERACAO CONTRATUAL", "CONSOLIDACAO", "CLAUSULA", "SOCIOS", "JUNTA COMERCIAL", "QUOTAS"],
        "fields": ["razao_social", "cnpj", "socios", "data_registro"],
        "validity": {"has_expiry": False, "note": "Não expira. Conferir se é a versão consolidada mais recente."},
    },
}

REQUIREMENT_PROFILES = {
    "PF": {
        "label": "Pessoa física",
        "tax_id_kind": "cpf",
        "required": [
            {"id": "identidade", "label": "Documento de identidade com foto", "any_of": ["rg", "cin", "cnh"]},
            {"id": "endereco", "label": "Comprovante de endereço", "any_of": ["comprovante_endereco"]},
        ],
        "required_fields": [
            {"field": "cpf", "label": "CPF legível em um documento", "in_any_of": ["rg", "cin", "cnh"]},
            {"field": "data_nascimento", "label": "Data de nascimento", "in_any_of": ["rg", "cin", "cnh"]},
        ],
    },
    "PJ": {
        "label": "Pessoa jurídica",
        "tax_id_kind": "cnpj",
        "required": [
            {"id": "cnpj", "label": "Comprovante de inscrição CNPJ", "any_of": ["cartao_cnpj"]},
            {"id": "contrato", "label": "Contrato social consolidado", "any_of": ["contrato_social"]},
            {"id": "representante", "label": "Identidade do representante legal", "any_of": ["rg", "cin", "cnh"]},
            {"id": "endereco", "label": "Comprovante de endereço da empresa", "any_of": ["comprovante_endereco", "cartao_cnpj"]},
        ],
        "required_fields": [
            {"field": "cnpj", "label": "CNPJ legível", "in_any_of": ["cartao_cnpj", "contrato_social"]},
        ],
    },
}

CONSISTENCY_RULES = {
    "name_match": {
        "mode": "tokens",
        "allow_abbreviated_middle_names": True,
        "ignore_tokens": ["DE", "DA", "DO", "DOS", "DAS", "E"],
        "min_similarity_for_review": 0.80,
        "applies_to": ["rg", "cin", "cnh"],
        "address_holder_may_differ": True,
    },
    "tax_id_match": {"enabled": True},
    "birth_date_match": {"enabled": True},
    "registration_name_match": {"enabled": True},
}

PRIORITY_RULES = [
    {"id": "processing_failed", "label": "Falha no processamento", "points": 100},
    {"id": "critical_finding", "label": "Indício crítico em aberto", "points": 80},
    {"id": "escalated_finding", "label": "Ponto escalado para supervisão", "points": 70},
    {"id": "high_finding", "label": "Ponto de alta severidade em aberto", "points": 50},
    {"id": "expired_document", "label": "Documento vencido", "points": 40},
    {"id": "missing_mandatory", "label": "Documento obrigatório ausente", "points": 30},
    {"id": "waiting_over_days", "label": "Aguardando há mais de 2 dias", "points": 20, "days": 2},
    {"id": "ready_for_decision", "label": "Pronto para decisão", "points": 10},
]

PROCESSING = {
    "ai_enabled": False,
    "ai_send_images": False,
    "compare_text_layer": True,
    "duplicate_phash_distance": 6,
    "auto_assign_by_extracted_id": False,
    "min_ocr_confidence": 0.60,
}

WATCHER = {
    "enabled": False,
    "folder": "/watch/entrada",
    "scan_interval_seconds": 10,
    "stable_seconds": 8,
    "after_ingest": "move",
    "ignore_patterns": ["~$*", "*.tmp", "*.part", "*.crdownload", ".*", "Thumbs.db", "desktop.ini"],
    "association": {
        "registration_code_pattern": r"(CAD-\d{4}-\d{6})",
        "use_parent_folder": True,
        "match_tax_id_in_filename": True,
    },
}

RETENTION = {
    "rejected_days": 180,
    "abandoned_pending_days": 365,
    "approved_note": "Aprovados: manter enquanto durar o relacionamento e por 5 anos após o encerramento (Lei 9.613/1998, art. 10; Circular Bacen 3.978/2020). O encerramento vem do sistema principal; não há expurgo automático de aprovados.",
}

INTEGRATIONS = {
    "shared_folder": True,
    "email_outlook": False,
    "whatsapp": False,
}

APPROVAL = {
    "approve_roles": ["supervisor", "admin"],
    "reject_roles": ["supervisor", "admin"],
    "override_roles": ["supervisor", "admin"],
    "allow_approve_with_open_findings": False,
}

DEFAULTS: dict[str, object] = {
    "document_types": DOCUMENT_TYPES,
    "requirement_profiles": REQUIREMENT_PROFILES,
    "consistency_rules": CONSISTENCY_RULES,
    "priority_rules": PRIORITY_RULES,
    "processing": PROCESSING,
    "watcher": WATCHER,
    "retention": RETENTION,
    "integrations": INTEGRATIONS,
    "approval": APPROVAL,
}
