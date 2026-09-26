import uuid
import re
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from .config import get_settings

class RAGService:
    def __init__(self):
        s=get_settings(); self.s=s
        self.client=QdrantClient(url=s.qdrant_url)
        self.embedder=SentenceTransformer(s.embedding_model)
        self.dim=self.embedder.get_sentence_embedding_dimension()
        self._query_embedding_cache=OrderedDict()
        self._query_embedding_lock=threading.Lock()
        self._ensure_collection()

    def _ensure_collection(self):
        try: self.client.get_collection(self.s.qdrant_collection)
        except Exception:
            self.client.create_collection(self.s.qdrant_collection, vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE))
        self.client.create_payload_index(collection_name=self.s.qdrant_collection, field_name='owner', field_schema=models.PayloadSchemaType.KEYWORD, wait=True)

    def embed(self, texts):
        return self.embedder.encode(texts, normalize_embeddings=True).tolist()

    def _query_embedding(self, query):
        normalized_query=' '.join(query.casefold().split())
        cache=getattr(self,'_query_embedding_cache',None)
        if cache is None:
            cache=self._query_embedding_cache=OrderedDict()
            self._query_embedding_lock=threading.Lock()
        with self._query_embedding_lock:
            vector=cache.get(normalized_query)
            if vector is not None:
                cache.move_to_end(normalized_query)
                return list(vector)
            vector=tuple(self.embed([f"query: {normalized_query}"])[0])
            cache[normalized_query]=vector
            if len(cache)>256:
                cache.popitem(last=False)
            return list(vector)

    def index_chunks(self, document_id, filename, chunks, metadata=None):
        vectors=self.embed([f"passage: {x}" for x in chunks])
        points=[]
        for i,(chunk,vec) in enumerate(zip(chunks,vectors)):
            vid=str(uuid.uuid4())
            payload={"document_id":document_id,"filename":filename,"chunk_index":i,"content":chunk,**(metadata or {})}
            points.append(models.PointStruct(id=vid,vector=vec,payload=payload))
        self.client.upsert(self.s.qdrant_collection, points=points)
        return [str(p.id) for p in points]

    def delete_document(self, document_id):
        selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key='document_id',match=models.MatchValue(value=document_id))]))
        self.client.delete(collection_name=self.s.qdrant_collection, points_selector=selector, wait=True)

    def search(self, query, owner, limit=6):
        embedding_started=time.perf_counter()
        vec=self._query_embedding(query)
        embedding_seconds=time.perf_counter()-embedding_started
        owner_filter=models.Filter(must=[models.FieldCondition(key='owner',match=models.MatchValue(value=owner))])
        candidate_limit=max(limit*4,24)
        qdrant_started=time.perf_counter()
        result=self.client.query_points(collection_name=self.s.qdrant_collection, query=vec, query_filter=owner_filter, limit=candidate_limit, with_payload=True)
        qdrant_seconds=time.perf_counter()-qdrant_started
        semantic_points=result.points
        terms={term for term in re.findall(r"[a-zàâçéèêëîïôûùüÿñæœ0-9]+", query.lower()) if len(term)>3}
        aliases={
            'socadel': {'eneo'},
            'eneo': {'socadel'},
            'salaire': {'salary','salaries','wage','wages','remuneration'},
            'salaires': {'salary','salaries','wage','wages','remuneration'},
            'grille': {'scale','classification','matrix'},
            'grilles': {'scale','classification','matrix'},
            'rémunération': {'salary','wage','remuneration'},
            'remuneration': {'salary','wage','remuneration'},
        }
        for term in list(terms): terms.update(aliases.get(term,set()))
        terms-= {'donne','donner','moi','pour','avec','dans','cette','quels','quelle'}
        salary_query=any(term in query.lower() for term in ('grille', 'salaire', 'salary', 'salaries', 'wage', 'remuneration'))
        if not terms:
            selected=semantic_points[:limit]
            logging.info('rag timing embedding_ms=%d qdrant_ms=%d rerank_ms=0 candidates=%d returned=%d',int(embedding_seconds*1000),int(qdrant_seconds*1000),len(semantic_points),len(selected))
            return selected
        rerank_started=time.perf_counter()
        ranked=[]
        priority=[]
        for point in semantic_points:
            content=' '.join(str((point.payload or {}).get('content','')).lower().split())
            filename=str((point.payload or {}).get('filename','')).lower()
            matches=sum(1 for term in terms if term in content or term in filename)
            if salary_query and ('salary scale' in content or 'appendix 3' in content or 'grille' in content):
                matches+=5
                priority.append(point)
            if matches: ranked.append((matches,point))
        ranked.sort(key=lambda item:item[0],reverse=True)
        merged=[]; seen=set()
        priority.sort(key=lambda point: (
            'appendix 3' in ' '.join(str((point.payload or {}).get('content','')).lower().split()),
            'salary scale' in ' '.join(str((point.payload or {}).get('content','')).lower().split()),
        ), reverse=True)
        ordered=priority+[item[1] for item in ranked]+semantic_points
        for point in ordered:
            point_id=str(point.id)
            if point_id not in seen:
                seen.add(point_id); merged.append(point)
            if len(merged)>=limit: break
        logging.info('rag timing embedding_ms=%d qdrant_ms=%d rerank_ms=%d candidates=%d returned=%d',int(embedding_seconds*1000),int(qdrant_seconds*1000),int((time.perf_counter()-rerank_started)*1000),len(semantic_points),len(merged))
        return merged
