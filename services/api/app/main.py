import asyncio, uuid, json, logging, re, time
from pathlib import Path
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from .config import get_settings
from .auth import get_current_user, CurrentUser
from .models import ChatRequest, ChatResponse, UserResponse, DocumentResponse, TranscriptionResponse, MemoryRequest
from .db import db_execute, db_fetchall, db_fetchone, migrate_chunk_storage
from .llm import get_llm
from .rag import RAGService
from .storage import ObjectStorage
from .document import extract_salary_scale_markdown, extract_text, chunk_text
from .voice import transcribe_audio, synthesize_piper

logging.basicConfig(level=logging.INFO)
s=get_settings(); app=FastAPI(title=s.app_name, version='1.0.0')
allowed_origins=[s.web_origin]
if s.codespace_name and s.github_codespaces_port_forwarding_domain:
    allowed_origins.append(f'https://{s.codespace_name}-5173.{s.github_codespaces_port_forwarding_domain}')
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

rag=None; storage=None

def quick_reply(message: str) -> str | None:
    normalized=re.sub(r'\s+', ' ', re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9 ]", ' ', message.lower())).strip()
    greetings={"hi","hello","hey","bonjour","salut","bonsoir","good morning","good afternoon","good evening"}
    if normalized in greetings:
        return "Bonjour ! Comment puis-je vous aider ?"
    if normalized in {"merci","thanks","thank you"}:
        return "Avec plaisir !"
    if normalized in {"comment vas tu","comment allez vous","comment ça va","comment ca va","ca va","ça va","bien et toi","bien et vous"} or normalized.startswith(("ça va bien et toi", "ça va bien et vous", "ca va bien et toi", "ca va bien et vous")):
        return "Ça va bien, merci de demander. Comment puis-je vous aider ?"
    if normalized.startswith(("pourquoi prends tu autant de temps", "pourquoi prend tu autant de temps")):
        return "Désolé pour l’attente. Les recherches documentaires et la génération tournent localement sur CPU; les questions simples sont traitées directement et les réponses sourcées peuvent demander quelques secondes."
    if normalized in {"comment fonctionne cet assistant", "comment fonctionne l assistant", "how does this assistant work", "how does the assistant work"}:
        return "Je réponds à vos questions en m’appuyant sur les documents de référence disponibles. Je retrouve les passages pertinents, puis le modèle local formule une réponse. Si les sources ne suffisent pas, je vous le signale plutôt que d’inventer."
    return None

def is_document_catalog_request(message: str) -> bool:
    normalized=re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9 ]", "", message.lower()).strip()
    catalog_terms=('document', 'source', 'référence', 'reference')
    state_terms=('disponible', 'upload', 'charg', 'présent', 'present', 'que tu as', 'que vous avez', 'as tu', 'avez vous', 'ai je', 'avons nous')
    return any(term in normalized for term in catalog_terms) and any(term in normalized for term in state_terms)

def is_procedure_overview_request(message: str) -> bool:
    normalized=re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9 ]", "", message.lower()).strip()
    return 'procédur' in normalized and any(term in normalized for term in ('principal', 'disponible', 'liste', 'quels', 'quelles'))

def is_source_question(message: str) -> bool:
    normalized=re.sub(r'\s+', ' ', re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9 ]", ' ', message.lower())).strip()
    return any(phrase in normalized for phrase in (
        'sur quels documents', 'sur quelle source', 'quels documents utilises',
        'quelles sources utilises', 'sur quoi te bases', 'sur quoi vous basez',
        'tu te bases', 'vous vous basez', 'tes sources', 'vos sources',
    ))

def procedure_overview_reply(filename: str) -> str | None:
    normalized=filename.lower()
    if 'eneo' not in normalized and 'collective' not in normalized:
        return None
    return (
        'La seule source de référence indexée est la Convention Eneo 2023. '
        'Elle décrit principalement les règles concernant :\n\n'
        '- le temps de travail : horaires, heures supplémentaires, travail de nuit et télétravail ;\n'
        '- les congés, absences et jours fériés ;\n'
        '- les déplacements, transports et indemnités de mission ;\n'
        '- la classification, l’avancement et la promotion ;\n'
        '- les salaires, avances et retenues ;\n'
        '- la discipline et les sanctions.\n\n'
        'C’est une convention collective, pas un catalogue de procédures opérationnelles séparées.'
    )

