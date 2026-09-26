from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from app import main
from app.auth import CurrentUser, get_current_user
from app.main import (
    is_document_catalog_request,
    is_procedure_overview_request,
    procedure_overview_reply,
    quick_reply,
    requests_salary_table,
)


def test_assistant_overview_uses_fast_reply():
    answer = quick_reply('Comment fonctionne cet assistant ?')

    assert answer is not None
    assert 'documents de référence' in answer


def test_reference_document_question_uses_catalog_route():
    assert is_document_catalog_request('Quels sont les documents de référence que tu as ?')


def test_eneos_salary_scale_question_is_recognized():
    assert requests_salary_table('Quelle est la grille salariale à ENEO ?')


def test_procedure_overview_uses_fast_grounded_response():
    question = 'Quelles sont les principales procédures disponibles ?'

    assert is_procedure_overview_request(question)
    answer = procedure_overview_reply('Convention Eneo 2023 OCR.pdf')
    assert answer is not None
    assert 'heures supplémentaires' in answer
    assert 'pas un catalogue de procédures opérationnelles séparées' in answer


def test_procedure_chat_uses_database_answer_without_rag_or_llm(monkeypatch):
    monkeypatch.setattr(main, 'ensure_user', AsyncMock(return_value={'id': 'db-user'}))
    monkeypatch.setattr(main, 'db_fetchall', AsyncMock(side_effect=[
        [],
        [{'id': 'doc-1', 'filename': 'Convention Eneo 2023 OCR.pdf', 'status': 'indexed'}],
    ]))
    monkeypatch.setattr(main, 'db_execute', AsyncMock())
    monkeypatch.setattr(main, 'get_llm', Mock(side_effect=AssertionError('LLM should not run')))
    main.app.dependency_overrides[get_current_user] = lambda: CurrentUser('employee-1', 'Test', 'test@example.com')

    try:
        response = TestClient(main.app).post('/api/v1/chat', json={
            'message': 'Quelles sont les principales procédures disponibles ?',
            'use_knowledge': True,
        })
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert 'heures supplémentaires' in response.json()['answer']
    assert response.json()['citations'][0]['filename'] == 'Convention Eneo 2023 OCR.pdf'