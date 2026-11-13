package com.ruanzhu.doorhandle.framework.semantic;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Typed, CAS-protected derived-index projection in the existing runtime_state table. */
@Component
public final class JdbcSemanticIndexState {
    public static final String NAMESPACE="SEMANTIC_INDEX";
    public record Source(String kind,long owner,String id,int version,String contentSha256,String scope) {
        public Source {
            if(!Set.of("KNOWLEDGE","EXPERIENCE").contains(kind)||owner<=0||id==null||!id.matches("[A-Za-z0-9_-]{1,128}")
                    ||version<=0||contentSha256==null||!contentSha256.matches("[a-f0-9]{64}")||scope==null||scope.length()>100)
                throw new IllegalArgumentException("Invalid derived index source");
        }
        public String key(){return kind+":"+id;}
        public String reference(){return id+"@v"+version;}
    }
    public record Body(int protocolVersion,String kind,String sourceId,int sourceVersion,String contentSha256,
                       String scope,String collection,String profile,String model,int dimensions,
                       String preprocessing,String storageGeneration) { }
    public record Ticket(Source source,String collection,long revision,Body body,boolean ready) { }
    /** The domain owner locks/checks its current source inside the same short SQL transaction. */
    @FunctionalInterface public interface SourceFence { boolean current(Source expected); }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final SemanticProperties properties;
    private final TransactionTemplate transaction;
    public JdbcSemanticIndexState(JdbcTemplate jdbc,ObjectMapper json,SemanticProperties properties) {
        this(jdbc,json,properties,new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())));
    }
    @org.springframework.beans.factory.annotation.Autowired
    public JdbcSemanticIndexState(JdbcTemplate jdbc,ObjectMapper json,SemanticProperties properties,PlatformTransactionManager manager) {
        this.jdbc=jdbc;this.json=json.copy().enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);this.properties=properties;
        this.transaction=new TransactionTemplate(manager);transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);transaction.setTimeout(5);
    }
    private <T> T fenced(Source source,SourceFence fence,Supplier<T> operation) {
        Objects.requireNonNull(fence,"A domain source fence is required");
        return transaction.execute(status->{if(!fence.current(source))throw new SemanticUnavailableException("VECTOR_INDEX_SOURCE_CHANGED");return operation.get();});
    }
    private Body body(Source source,String collection) {
        return new Body(1,source.kind(),source.id(),source.version(),source.contentSha256(),source.scope(),collection,
                properties.getProfile(),properties.getModel(),properties.getDimensions(),properties.getPreprocessing(),properties.getStorageGeneration());
    }
    private String encode(Body value){try{return json.writeValueAsString(value);}catch(Exception invalid){throw new IllegalStateException("Cannot encode index state");}}
    private Body decode(Map<String,Object> row) {
        try {
            if(((Number)row.get("payload_version")).intValue()!=1)throw new IllegalArgumentException();
            Body value=json.readValue(row.get("payload_json").toString(),Body.class);
            if(value.protocolVersion()!=1)throw new IllegalArgumentException();
            new Source(value.kind(),((Number)row.get("owner_id")).longValue(),value.sourceId(),value.sourceVersion(),value.contentSha256(),value.scope());
            return value;
        }catch(Exception invalid){throw new IllegalStateException("Derived index state protocol is invalid");}
    }
    private Map<String,Object> read(Source source) {
        var rows=jdbc.queryForList("SELECT owner_id,revision,current_ref,state_code,payload_version,payload_json,updated_at FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",source.owner(),source.key());
        return rows.isEmpty()?null:rows.get(0);
    }
    public String state(Source source,String collection,SourceFence fence) {
        return transaction.execute(status->fence.current(source)?readState(source,collection):"INACTIVE");
    }
    private String readState(Source source,String collection) {
        var row=read(source);
        if(row==null||!source.reference().equals(row.get("current_ref"))||!body(source,collection).equals(decode(row)))return "PENDING";
        String state=Objects.toString(row.get("state_code"));
        if(!Set.of("PENDING","INDEXING","READY","FAILED").contains(state))throw new IllegalStateException("Invalid index state");
        return state;
    }
    public Ticket claim(Source source,String collection,SourceFence fence) {
        return fenced(source,fence,()->claimCurrent(source,collection));
    }
    private Ticket claimCurrent(Source source,String collection) {
        Body expected=body(source,collection);String encoded=encode(expected);
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,current_ref,revision,state_code,payload_version,payload_json,created_at,updated_at) VALUES('SEMANTIC_INDEX',?,?,?,0,'PENDING',1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)",source.owner(),source.key(),source.reference(),encoded);
        var row=read(source);long revision=((Number)row.get("revision")).longValue();
        if(expected.equals(decode(row))&&source.reference().equals(row.get("current_ref"))&&"READY".equals(row.get("state_code")))
            return new Ticket(source,collection,revision,expected,true);
        if(jdbc.update("UPDATE runtime_state SET current_ref=?,state_code='INDEXING',revision=revision+1,payload_json=?,updated_at=UTC_TIMESTAMP(6) WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=? AND revision=?",source.reference(),encoded,source.owner(),source.key(),revision)!=1)
            throw new SemanticUnavailableException("VECTOR_INDEX_CLAIM_CHANGED");
        return new Ticket(source,collection,revision+1,expected,false);
    }
    public void finish(Ticket ticket,boolean success,SourceFence fence) {
        fenced(ticket.source(),fence,()->{
            if(!ticket.body().equals(body(ticket.source(),ticket.collection())))throw new SemanticUnavailableException("VECTOR_INDEX_GENERATION_CHANGED");
            if(jdbc.update("UPDATE runtime_state SET state_code=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=? AND revision=? AND current_ref=? AND state_code=? AND payload_json=?",success?"READY":"FAILED",ticket.source().owner(),ticket.source().key(),ticket.revision(),ticket.source().reference(),ticket.ready()?"READY":"INDEXING",encode(ticket.body()))!=1)
                throw new SemanticUnavailableException("VECTOR_INDEX_COMPLETION_CHANGED");
            return null;
        });
    }
    public Ticket reopen(Ticket ticket,SourceFence fence) {
        if(!ticket.ready())throw new IllegalArgumentException("Only a previously ready ticket can be reopened");
        return fenced(ticket.source(),fence,()->{
            if(!ticket.body().equals(body(ticket.source(),ticket.collection())))throw new SemanticUnavailableException("VECTOR_INDEX_GENERATION_CHANGED");
            if(jdbc.update("UPDATE runtime_state SET state_code='INDEXING',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=? AND revision=? AND current_ref=? AND state_code='READY' AND payload_json=?",ticket.source().owner(),ticket.source().key(),ticket.revision(),ticket.source().reference(),encode(ticket.body()))!=1)
                throw new SemanticUnavailableException("VECTOR_INDEX_REOPEN_CHANGED");
            return new Ticket(ticket.source(),ticket.collection(),ticket.revision()+1,ticket.body(),false);
        });
    }
    public void invalidate(String kind,long owner,String id) {
        // Publication/archiving owners call this while holding their existing source write lock.
        com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions.requireActive(jdbc);
        jdbc.update("UPDATE runtime_state SET state_code='PENDING',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",owner,kind+":"+id);
    }
    public void confirm(Ticket ticket,SourceFence fence) {
        if(!ticket.ready())throw new IllegalArgumentException("Only an exact remote-read verified index can be confirmed");
        finish(ticket,true,fence);
    }
}