def supports_catalog_intent(message: str) -> bool:
    normalized=message.lower()
    catalog_signals=('disponible', 'disponibles', 'chargé', 'chargés', 'chargées', 'chargées', 'upload', 'référence', 'reference', 'fichier', 'fichiers', 'liste', 'ressource', 'ressources')
    return any(signal in normalized for signal in catalog_signals)

def is_knowledge_question(message: str) -> bool:
    normalized=message.lower().strip()
    question_words=('qui', 'que', 'quoi', 'quel', 'quelle', 'quels', 'quelles', 'comment', 'pourquoi', 'où', 'quand', 'combien')
    action_words=('explique', 'décris', 'décrire', 'donne-moi', 'donne moi', 'liste', 'présente')
    return '?' in normalized or normalized.startswith(question_words) or normalized.startswith(action_words)

def is_contextual_follow_up(message: str) -> bool:
    normalized=re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9 ]", "", message.lower()).strip()
    return normalized.startswith(("et pour ", "et les ", "et la ", "et le ", "cette ", "ce ", "ces ", "cela ", "ça ", "qu en est il ", "concernant "))

def requests_salary_table(message: str) -> bool:
    normalized=message.lower()
    return any(term in normalized for term in ('grille salariale', 'grille de salaire', 'grille des salaires', 'grille de salaires', 'grille chiffr', 'salaire de base', 'salaires de base', 'basic salary', 'base salaries', 'salary scale'))
@app.on_event('startup')
async def startup():
    global rag,storage
    await migrate_chunk_storage()
    rag=RAGService(); storage=ObjectStorage()

async def ensure_user(user: CurrentUser):
    row=await db_fetchone('SELECT id FROM users WHERE external_id=:e',{'e':user.external_id})
    if not row:
        await db_execute('INSERT INTO users(external_id,name,email,department,role) VALUES(:e,:n,:m,:d,:r)',{'e':user.external_id,'n':user.name,'m':user.email,'d':user.department,'r':user.role})
    return await db_fetchone('SELECT id FROM users WHERE external_id=:e',{'e':user.external_id})

@app.get('/api/v1/health')
async def health(): return {'status':'ok','service':'enterprise-ai','llm_mode':s.llm_mode}

@app.get('/api/v1/me',response_model=UserResponse)
async def me(user: CurrentUser=Depends(get_current_user)):
    await ensure_user(user); return UserResponse(external_id=user.external_id,name=user.name,email=user.email,role=user.role,department=user.department)

@app.get('/api/v1/conversations')
async def conversations(user: CurrentUser=Depends(get_current_user)):
    u=await ensure_user(user)
    rows=await db_fetchall('SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=:u ORDER BY updated_at DESC',{'u':u['id']})
    return [dict(r) for r in rows]

@app.get('/api/v1/conversations/{conversation_id}')
async def conversation(conversation_id:str,user:CurrentUser=Depends(get_current_user)):
    u=await ensure_user(user)
    rows=await db_fetchall('''SELECT m.id,m.role,m.content,m.metadata,m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.id=:c AND c.user_id=:u ORDER BY m.created_at''',{'c':conversation_id,'u':u['id']})
    return [dict(r) for r in rows]

