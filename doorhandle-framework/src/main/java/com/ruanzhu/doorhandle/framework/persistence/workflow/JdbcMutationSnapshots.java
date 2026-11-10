package com.ruanzhu.doorhandle.framework.persistence.workflow;

import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant.Snapshot;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;

/** Fixed domain mappings only. SQL identifiers can never originate from a request. */
public final class JdbcMutationSnapshots {
    public record Mapping(String type,String table,String key,String revision,List<String> fields,Set<String> masked,Set<String> secret) {
        public Mapping {for(String name:join(table,key,revision,fields))if(!name.matches("[a-z][a-z0-9_]*"))throw new IllegalArgumentException("Unsafe mapping");fields=List.copyOf(fields);masked=Set.copyOf(masked);secret=Set.copyOf(secret);}
        private static List<String> join(String table,String key,String revision,List<String> fields){var names=new ArrayList<>(fields);names.add(table);names.add(key);names.add(revision);return names;}
    }
    private final JdbcTemplate jdbc;
    public JdbcMutationSnapshots(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public Snapshot capture(Mapping mapping,String id,boolean lock) {
        if(id==null)return null;if(!id.matches("[1-9][0-9]{0,18}"))throw new IllegalArgumentException("资源编号无效");
        var columns=new LinkedHashSet<>(mapping.fields());columns.add(mapping.revision());
        var rows=jdbc.queryForList("SELECT "+String.join(",",columns)+" FROM "+mapping.table()+" WHERE "+mapping.key()+"=?"+(lock?" FOR UPDATE":""),Long.parseLong(id));
        if(rows.isEmpty())return null;if(rows.size()!=1)throw new IllegalStateException("资源不唯一");var row=rows.get(0);
        var values=new LinkedHashMap<String,Object>();for(String field:mapping.fields()){
            Object value=row.get(field);if(value instanceof java.sql.Timestamp timestamp)value=timestamp.toLocalDateTime().toString();
            else if(value instanceof java.sql.Date date)value=date.toLocalDate().toString();
            else if(value instanceof java.time.temporal.TemporalAccessor)value=value.toString();
            // Identities and explicitly mapped revisions are strings; ordinary quantities retain their numeric type.
            else if(value instanceof Number&&(field.equals("id")||field.equals(mapping.key())||field.endsWith("_id")||field.equals(mapping.revision())))value=value.toString();
            // Details beyond the fixed public bound are represented by content identity, never copied wholesale.
            if(value instanceof String text&&text.length()>512)value="sha256:"+sha(text);
            values.put(field,value);
        }
        // Freeze the public relationship labels in the same business transaction.
        // History readers must never resolve these IDs against today's personnel records.
        relationship(values,"employee_id","SELECT name,employee_number FROM employee WHERE id=?",Map.of("name","employee_name","employee_number","employee_number"));
        relationship(values,"department_id","SELECT name FROM organization_department WHERE id=?",Map.of("name","department_name"));
        relationship(values,"device_id","SELECT device_code,model_name FROM device_management WHERE id=?",Map.of("device_code","device_code","model_name","device_model_name"));
        return new Snapshot(mapping.type(),id,((Number)row.get(mapping.revision())).longValue(),values,mapping.masked(),mapping.secret());
    }
    private void relationship(Map<String,Object> fields,String key,String sql,Map<String,String> labels){
        if(!fields.containsKey(key))return;
        Object id=fields.get(key);Map<String,Object> row=Map.of();
        if(id!=null){
            String value=id.toString();if(!value.matches("[1-9][0-9]{0,18}"))throw new IllegalStateException("Invalid persisted relationship identity");
            var rows=jdbc.queryForList(sql,Long.parseLong(value));
            if(rows.size()>1)throw new IllegalStateException("Relationship identity is not unique");
            if(!rows.isEmpty())row=rows.get(0);
        }
        for(var label:labels.entrySet()){
            Object value=row.get(label.getKey());
            if(value!=null&&(!(value instanceof String)||((String)value).length()>512))throw new IllegalStateException("Invalid persisted relationship label");
            fields.put(label.getValue(),value);
        }
    }
    public Snapshot advance(Mapping mapping,Snapshot before,Snapshot after) {
        if(before==null||after==null||!Objects.equals(before.version(),after.version()))return after;
        long next=Math.addExact(before.version(),1);
        if(jdbc.update("UPDATE "+mapping.table()+" SET "+mapping.revision()+"=? WHERE "+mapping.key()+"=? AND "+mapping.revision()+"=?",next,Long.parseLong(after.resourceId()),before.version())!=1)
            throw new IllegalStateException("资源版本更新失败");
        return capture(mapping,after.resourceId(),false);
    }
    /** Read an explicit list of public command properties for digesting, never all DTO fields. */
    public static Map<String,Object> properties(Object bean,String...names) {
        var values=new TreeMap<String,Object>();if(bean==null)return values;
        for(String name:names)try{var method=bean.getClass().isRecord()?bean.getClass().getMethod(name):bean.getClass().getMethod("get"+Character.toUpperCase(name.charAt(0))+name.substring(1));
            values.put(name,method.invoke(bean));
        }catch(NoSuchMethodException absent){throw new IllegalArgumentException("Command property missing: "+name);}
        catch(ReflectiveOperationException invalid){throw new IllegalArgumentException("Command property unreadable",invalid);}
        return values;
    }
    private static String sha(String value){try{return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
