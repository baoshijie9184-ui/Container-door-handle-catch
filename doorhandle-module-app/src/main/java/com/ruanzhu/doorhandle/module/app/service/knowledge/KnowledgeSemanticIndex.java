package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.framework.semantic.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/** Derived current-version index. MySQL retains the source, lifecycle and authorization authority. */
@Service
@ConditionalOnProperty(prefix="app.knowledge",name="enabled",havingValue="true")
public final class KnowledgeSemanticIndex {
    private final JdbcTemplate jdbc;
    private final SemanticVectorStore vectors;
    private final SemanticProperties properties;
    private final JdbcSemanticIndexState states;
    private final AtomicBoolean indexing=new AtomicBoolean();
    public KnowledgeSemanticIndex(JdbcTemplate jdbc,SemanticVectorStore vectors,SemanticProperties properties,JdbcSemanticIndexState states) {
        this.jdbc=jdbc;this.vectors=vectors;this.properties=properties;this.states=states;
    }
    private static String text(Map<String,Object> row,String name){return Objects.toString(row.get(name),"");}
    /** Called by the ordinary scheduler, outside content write transactions; retries persist across restarts. */
    @Scheduled(fixedDelayString="${app.semantic.reconcile-delay-ms:30000}",initialDelayString="${app.semantic.reconcile-initial-delay-ms:30000}")
    public void reconcile() {
        if(!properties.isEnabled()||!indexing.compareAndSet(false,true))return;
        try {
            var pending=jdbc.queryForList("SELECT d.asset_id,d.owner_user_id,d.visibility,d.current_version,r.content_sha256 FROM content_asset d JOIN content_revision r ON r.asset_id=d.asset_id AND r.version=d.current_version AND r.asset_kind='KNOWLEDGE' LEFT JOIN runtime_state s ON s.namespace='SEMANTIC_INDEX' AND s.owner_id=d.owner_user_id AND s.scope_key=CONCAT('KNOWLEDGE:',d.asset_id) WHERE d.asset_kind='KNOWLEDGE' AND d.lifecycle='ACTIVE' ORDER BY COALESCE(s.updated_at,r.created_at),r.id LIMIT 4");
            for(var source:pending)try{index(source);}catch(SemanticUnavailableException changed){/* A changed source is retried from its new pointer, never completed from this snapshot. */}
        } finally {indexing.set(false);}
    }
    private String generation(){return properties.getStorageGeneration()+"/"+properties.getProfile()+"/"+properties.getModel()+"/"+properties.getDimensions()+"/"+properties.getPreprocessing();}
    private JdbcSemanticIndexState.Source source(Map<String,Object> row){return new JdbcSemanticIndexState.Source("KNOWLEDGE",((Number)row.get("owner_user_id")).longValue(),text(row,"asset_id"),((Number)row.get("current_version")).intValue(),text(row,"content_sha256"),text(row,"visibility"));}
    boolean currentSource(JdbcSemanticIndexState.Source expected){
        com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions.requireActive(jdbc);
        if(!"KNOWLEDGE".equals(expected.kind()))return false;
        var rows=jdbc.queryForList("SELECT d.owner_user_id,d.current_version,d.lifecycle,d.visibility,r.content_sha256 FROM content_asset d JOIN content_revision r ON r.asset_id=d.asset_id AND r.asset_kind='KNOWLEDGE' AND r.version=d.current_version WHERE d.asset_kind='KNOWLEDGE' AND d.asset_id=? FOR UPDATE",expected.id());
        if(rows.size()!=1)return false;var row=rows.get(0);
        return ((Number)row.get("owner_user_id")).longValue()==expected.owner()&&((Number)row.get("current_version")).intValue()==expected.version()
                &&"ACTIVE".equals(row.get("lifecycle"))&&expected.scope().equals(row.get("visibility"))&&expected.contentSha256().equals(row.get("content_sha256"));
    }
    private void index(Map<String,Object> source) {
        String id=text(source,"asset_id");int version=((Number)source.get("current_version")).intValue();
        var ticket=states.claim(source(source),properties.getKnowledgeCollection(),this::currentSource);
        var chunks=jdbc.queryForList("SELECT ordinal_no,content_text FROM content_chunk WHERE asset_id=? AND version=? ORDER BY ordinal_no",id,version);
        var documents=new ArrayList<SemanticVectorStore.Document>();
        for(var chunk:chunks) {
            var parts=SemanticDocuments.split(text(chunk,"content_text"));
            for(int part=0;part<parts.size();part++)documents.add(new SemanticVectorStore.Document(id+"@v"+version+":"+chunk.get("ordinal_no")+":"+part,parts.get(part),
                    Map.of("kind","KNOWLEDGE","source_id",id,"owner",text(source,"owner_user_id"),"visibility",text(source,"visibility"),
                            "version",String.valueOf(version),"ordinal",text(chunk,"ordinal_no"),"part",String.valueOf(part),"source_sha256",text(source,"content_sha256"),"generation",generation(),"lifecycle","ACTIVE")));
        }
        if(documents.isEmpty()){states.finish(ticket,false,this::currentSource);return;}
        String state="READY";
        try {
            if(!documents.isEmpty()) {
                boolean current=false;try{current=vectors.contains(properties.getKnowledgeCollection(),documents);}catch(SemanticUnavailableException unavailable){/* Missing/unavailable never counts as readiness. */}
                if(ticket.ready()&&!current)ticket=states.reopen(ticket,this::currentSource);
                if(!current)vectors.upsert(properties.getKnowledgeCollection(),documents,new EmbeddingClient.RequestContext("KNOWLEDGE","doorhandlecatch:user:"+source.get("owner_user_id")));
            }
        }catch(RuntimeException unavailable){state="FAILED";}
        // A CAS ticket cannot complete a newer content/model/scope projection.
        states.finish(ticket,"READY".equals(state),this::currentSource);
    }
    public String state(long owner,String id,int version,String hash,String visibility){return !properties.isEnabled()?"DISABLED":states.state(new JdbcSemanticIndexState.Source("KNOWLEDGE",owner,id,version,hash,visibility),properties.getKnowledgeCollection(),this::currentSource);}
    public void invalidate(long owner,String id){states.invalidate("KNOWLEDGE",owner,id);}
    private boolean matchesPart(String source,SemanticVectorStore.Hit hit){
        String value=hit.metadata().getOrDefault("part","0");if(!value.matches("0|[1-9][0-9]{0,4}"))return false;
        var parts=SemanticDocuments.split(source);int part=Integer.parseInt(value);return part<parts.size()&&parts.get(part).equals(hit.text());
    }
    /** Candidates are prefiltered in Qdrant and reloaded from current authorized MySQL chunks. */
    public List<Map<String,Object>> search(Identity actor,String query) {
        if(!properties.isEnabled())throw new SemanticUnavailableException("VECTOR_DISABLED");
        var filter=new SemanticVectorStore.Filter(Map.of("kind","KNOWLEDGE","lifecycle","ACTIVE","generation",generation()),
                List.of(Map.of("owner",String.valueOf(actor.userId())),Map.of("visibility","ENTERPRISE")));
        var hits=vectors.search(properties.getKnowledgeCollection(),query,filter,30,new EmbeddingClient.RequestContext("KNOWLEDGE","doorhandlecatch:user:"+actor.userId()));
        var result=new ArrayList<Map<String,Object>>();var seen=new HashSet<String>();
        for(var hit:hits) {
            var meta=hit.metadata();String id=meta.get("source_id"),version=meta.get("version"),ordinal=meta.get("ordinal");
            if(id==null||version==null||ordinal==null||!version.matches("[1-9][0-9]{0,8}")||!ordinal.matches("[1-9][0-9]{0,8}")||!seen.add(id+"/"+version+"/"+ordinal))continue;
            var current=jdbc.queryForList("SELECT d.asset_id AS document_id,d.owner_user_id,d.visibility,d.title,d.current_version,c.ordinal_no,c.locator,c.content_text,r.content_sha256 FROM content_asset d JOIN content_revision r ON r.asset_id=d.asset_id AND r.version=d.current_version AND r.asset_kind='KNOWLEDGE' JOIN content_chunk c ON c.asset_id=d.asset_id AND c.version=d.current_version WHERE d.asset_kind='KNOWLEDGE' AND d.asset_id=? AND d.lifecycle='ACTIVE' AND d.current_version=? AND c.ordinal_no=? AND (d.owner_user_id=? OR d.visibility='ENTERPRISE')",id,Integer.parseInt(version),Integer.parseInt(ordinal),actor.userId());
            if(current.size()==1&&Objects.equals(current.get(0).get("content_sha256"),meta.get("source_sha256"))&&matchesPart(current.get(0).get("content_text").toString(),hit)
                    &&"READY".equals(state(((Number)current.get(0).get("owner_user_id")).longValue(),id,Integer.parseInt(version),meta.get("source_sha256"),current.get(0).get("visibility").toString()))) {
                var row=current.get(0);row.remove("content_sha256");row.remove("owner_user_id");row.remove("visibility");row.put("retrieval_mode","SEMANTIC");result.add(row);
            }
            if(result.size()==6)break;
        }
        return List.copyOf(result);
    }
}
