package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.state.*;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;

/** SDK state is keyed by stable account ID and SDK session, with real CAS support. */
public final class JdbcWorkbenchStateStore implements AgentStateStore {
    private final WorkbenchStore store;private final JdbcTemplate jdbc;private final ObjectMapper json=new ObjectMapper();
    private final boolean sdkAttempt;private final Map<String,Lease> leases=new java.util.concurrent.ConcurrentHashMap<>();
    private static final class Lease {long latest;final Set<Long> versions=new HashSet<>();Lease(long version){latest=version;versions.add(version);}}
    public JdbcWorkbenchStateStore(WorkbenchStore store){this(store,false);}
    public JdbcWorkbenchStateStore(WorkbenchStore store,boolean sdkAttempt){this.store=store;this.jdbc=store.jdbc;this.sdkAttempt=sdkAttempt;}
    private String slot(String user,String session,String key){return user+":"+session+":"+key;}
    private long account(String user){if(user==null||!user.matches("[1-9][0-9]{0,18}"))throw new SecurityException("状态必须属于有效账号");return Long.parseLong(user);}
    private String encode(Object value){if(value instanceof AgentState state)return state.toJson();return store.encode(value);}
    private <T>T decode(String value,Class<T> type){try{return type==AgentState.class?type.cast(AgentState.fromJsonString(value)):json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("SDK 检查点不可读");}}
    @Override public boolean supportsVersioning(){return true;}
    @Override public <T extends State>VersionedState<T> getVersioned(String user,String session,String key,Class<T> type){account(user);var rows=jdbc.queryForList("SELECT revision,state_json FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=? AND state_key=?",user,session,key);return rows.isEmpty()?new VersionedState<>(null,0):new VersionedState<>(decode((String)rows.get(0).get("state_json"),type),((Number)rows.get(0).get("revision")).longValue());}
    @Override public long saveIfVersion(String user,String session,String key,State value,long version){
        if(!sdkAttempt)return saveCas(user,session,key,value,version);
        // SDK 2.0.4 keeps the call's initial version for its final save, while explicit
        // checkpoint saves advance slotVersions. Accept only versions produced by this
        // attempt, and CAS against its last durable version. A foreign writer always fails;
        // throwing also prevents the SDK's default OVERWRITE conflict fallback.
        if(version==UNVERSIONED)throw WorkbenchStore.fail(409,"SDK 状态不允许无版本覆盖");
        var lease=leases.computeIfAbsent(slot(user,session,key),ignored->new Lease(version));
        synchronized(lease){if(!lease.versions.contains(version))throw WorkbenchStore.fail(409,"SDK 检查点版本不属于当前执行尝试");long saved=saveCas(user,session,key,value,lease.latest);if(saved==UNVERSIONED)throw WorkbenchStore.fail(409,"SDK 检查点已被其他执行修改");lease.latest=saved;lease.versions.add(saved);return saved;}
    }
    private long saveCas(String user,String session,String key,State value,long version){return store.locked(account(user),()->{
        var rows=jdbc.queryForList("SELECT revision FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=? AND state_key=?",user,session,key);long current=rows.isEmpty()?0:((Number)rows.get(0).get("revision")).longValue();
        if(version!=UNVERSIONED&&version!=current)return UNVERSIONED;
        if(rows.isEmpty())jdbc.update("INSERT INTO agent_workbench_sdk_state(user_id,session_id,state_key,revision,state_json) VALUES(?,?,?,?,?)",user,session,key,1,encode(value));
        else jdbc.update("UPDATE agent_workbench_sdk_state SET revision=revision+1,state_json=?,updated_at=CURRENT_TIMESTAMP(6) WHERE user_id=? AND session_id=? AND state_key=?",encode(value),user,session,key);
        return current+1;
    });}
    @Override public void save(String user,String session,String key,State value){saveIfVersion(user,session,key,value,UNVERSIONED);}
    @Override public void save(String user,String session,String key,List<? extends State> values){store.locked(account(user),()->{var value=store.encode(values);jdbc.update("DELETE FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=? AND state_key=?",user,session,key);jdbc.update("INSERT INTO agent_workbench_sdk_state(user_id,session_id,state_key,revision,state_json) VALUES(?,?,?,?,?)",user,session,key,1,value);return null;});}
    @Override public <T extends State>Optional<T> get(String user,String session,String key,Class<T> type){return Optional.ofNullable(getVersioned(user,session,key,type).value());}
    @Override public <T extends State>List<T> getList(String user,String session,String key,Class<T> type){account(user);var rows=jdbc.queryForList("SELECT state_json FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=? AND state_key=?",user,session,key);if(rows.isEmpty())return List.of();try{var array=json.readTree((String)rows.get(0).get("state_json"));var result=new ArrayList<T>();for(var entry:array)result.add(decode(entry.toString(),type));return result;}catch(Exception error){throw new IllegalStateException("SDK 状态列表不可读");}}
    @Override public boolean exists(String user,String session){account(user);return jdbc.queryForObject("SELECT COUNT(*) FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=?",Integer.class,user,session)>0;}
    @Override public void delete(String user,String session){account(user);jdbc.update("DELETE FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=?",user,session);}
    @Override public void delete(String user,String session,String key){account(user);jdbc.update("DELETE FROM agent_workbench_sdk_state WHERE user_id=? AND session_id=? AND state_key=?",user,session,key);}
    @Override public Set<String> listSessionIds(String user){account(user);return new HashSet<>(jdbc.queryForList("SELECT DISTINCT session_id FROM agent_workbench_sdk_state WHERE user_id=?",String.class,user));}
}
