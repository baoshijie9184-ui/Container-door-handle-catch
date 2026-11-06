package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.state.*;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** SDK checkpoints share runtime_state, retaining typed owner/session/key and real CAS. */
public final class JdbcWorkbenchStateStore implements AgentStateStore {
    private static final String NAMESPACE="SDK_CHECKPOINT";
    private final WorkbenchStore store; private final JdbcTemplate jdbc; private final ObjectMapper json=new ObjectMapper();
    private final boolean sdkAttempt; private final Map<String,Lease> leases=new java.util.concurrent.ConcurrentHashMap<>();
    private final Runnable assertClaim;
    private final String expectedUser,expectedSession;
    private static final class Lease { long latest; final Set<Long> versions=new HashSet<>(); Lease(long version){latest=version;versions.add(version);} }
    /** The inner JSON string is retained byte-for-byte; SDK encoding is independent of the shared envelope. */
    public record CheckpointV1(String stateJson) { public CheckpointV1 { Objects.requireNonNull(stateJson,"stateJson"); } }
    private record Snapshot(long revision,int payloadVersion,String payload) { }
    public JdbcWorkbenchStateStore(WorkbenchStore store){this(store,false);}
    public JdbcWorkbenchStateStore(WorkbenchStore store,boolean sdkAttempt){this(store,sdkAttempt,()->{});}
    public JdbcWorkbenchStateStore(WorkbenchStore store,boolean sdkAttempt,Runnable assertClaim){this(store,sdkAttempt,assertClaim,null,null);}
    public JdbcWorkbenchStateStore(WorkbenchStore store,boolean sdkAttempt,Runnable assertClaim,String expectedUser,String expectedSession){this.store=store;this.jdbc=store.jdbc();this.sdkAttempt=sdkAttempt;this.assertClaim=Objects.requireNonNull(assertClaim);this.expectedUser=expectedUser;this.expectedSession=expectedSession;}
    private void binding(String user,String session){if(expectedUser!=null&&(!expectedUser.equals(user)||!expectedSession.equals(session)))throw new SecurityException("SDK 状态不属于本次执行");}
    private long account(String user){if(user==null||!user.matches("[1-9][0-9]{0,18}"))throw new SecurityException("状态必须属于有效账号");try{return Long.parseLong(user);}catch(NumberFormatException error){throw new SecurityException("状态必须属于有效账号");}}
    private static void session(String value){if(value==null||value.codePointCount(0,value.length())>160)throw new IllegalArgumentException("SDK session exceeds its registered limit");}
    private static String scope(String session,String key){
        session(session);if(key==null||key.codePointCount(0,key.length())>128)throw new IllegalArgumentException("SDK state key exceeds its registered limit");
        return WorkbenchStore.hash(session.getBytes(StandardCharsets.UTF_8).length+":"+session+":"+key.getBytes(StandardCharsets.UTF_8).length+":"+key);
    }
    private String encode(Object value){if(value instanceof AgentState state)return state.toJson();return store.encode(value);}
    private <T>T decode(String value,Class<T> type){try{return type==AgentState.class?type.cast(AgentState.fromJsonString(value)):json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("SDK 检查点不可读",error);}}
    private Snapshot snapshot(long owner,String session,String key){
        binding(Long.toString(owner),session);
        scope(session,key);
        var rows=jdbc.query("SELECT revision,payload_version,payload_json FROM runtime_state WHERE namespace=? AND owner_id=? AND session_id=? AND state_key=?",
                (rs,n)->new Snapshot(rs.getLong(1),rs.getInt(2),rs.getString(3)),NAMESPACE,owner,session,key);
        return rows.isEmpty()?null:rows.get(0);
    }
    private String state(Snapshot row){
        if(row.payloadVersion()!=1)throw new IllegalStateException("Unsupported SDK checkpoint version");
        try{return json.readValue(row.payload(),CheckpointV1.class).stateJson();}
        catch(Exception error){throw new IllegalStateException("SDK 检查点封装不可读",error);}
    }
    @Override public boolean supportsVersioning(){return true;}
    @Override public <T extends State>VersionedState<T> getVersioned(String user,String session,String key,Class<T> type){
        var row=snapshot(account(user),session,key);return row==null?new VersionedState<>(null,0):new VersionedState<>(decode(state(row),type),row.revision());
    }
    @Override public long saveIfVersion(String user,String session,String key,State value,long version){
        if(!sdkAttempt)return saveCas(user,session,key,encode(value),version);
        // SDK final save may reuse its initial version; only this attempt's durable versions are accepted.
        if(version==UNVERSIONED)throw WorkbenchStore.fail(409,"SDK 状态不允许无版本覆盖");
        var lease=leases.computeIfAbsent(account(user)+":"+scope(session,key),ignored->new Lease(version));
        synchronized(lease){
            if(!lease.versions.contains(version))throw WorkbenchStore.fail(409,"SDK 检查点版本不属于当前执行尝试");
            long saved=saveCas(user,session,key,encode(value),lease.latest);
            if(saved==UNVERSIONED)throw WorkbenchStore.fail(409,"SDK 检查点已被其他执行修改");
            lease.latest=saved;lease.versions.add(saved);return saved;
        }
    }
    private long saveCas(String user,String session,String key,String state,long version){
        binding(user,session);
        long owner=account(user);String scope=scope(session,key);String envelope=store.encode(new CheckpointV1(state));
        return store.locked(owner,()->{
            assertClaim.run();
            var row=snapshot(owner,session,key);long current=row==null?0:row.revision();
            if(version!=UNVERSIONED&&version!=current)return UNVERSIONED;
            if(row==null)jdbc.update("""
                    INSERT INTO runtime_state(namespace,owner_id,scope_key,session_id,state_key,revision,state_code,payload_version,payload_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,1,'LIVE',1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                    """,NAMESPACE,owner,scope,session,key,envelope);
            else if(jdbc.update("""
                    UPDATE runtime_state SET revision=revision+1,payload_json=?,updated_at=UTC_TIMESTAMP(6)
                    WHERE namespace=? AND owner_id=? AND scope_key=? AND session_id=? AND state_key=? AND revision=?
                    """,envelope,NAMESPACE,owner,scope,session,key,current)!=1)return UNVERSIONED;
            return current+1;
        });
    }
    @Override public void save(String user,String session,String key,State value){saveIfVersion(user,session,key,value,UNVERSIONED);}
    @Override public void save(String user,String session,String key,List<? extends State> values){if(sdkAttempt)throw WorkbenchStore.fail(409,"SDK 检查点不允许无版本覆盖");saveCas(user,session,key,store.encode(values),UNVERSIONED);}
    @Override public <T extends State>Optional<T> get(String user,String session,String key,Class<T> type){return Optional.ofNullable(getVersioned(user,session,key,type).value());}
    @Override public <T extends State>List<T> getList(String user,String session,String key,Class<T> type){
        var row=snapshot(account(user),session,key);if(row==null)return List.of();
        try{var array=json.readTree(state(row));if(!array.isArray())throw new IllegalStateException("SDK checkpoint is not a list");var result=new ArrayList<T>();for(var entry:array)result.add(decode(entry.toString(),type));return result;}
        catch(Exception error){throw new IllegalStateException("SDK 状态列表不可读",error);}
    }
    @Override public boolean exists(String user,String session){binding(user,session);session(session);return jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace=? AND owner_id=? AND session_id=?",Long.class,NAMESPACE,account(user),session)>0;}
    @Override public void delete(String user,String session){binding(user,session);session(session);long owner=account(user);store.locked(owner,()->{assertClaim.run();jdbc.update("DELETE FROM runtime_state WHERE namespace=? AND owner_id=? AND session_id=?",NAMESPACE,owner,session);return null;});}
    @Override public void delete(String user,String session,String key){binding(user,session);scope(session,key);long owner=account(user);store.locked(owner,()->{assertClaim.run();jdbc.update("DELETE FROM runtime_state WHERE namespace=? AND owner_id=? AND session_id=? AND state_key=?",NAMESPACE,owner,session,key);return null;});}
    @Override public Set<String> listSessionIds(String user){if(expectedUser!=null){binding(user,expectedSession);return exists(user,expectedSession)?Set.of(expectedSession):Set.of();}return new HashSet<>(jdbc.queryForList("SELECT DISTINCT session_id FROM runtime_state WHERE namespace=? AND owner_id=?",String.class,NAMESPACE,account(user)));}
}
