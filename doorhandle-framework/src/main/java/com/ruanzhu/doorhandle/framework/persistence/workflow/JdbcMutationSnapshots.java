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
            // JavaScript cannot represent all persisted BIGINT values exactly.
            else if(value instanceof Long||value instanceof Number&&(field.equals("id")||field.endsWith("_id")))value=value.toString();
            // Details beyond the fixed public bound are represented by content identity, never copied wholesale.
            if(value instanceof String text&&text.length()>512)value="sha256:"+sha(text);
            values.put(field,value);
        }
        return new Snapshot(mapping.type(),id,((Number)row.get(mapping.revision())).longValue(),values,mapping.masked(),mapping.secret());
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