@app.post('/api/v1/chat',response_model=ChatResponse)
async def chat(req:ChatRequest,user:CurrentUser=Depends(get_current_user)):
    request_started=time.perf_counter()
    rag_seconds=0.0
    llm_seconds=0.0
    u=await ensure_user(user)
    cid=req.conversation_id
    if cid:
        conv=await db_fetchone('SELECT id FROM conversations WHERE id=:c AND user_id=:u',{'c':cid,'u':u['id']})
        if not conv: raise HTTPException(404,'Conversation not found')
    else:
        cid=str(uuid.uuid4()); await db_execute('INSERT INTO conversations(id,user_id,title) VALUES(:id,:u,:t)',{'id':cid,'u':u['id'],'t':req.message[:80]})
    history=await db_fetchall('SELECT role,content FROM messages WHERE conversation_id=:c ORDER BY created_at DESC LIMIT :lim',{'c':cid,'lim:s':s.max_history_messages} if False else {'c':cid,'lim':s.max_history_messages})
    history=list(reversed([{'role':x['role'],'content':x['content']} for x in history]))
    citations=[]; context=''; cited_documents=set(); retrieved_chunks=[]
    answer=quick_reply(req.message)
    catalog_request=is_document_catalog_request(req.message)
    procedure_overview=is_procedure_overview_request(req.message)
    source_question=is_source_question(req.message)
    direct_knowledge=is_knowledge_question(req.message)
    if answer is None and source_question:
        rows=await db_fetchall("SELECT id,filename,status FROM documents WHERE metadata->>'owner'=:owner ORDER BY created_at DESC",{'owner':user.external_id})
        if rows:
            filenames=', '.join(row['filename'] for row in rows)
            answer=f"Je me base sur les documents de référence suivants : {filenames}."
            citations=[{'document_id':str(row['id']),'filename':row['filename'],'chunk_index':0,'score':1.0} for row in rows]
        else:
            answer='Aucun document de référence n’est indexé pour votre compte.'
    if answer is None and procedure_overview:
        rows=await db_fetchall("SELECT id,filename,status FROM documents WHERE metadata->>'owner'=:owner ORDER BY created_at DESC",{'owner':user.external_id})
        if rows:
            source=next((row for row in rows if procedure_overview_reply(row['filename'])),None)
            if source:
                answer=procedure_overview_reply(source['filename'])
                citations=[{'document_id':str(source['id']),'filename':source['filename'],'chunk_index':0,'score':1.0}]
            else:
                answer='Documents de référence disponibles :\n\n'+'\n'.join(f"- {row['filename']} ({row['status']})" for row in rows)+'\n\nPrécisez le document ou le sujet pour que je puisse cibler les procédures concernées.'
        else:
            answer='Aucun document de procédure n’est indexé pour le moment.'
    salary_table=requests_salary_table(req.message)
    if answer is None and catalog_request:
        rows=await db_fetchall("SELECT filename,status FROM documents WHERE metadata->>'owner'=:owner ORDER BY created_at DESC",{'owner':user.external_id})
        if rows:
            answer='Documents sources disponibles :\n\n'+'\n'.join(f"- {row['filename']} ({row['status']})" for row in rows)
        else:
            answer='Aucun document source n’est disponible pour le moment.'
    search_knowledge=answer is None and req.use_knowledge and direct_knowledge
    if search_knowledge:
        try:
            retrieval_limit=1 if any(term in req.message.lower() for term in ('grille', 'salaire', 'salary', 'wage')) else s.max_context_chunks
            retrieval_query=req.message
            if is_contextual_follow_up(req.message):
                previous_question=next((item['content'] for item in reversed(history) if item['role']=='user'),None)
                if previous_question:
                    retrieval_query=f'{previous_question[:300]} {req.message}'
            retrieval_limit=1 if any(term in retrieval_query.lower() for term in ('grille', 'salaire', 'salary', 'wage')) else retrieval_limit
            rag_started=time.perf_counter()
            hits=await asyncio.to_thread(rag.search,retrieval_query,user.external_id,retrieval_limit)
            rag_seconds=time.perf_counter()-rag_started
            for h in hits:
                p=h.payload or {}; retrieved_chunks.append(p); document_key=p.get('document_id') or p.get('filename','')
                if document_key not in cited_documents:
                    cited_documents.add(document_key)
                    citations.append({'document_id':p.get('document_id',''),'filename':p.get('filename',''),'chunk_index':p.get('chunk_index',0),'score':float(getattr(h,'score',0.0) or 0.0)})
            context_limit=2200 if salary_table else 800
            context_parts=[]
            for p in [h.payload or {} for h in hits]:
                raw_content=str(p.get('content',''))
                content=raw_content if salary_table else ' '.join(raw_content.split())
                if salary_table:
                    marker=content.lower().find('appendix 3 salary scale')
                    if marker >= 0:
                        content=content[marker:]
                context_parts.append(f"[Source: {p.get('filename')} / chunk {p.get('chunk_index')}]\n{content[:context_limit]}")
            context='\n\n'.join(context_parts)
        except Exception as e: logging.warning('RAG unavailable: %s',e)
    if salary_table and retrieved_chunks:
        document_id=retrieved_chunks[0].get('document_id')
        document_row=await db_fetchone('SELECT object_key FROM documents WHERE id=:d',{'d':document_id}) if document_id else None
        if document_row:
            try:
                structured_table=extract_salary_scale_markdown(storage.get(document_row['object_key']))
            except Exception as e:
                logging.warning('Salary table extraction unavailable: %s',e)
                structured_table=None
            if structured_table:
                answer='Voici la grille salariale extraite de l’Appendice 3 :\n\n'+structured_table
    if salary_table and answer is None:
        answer='J’ai trouvé la convention Eneo, mais sa page de grille salariale est trop dégradée par l’OCR pour transcrire les montants sans risque d’erreur. Je préfère ne pas présenter de chiffres inexacts.'
    system='''You are Enterprise AI, a sovereign internal employee assistant. Answer clearly and safely. Never invent company policy. In this knowledge base, SOCADEL is the new name of former ENEO; treat both names as the same organization. If knowledge sources are provided, prioritize them. Answer in the language of the user's latest message: French for French questions, English for English questions. Use the conversation history to resolve follow-ups such as "cette grille" or "this scale". For broad summary questions, give at most 3 numbered items, with each description limited to 12 words. End every sentence completely. Do not include a source list or repeat document filenames in your answer; the interface displays sources separately. If evidence is insufficient, say so. Do not expose confidential information outside the user's authorized context.'''
    if requests_salary_table(req.message):
        system += '\nFor a salary-scale request, use only the APPENDIX 3 SALARY SCALE section, never the job classification matrix. Reproduce the actual category columns A through G as a Markdown table with columns Echelon, A, B, C, D, E, F, G. Preserve source values exactly and do not invent missing values; say the scan is unreadable if the OCR cannot establish a cell.'
    if context: system += '\n\nEnterprise knowledge:\n'+context
    if answer is None:
        messages=[{'role':'system','content':system}]+history+[{'role':'user','content':req.message}]
        try:
            llm_started=time.perf_counter()
            answer=await asyncio.wait_for(get_llm().chat(messages), timeout=min(s.chat_timeout_seconds, 45.0))
            llm_seconds=time.perf_counter()-llm_started
        except Exception as e:
            llm_seconds=time.perf_counter()-llm_started
            logging.info('chat timing route=llm-failed rag_ms=%d llm_ms=%d total_ms=%d',int(rag_seconds*1000),int(llm_seconds*1000),int((time.perf_counter()-request_started)*1000))
            if isinstance(e, asyncio.TimeoutError) and retrieved_chunks:
                answer='Je n’ai pas pu produire une réponse fiable dans le délai imparti. Veuillez réessayer.'
            else:
                logging.exception('LLM request failed')
                raise HTTPException(503, f'Le modèle est indisponible ou n’a pas répondu à temps: {e}')
    mid=str(uuid.uuid4())
    await db_execute('INSERT INTO messages(id,conversation_id,role,content,metadata) VALUES(:id,:c,:r,:x,:m)',{'id':str(uuid.uuid4()),'c':cid,'r':'user','x':req.message,'m':'{}'})
    await db_execute('INSERT INTO messages(id,conversation_id,role,content,metadata) VALUES(:id,:c,:r,:x,:m)',{'id':mid,'c':cid,'r':'assistant','x':answer,'m':json.dumps({'citations':citations},default=str)})
    await db_execute('UPDATE conversations SET updated_at=now() WHERE id=:c',{'c':cid})
    await db_execute('INSERT INTO audit_logs(user_external_id,action,resource,metadata) VALUES(:u,:a,:r,:m)',{'u':user.external_id,'a':'chat','r':cid,'m':json.dumps({'voice_response':req.voice_response})})
    route='rag+llm' if rag_seconds and llm_seconds else 'rag' if rag_seconds else 'fast' if answer is not None else 'llm'
    logging.info('chat timing route=%s rag_ms=%d llm_ms=%d total_ms=%d',route,int(rag_seconds*1000),int(llm_seconds*1000),int((time.perf_counter()-request_started)*1000))
    return ChatResponse(conversation_id=cid,message_id=mid,answer=answer,citations=citations,metadata={'voice_available':s.tts_enabled})

