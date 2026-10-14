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
            "max_age_days": 60,
            "max_age_from": "data_emissao",
            "max_age_severity": "high",
            "note": "Comprovante emitido há no máximo 60 dias (checklist FinTrust 2026).",
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
        "label": "Contrato social / última alteração consolidada",
        "keywords": ["CONTRATO SOCIAL", "ALTERACAO CONTRATUAL", "CONSOLIDACAO", "CLAUSULA", "SOCIOS", "QUOTAS"],
        "fields": ["razao_social", "cnpj", "socios", "data_registro"],
        "validity": {"has_expiry": False, "note": "Não expira. Conferir se é a última alteração consolidada."},
    },
    "certidao_simplificada": {
        "label": "Certidão simplificada da Junta Comercial",
        "keywords": ["CERTIDAO SIMPLIFICADA", "JUNTA COMERCIAL", "CERTIFICAMOS", "ATOS ARQUIVADOS", "NIRE"],
        "fields": ["razao_social", "cnpj", "socios", "data_emissao"],
        "validity": {"has_expiry": False, "max_age_days": 60, "max_age_from": "data_emissao", "max_age_severity": "high", "note": "Emitida há no máximo 60 dias (checklist FinTrust 2026)."},
    },
    "estatuto_social": {
        "label": "Estatuto social (S/A)",
        "keywords": ["ESTATUTO SOCIAL", "SOCIEDADE ANONIMA", "S.A.", "ASSEMBLEIA GERAL", "ACOES"],
        "fields": ["razao_social", "cnpj", "data_registro"],
        "validity": {"has_expiry": False, "note": "Conferir se é a versão atualizada."},
    },
    "ata_eleicao": {
        "label": "Ata de eleição da diretoria (S/A)",
        "keywords": ["ATA DA ASSEMBLEIA", "ATA DE REUNIAO", "ELEICAO", "DIRETORIA", "MANDATO", "CONSELHO DE ADMINISTRACAO"],
        "fields": ["razao_social", "cnpj", "data_emissao"],
        "validity": {"has_expiry": False, "note": "Conferir se o mandato da diretoria está vigente."},
    },
    "balanco_dre": {
        "label": "Balanço patrimonial e DRE",
        "keywords": ["BALANCO PATRIMONIAL", "DEMONSTRACAO DO RESULTADO", "DRE", "ATIVO CIRCULANTE", "PASSIVO CIRCULANTE", "PATRIMONIO LIQUIDO"],
        "fields": ["razao_social", "cnpj", "exercicio", "receita_liquida", "lucro_liquido", "patrimonio_liquido", "ativo_total", "crc_contador", "assinatura_representante"],
        "validity": {"has_expiry": False, "requires_signatures": ["contador", "representante"], "note": "Assinado por representante legal e contador."},
    },
    "balancete": {
        "label": "Balancete do exercício vigente",
        "keywords": ["BALANCETE", "BALANCETE DE VERIFICACAO", "SALDO ANTERIOR", "DEBITO", "CREDITO"],
        "fields": ["razao_social", "cnpj", "exercicio", "receita_liquida", "crc_contador", "assinatura_representante"],
        "validity": {"has_expiry": False, "requires_signatures": ["contador", "representante"], "note": "Assinado por representante legal e contador."},
    },
    "faturamento": {
        "label": "Relação de faturamento",
        "keywords": ["FATURAMENTO", "RELACAO DE FATURAMENTO", "RECEITA BRUTA", "JANEIRO", "FEVEREIRO", "DEZEMBRO"],
        "fields": ["razao_social", "cnpj", "exercicio", "faturamento_mensal", "faturamento_total", "periodo_fim", "crc_contador", "assinatura_representante"],
        "validity": {"has_expiry": False, "requires_signatures": ["contador", "representante"], "current_year_max_gap_days": 62,
                     "note": "Fechado nos anos anteriores; no ano vigente, com intervalo máximo de 2 meses. Assinado pelo contador e pelo representante legal."},
    },
    "endividamento": {
        "label": "Endividamento financeiro",
        "keywords": ["ENDIVIDAMENTO", "INSTITUICAO", "SALDO DEVEDOR", "FACTORING", "SECURITIZADORA", "LIMITE"],
        "fields": ["razao_social", "cnpj", "data_emissao", "endividamento_total", "endividamento_itens"],
        "validity": {"has_expiry": False, "max_age_days": 90, "max_age_from": "data_emissao", "max_age_severity": "high",
                     "note": "Bancos, fundos, FIDCs, factorings, securitizadoras e demais instituições; emitido há no máximo 90 dias."},
    },
    "curva_abc": {
        "label": "Curva ABC de clientes",
        "keywords": ["CURVA ABC", "CLIENTES", "PARTICIPACAO", "CLASSE A", "CLASSE B"],
        "fields": ["razao_social", "data_emissao", "concentracao_clientes"],
        "validity": {"has_expiry": False},
    },
    "irpf": {
        "label": "IRPF (declaração de ajuste anual)",
        "keywords": ["IMPOSTO SOBRE A RENDA", "DECLARACAO DE AJUSTE ANUAL", "ANO-CALENDARIO", "BENS E DIREITOS", "RECEITA FEDERAL"],
        "fields": ["nome", "cpf", "exercicio", "patrimonio_declarado", "dividas_onus", "lucros_dividendos"],
        "validity": {"has_expiry": False, "note": "Dos sócios e/ou devedores solidários."},
    },
    "relatorio_visita": {
        "label": "Relatório de visita comercial",
        "keywords": ["RELATORIO DE VISITA", "VISITA COMERCIAL", "VISITA TECNICA", "REGISTRO FOTOGRAFICO"],
        "fields": ["razao_social", "data_emissao"],
        "validity": {"has_expiry": False, "note": "Com registro fotográfico da empresa visitada."},
    },
    "certidao_casamento": {
        "label": "Certidão de casamento / união estável",
        "keywords": ["CERTIDAO DE CASAMENTO", "UNIAO ESTAVEL", "REGIME DE BENS", "CONTRAENTES", "AVERBACAO"],
        "fields": ["nome", "data_emissao", "regime_bens"],
        "validity": {"has_expiry": False, "note": "Se divorciado(a) ou viúvo(a), com a averbação."},
    },
}

