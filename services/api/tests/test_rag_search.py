import logging
from types import SimpleNamespace
from unittest.mock import Mock

from app.rag import RAGService


def test_search_filters_by_owner_and_logs_stage_timings(caplog):
    point = SimpleNamespace(id='point-1', payload={'content': 'travel policy'}, score=0.9)
    service = object.__new__(RAGService)
    service.s = SimpleNamespace(qdrant_collection='documents')
    service.client = Mock()
    service.client.query_points.return_value = SimpleNamespace(points=[point])
    service.embed = Mock(return_value=[[0.1, 0.2]])

    with caplog.at_level(logging.INFO):
        result = service.search('travel policy', owner='employee-1', limit=2)

    query = service.client.query_points.call_args.kwargs
    assert query['limit'] == 24
    assert query['query_filter'].must[0].key == 'owner'
    assert query['query_filter'].must[0].match.value == 'employee-1'
    service.client.scroll.assert_not_called()
    assert result == [point]
    assert 'rag timing embedding_ms=' in caplog.text
    assert 'qdrant_ms=' in caplog.text
    assert 'rerank_ms=' in caplog.text


def test_repeated_query_reuses_cached_embedding():
    point = SimpleNamespace(id='point-1', payload={'content': 'travel policy'}, score=0.9)
    service = object.__new__(RAGService)
    service.s = SimpleNamespace(qdrant_collection='documents')
    service.client = Mock()
    service.client.query_points.return_value = SimpleNamespace(points=[point])
    service.embed = Mock(return_value=[[0.1, 0.2]])

    service.search('Travel   policy', owner='employee-1', limit=2)
    service.search('travel policy', owner='employee-1', limit=2)

    service.embed.assert_called_once_with(['query: travel policy'])