@app.post('/api/v1/documents',response_model=DocumentResponse)
async def upload_document(file:UploadFile=File(...),user:CurrentUser=Depends(get_current_user)):
    filename=Path((file.filename or '').replace('\\','/')).name
    if Path(filename).suffix.lower() not in {'.pdf','.docx','.txt','.md','.csv','.json','.xml','.html'}:
        raise HTTPException(415,'Unsupported document type')
    data=await file.read(s.max_upload_mb*1024*1024+1)
    if len(data)>s.max_upload_mb*1024*1024: raise HTTPException(413,'File too large')
    doc_id=str(uuid.uuid4()); key=f'{user.external_id}/{doc_id}/{filename}'
    stored=False; document_created=False
    try:
        text=extract_text(filename,data); chunks=chunk_text(text)
        storage.put(key,data,file.content_type or 'application/octet-stream'); stored=True
        vector_ids=rag.index_chunks(doc_id,filename,chunks,{'owner':user.external_id}) if chunks else []
        await db_execute('INSERT INTO documents(id,filename,object_key,mime_type,size_bytes,status,metadata) VALUES(:id,:f,:o,:m,:s,:st,:md)',{'id':doc_id,'f':filename,'o':key,'m':file.content_type,'s':len(data),'st':'indexed','md':json.dumps({'owner':user.external_id,'chunks':len(chunks)})})
        document_created=True
        if vector_ids:
            await db_execute('INSERT INTO document_chunks(document_id,chunk_index,vector_id) VALUES(:d,:i,:v)',[{'d':doc_id,'i':i,'v':vid} for i,vid in enumerate(vector_ids)])
        return DocumentResponse(id=doc_id,filename=filename,status='indexed',size_bytes=len(data))
    except Exception:
        logging.exception('document indexing failed')
        try: rag.delete_document(doc_id)
        except Exception: logging.warning('failed to clean up document vectors')
        if document_created:
            try: await db_execute('DELETE FROM documents WHERE id=:d',{'d':doc_id})
            except Exception: logging.warning('failed to clean up document record')
        if stored:
            try: storage.delete(key)
            except Exception: logging.warning('failed to clean up uploaded object')
        raise HTTPException(500,'Document indexing failed')