REQUIREMENT_PROFILES = {
    # FinTrust standard (Checklist de Documentos 2026, v2.1). "{ano}" in a label is the year the
    # requirement refers to, computed from year_offset, so the checklist rolls forward each year.
    "PJ": {
        "label": "Empresa (FIDC)",
        "tax_id_kind": "cnpj",
        "source": "Checklist de Documentos FinTrust 2026 (v2.1)",
        "stages": [
            {"id": "analise", "label": "Análise de crédito", "blocks_decision": True},
            {"id": "formalizacao", "label": "Formalização", "blocks_decision": False,
             "note": "Exigida somente após a aprovação em Comitê de Crédito."},
        ],
        "required": [
            {"id": "societario", "stage": "analise", "group": "Documentos societários",
             "label": "Última alteração contratual consolidada ou certidão simplificada (até 60 dias)",
             "note": "Limitada; para S/A, estatuto social atualizado e ata de eleição da diretoria vigente",
             "options": [["contrato_social"], ["certidao_simplificada"], ["estatuto_social", "ata_eleicao"]]},
            {"id": "balanco_anterior2", "stage": "analise", "group": "Informações financeiras",
             "label": "Balanço patrimonial e DRE {ano}", "any_of": ["balanco_dre"], "year_offset": -2,
             "note": "Assinado por representante legal e contador"},
            {"id": "balanco_anterior", "stage": "analise", "group": "Informações financeiras",
             "label": "Balanço patrimonial e DRE {ano}", "any_of": ["balanco_dre"], "year_offset": -1,
             "note": "Assinado por representante legal e contador"},
            {"id": "balancete", "stage": "analise", "group": "Informações financeiras",
             "label": "Balancete do exercício vigente ({ano})", "any_of": ["balancete"], "year_offset": 0,
             "note": "Assinado por representante legal e contador"},
            {"id": "faturamento_anterior2", "stage": "analise", "group": "Informações financeiras",
             "label": "Faturamento fechado de {ano}", "any_of": ["faturamento"], "year_offset": -2},
            {"id": "faturamento_anterior", "stage": "analise", "group": "Informações financeiras",
             "label": "Faturamento fechado de {ano}", "any_of": ["faturamento"], "year_offset": -1},
            {"id": "faturamento_atual", "stage": "analise", "group": "Informações financeiras",
             "label": "Faturamento {ano} (intervalo máximo de 2 meses)", "any_of": ["faturamento"], "year_offset": 0},
            {"id": "endividamento", "stage": "analise", "group": "Informações financeiras",
             "label": "Endividamento financeiro atualizado (até 90 dias)", "any_of": ["endividamento"]},
            {"id": "curva_abc", "stage": "analise", "group": "Informações financeiras",
             "label": "Curva ABC de clientes", "any_of": ["curva_abc"]},
            {"id": "irpf_anterior", "stage": "analise", "group": "Informações financeiras",
             "label": "IRPF {ano} dos sócios e/ou devedores solidários", "any_of": ["irpf"], "year_offset": -1, "per_partner": True},
            {"id": "irpf_atual", "stage": "analise", "group": "Informações financeiras",
             "label": "IRPF {ano} dos sócios e/ou devedores solidários", "any_of": ["irpf"], "year_offset": 0, "per_partner": True},
            {"id": "visita", "stage": "analise", "group": "Visita comercial",
             "label": "Relatório de visita comercial com registro fotográfico", "any_of": ["relatorio_visita"]},
            {"id": "identidade_socios", "stage": "formalizacao", "group": "Sócios, representantes e cônjuges",
             "label": "Documento de identificação dos sócios e/ou representantes (RG ou CNH)", "any_of": ["rg", "cin", "cnh"], "per_partner": True},
            {"id": "endereco", "stage": "formalizacao", "group": "Sócios, representantes e cônjuges",
             "label": "Comprovante de endereço (até 60 dias)", "note": "Da empresa e dos sócios/representantes legais",
             "any_of": ["comprovante_endereco"], "per_partner": True},
            {"id": "casamento", "stage": "formalizacao", "group": "Sócios, representantes e cônjuges", "required": False,
             "label": "Certidão de casamento ou de união estável", "note": "Se aplicável; divorciado(a) ou viúvo(a) com averbação",
             "any_of": ["certidao_casamento"]},
            {"id": "identidade_conjuge", "stage": "formalizacao", "group": "Sócios, representantes e cônjuges", "required": False,
             "label": "Documento de identificação do cônjuge (RG ou CNH)", "note": "Exceto em regime de separação total de bens",
             "any_of": ["rg", "cin", "cnh"]},
        ],
        "required_info": [
            {"id": "dados_bancarios", "stage": "formalizacao", "group": "Dados para a operação",
             "label": "Dados bancários da empresa", "hint": "Banco, agência e conta para recebimento das antecipações"},
            {"id": "responsavel_financeiro", "stage": "formalizacao", "group": "Dados para a operação",
             "label": "Responsável pelas operações financeiras", "hint": "Nome, telefone e e-mail"},
        ],
        "required_fields": [
            {"field": "cnpj", "label": "CNPJ legível", "in_any_of": ["cartao_cnpj", "contrato_social", "certidao_simplificada", "estatuto_social"]},
        ],
    },
    "PF": {
        "label": "Pessoa física",
        "tax_id_kind": "cpf",
        "required": [
            {"id": "identidade", "label": "Documento de identidade com foto", "any_of": ["rg", "cin", "cnh"]},
            {"id": "endereco", "label": "Comprovante de endereço (até 60 dias)", "any_of": ["comprovante_endereco"]},
        ],
        "required_fields": [
            {"field": "cpf", "label": "CPF legível em um documento", "in_any_of": ["rg", "cin", "cnh"]},
            {"field": "data_nascimento", "label": "Data de nascimento", "in_any_of": ["rg", "cin", "cnh"]},
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

# Pipeline statuses of portfolio clients, per modality, as the team used them in the previous dashboard.
# outcome: "approved" or "denied" closes the folder for the indicators (Apto a Operar / Negada);
# opens_signature: reaching it opens the contracts in Assinaturas.
CLIENT_STATUSES = {
    "normal": [
        {"key": "pasta_nova", "label": "Pasta Nova"},
        {"key": "aguardando_conferencia", "label": "Aguardando Conferência"},
        {"key": "aguardando_pre_comite", "label": "Aguardando Pré-Comitê"},
        {"key": "aguardando_comite", "label": "Aguardando Comitê"},
        {"key": "aguardando_documentacao", "label": "Aguardando Documentação"},
        {"key": "aguardando_assinatura", "label": "Aguardando Assinatura", "opens_signature": True},
        {"key": "apto_operar", "label": "Apto a Operar", "outcome": "approved"},
        {"key": "reanalise", "label": "Reanálise"},
        {"key": "negada", "label": "Negada", "outcome": "denied"},
    ],
    "one7": [
        {"key": "ag_documentos", "label": "Ag. Documentos"},
        {"key": "solicitar_docs", "label": "Solicitar Docs"},
        {"key": "cedente_bloqueado", "label": "Cedente Bloqueado"},
        {"key": "ag_comite", "label": "Ag. Comitê"},
        {"key": "apto_operar", "label": "Apto a Operar", "outcome": "approved"},
    ],
}

PORTFOLIO = {
    "sla_days": 7,  # days in the same status after which a folder counts as atrasada
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
    "client_statuses": CLIENT_STATUSES,
    "portfolio": PORTFOLIO,
}
