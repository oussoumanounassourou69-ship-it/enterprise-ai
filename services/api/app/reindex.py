import asyncio
import json
from datetime import datetime, timezone

from .db import db_execute, db_fetchall, migrate_chunk_storage
from .document import chunk_text, extract_text
from .rag import RAGService
from .storage import ObjectStorage

def read_metadata(value):
    return value if isinstance(value, dict) else json.loads(value or '{}')

async def reindex_documents():
    await migrate_chunk_storage()
    rows=await db_fetchall('SELECT id,filename,object_key,metadata FROM documents ORDER BY created_at')
    storage=ObjectStorage()
    rag=RAGService()
    for row in rows:
        document_id=str(row['id'])
        data=storage.get(row['object_key'])
        chunks=chunk_text(extract_text(row['filename'],data))
        rag.delete_document(document_id)
        metadata=read_metadata(row['metadata'])
        vector_ids=rag.index_chunks(document_id,row['filename'],chunks,metadata) if chunks else []
        await db_execute('DELETE FROM document_chunks WHERE document_id=:d',{'d':document_id})
        if vector_ids:
            await db_execute('INSERT INTO document_chunks(document_id,chunk_index,vector_id) VALUES(:d,:i,:v)',[{'d':document_id,'i':index,'v':vector_id} for index,vector_id in enumerate(vector_ids)])
        metadata.update({'chunks':len(chunks),'reindexed_at':datetime.now(timezone.utc).isoformat(),'layout_preserved':True})
        await db_execute('UPDATE documents SET status=:s,metadata=CAST(:m AS jsonb) WHERE id=:d',{'s':'indexed','m':json.dumps(metadata),'d':document_id})
        print(f'{row["filename"]}: {len(chunks)} chunks')


if __name__ == '__main__':
    asyncio.run(reindex_documents())