@app.get('/api/v1/documents',response_model=list[DocumentResponse])
async def documents(user:CurrentUser=Depends(get_current_user)):
    rows=await db_fetchall("SELECT id,filename,status,size_bytes FROM documents WHERE metadata->>'owner'=:owner ORDER BY created_at DESC",{'owner':user.external_id})
    return [DocumentResponse(id=str(r['id']),filename=r['filename'],status=r['status'],size_bytes=r['size_bytes']) for r in rows]

@app.post('/api/v1/memory')
async def add_memory(req:MemoryRequest,user:CurrentUser=Depends(get_current_user)):
    u=await ensure_user(user)
    mid=str(uuid.uuid4()); await db_execute('INSERT INTO memories(id,user_id,kind,content) VALUES(:id,:u,:k,:c)',{'id':mid,'u':u['id'],'k':req.kind,'c':req.content})
    return {'id':mid,'status':'stored'}

@app.get('/api/v1/memory')
async def list_memory(user:CurrentUser=Depends(get_current_user)):
    u=await ensure_user(user); rows=await db_fetchall('SELECT id,kind,content,created_at FROM memories WHERE user_id=:u ORDER BY created_at DESC',{'u':u['id']}); return [dict(r) for r in rows]

@app.post('/api/v1/voice/transcribe',response_model=TranscriptionResponse)
async def voice_transcribe(file:UploadFile=File(...),user:CurrentUser=Depends(get_current_user)):
    data=await file.read(s.max_upload_mb*1024*1024+1)
    if len(data)>s.max_upload_mb*1024*1024: raise HTTPException(413,'File too large')
    text,lang=transcribe_audio(data,Path(file.filename or 'audio.webm').suffix or '.webm'); return TranscriptionResponse(text=text,language=lang)

@app.post('/api/v1/voice/synthesize')
async def voice_synthesize(payload:dict,user:CurrentUser=Depends(get_current_user)):
    text=payload.get('text','')
    if not text: raise HTTPException(400,'text is required')
    try: audio=synthesize_piper(text)
    except RuntimeError as e: raise HTTPException(503,str(e))
    return Response(content=audio,media_type='audio/wav')
