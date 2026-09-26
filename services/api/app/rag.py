import uuid
import re
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
        self._ensure_collection()

    def _ensure_collection(self):
        try: self.client.get_collection(self.s.qdrant_collection)
        except Exception:
            self.client.create_collection(self.s.qdrant_collection, vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE))
        self.client.create_payload_index(collection_name=self.s.qdrant_collection, field_name='owner', field_schema=models.PayloadSchemaType.KEYWORD, wait=True)

    def embed(self, texts):
        return self.embedder.encode(texts, normalize_embeddings=True).tolist()

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
        vec=self.embed([f"query: {query}"])[0]
        owner_filter=models.Filter(must=[models.FieldCondition(key='owner',match=models.MatchValue(value=owner))])
        candidate_limit=max(limit*8,32)
        result=self.client.query_points(collection_name=self.s.qdrant_collection, query=vec, query_filter=owner_filter, limit=candidate_limit, with_payload=True)
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
            return semantic_points[:limit]
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
        return merged
