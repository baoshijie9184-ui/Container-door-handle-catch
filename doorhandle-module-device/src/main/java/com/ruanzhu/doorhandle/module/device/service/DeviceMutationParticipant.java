package com.ruanzhu.doorhandle.module.device.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.util.*;

/** Personnel, devices and usage are owned by this module; only the fixed public facts enter history. */
@Component
public class DeviceMutationParticipant implements BusinessMutationParticipant,BusinessResourceAccess {
    private static final Mapping EMPLOYEE=map("EMPLOYEE","employee","name employee_number contact gender department_id employee_type status hire_date","contact");
    private static final Mapping DEVICE=map("DEVICE","device_management","device_code device_type model_name serial_number status employee_id last_maintenance_date","");
    private static final Mapping USAGE=map("DEVICE_USAGE","device_usage","device_id employee_id start_time end_time status remarks","");
    private static final Mapping ALERT=map("DEVICE_ALERT","device_alert","device_id status ack_operator ack_remark acknowledged_at resolved_operator resolved_remark resolved_at","");
    private static final Map<String,Set<String>> ACTIONS=Map.of(
            "EMPLOYEE",Set.of("add","update","delete"),
            "DEVICE",Set.of("createDevice","updateDevice","deleteDevice","removeEmployeeFromDevice","UNASSIGN_EMPLOYEE","assignDeviceToEmployee","USAGE_ASSIGN","USAGE_RETURN"),
            "DEVICE_USAGE",Set.of("createDeviceUsageRecord","updateDeviceUsageRecord","deleteDeviceUsageRecord","createRecord","updateRecord","deleteRecord","returnDevice"),
            "DEVICE_ALERT",Set.of("ACKNOWLEDGE","RESOLVE"));
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;private final JdbcMutationSnapshots snapshots;
    public DeviceMutationParticipant(JdbcTemplate jdbc,BusinessUserDirectory users){this.jdbc=jdbc;this.users=users;this.snapshots=new JdbcMutationSnapshots(jdbc);}
    private static Mapping map(String type,String table,String fields,String masked){return new Mapping(type,table,"id","version",List.of(fields.split(" ")),masked.isEmpty()?Set.of():Set.of(masked),Set.of());}
    private static Mapping mapping(String domain){return switch(domain){case "EMPLOYEE"->EMPLOYEE;case "DEVICE"->DEVICE;case "DEVICE_USAGE"->USAGE;case "DEVICE_ALERT"->ALERT;default->throw new IllegalArgumentException("Unsupported device resource");};}
    public boolean supports(String domain,String action){return ACTIONS.getOrDefault(domain,Set.of()).contains(action);}
    public String resourceDomain(Snapshot snapshot,String commandDomain){return snapshot.resourceType();}
    public boolean creates(String action){return Set.of("add","createDevice","createDeviceUsageRecord","createRecord").contains(action);}
    public String resourceId(String domain,String action,Object[] args,Object result){
        if("assignDeviceToEmployee".equals(action))return String.valueOf(args[1]);
        Object selected="createDevice".equals(action)?result:args[0];
        if(selected==null)return null;if(selected instanceof Number)return selected.toString();
        Object id=JdbcMutationSnapshots.properties(selected,"id").get("id");return id==null?null:id.toString();
    }
    public void prepare(AgentActor actor,String domain,String action,String id,Object[] arguments){
        var current=users.lockCurrent(actor.userId(),actor.username());if(!current.supervisor())throw new SecurityException("当前无人员设备管理权限");
        // Employee -> device -> usage is the common order for assignment, deletion and return.
        var employees=new TreeSet<Long>();var devices=new TreeSet<Long>();
        if("EMPLOYEE".equals(domain)&&id!=null)employees.add(Long.parseLong(id));
        if("assignDeviceToEmployee".equals(action))employees.add(((Number)arguments[0]).longValue());
        if("USAGE_ASSIGN".equals(action))employees.add(((Number)arguments[1]).longValue());
        if("DEVICE".equals(domain)&&id!=null)devices.add(Long.parseLong(id));
        if("DEVICE_USAGE".equals(domain)){
            if(id!=null)devices.addAll(jdbc.queryForList("SELECT device_id FROM device_usage WHERE id=?",Long.class,Long.parseLong(id)));
            if(Set.of("createDeviceUsageRecord","updateDeviceUsageRecord","createRecord","updateRecord").contains(action)){
                var input=JdbcMutationSnapshots.properties(arguments[0],"deviceId","employeeId");
                if(input.get("deviceId") instanceof Number device)devices.add(device.longValue());
                if(input.get("employeeId") instanceof Number employee)employees.add(employee.longValue());
            }
        }
        for(Long employee:employees)jdbc.queryForList("SELECT id FROM employee WHERE id=? FOR UPDATE",employee);
        if("EMPLOYEE".equals(domain)&&"delete".equals(action)&&id!=null){
            devices.addAll(jdbc.queryForList("SELECT id FROM device_management WHERE employee_id=? ORDER BY id",Long.class,Long.parseLong(id)));
            devices.addAll(jdbc.queryForList("SELECT DISTINCT device_id FROM device_usage WHERE employee_id=? ORDER BY device_id",Long.class,Long.parseLong(id)));
        }
        if(devices.size()>200)throw new IllegalArgumentException("关联设备超过单次操作上限，请分批处理");
        for(Long device:devices)jdbc.queryForList("SELECT id FROM device_management WHERE id=? FOR UPDATE",device);
    }
    public Snapshot capture(AgentActor actor,String domain,String action,String id,boolean lock){requireSupervisor(actor);return snapshots.capture(mapping(domain),id,lock);}
    public Snapshot advanceVersion(Snapshot before,Snapshot after){return snapshots.advance(mapping((after==null?before:after).resourceType()),before,after);}
    public Object digestInput(String action,Object[] args){
        if(Set.of("add","update").contains(action))return JdbcMutationSnapshots.properties(args[0],"id","version","name","employeeNumber","contact","gender","department","departmentId","employeeType","status","hireDate");
        if(Set.of("createDevice","updateDevice").contains(action)){Object bean=args[args.length-1];return Arrays.asList(args.length>1?args[0]:null,JdbcMutationSnapshots.properties(bean,"id","version","deviceCode","deviceType","modelName","serialNumber","status","employeeId","lastMaintenanceDate"));}
        if(Set.of("createDeviceUsageRecord","updateDeviceUsageRecord","createRecord","updateRecord").contains(action))return JdbcMutationSnapshots.properties(args[0],"id","version","deviceId","employeeId","startTime","endTime","status","remarks");
        if(Set.of("ACKNOWLEDGE","RESOLVE").contains(action))return Arrays.asList(args[0],JdbcMutationSnapshots.properties(args[1],"remark"));
        return Arrays.asList(args);
    }
    public boolean mayRead(AgentActor actor,String scope,String domain,String type,String id){
        if(!"ENTERPRISE".equals(scope)||!Objects.equals(domain,type)||!Set.of("EMPLOYEE","DEVICE","DEVICE_USAGE","DEVICE_ALERT").contains(type))return false;
        try{
            var current=users.current(actor.userId(),actor.username());
            if(!"DEVICE".equals(type))return current.supervisor();
            if(id==null||!id.matches("[1-9][0-9]{0,18}"))return false;
            long device=Long.parseLong(id);
            // GET /api/devices/{id} is available to every qualified account.
            // A removed device has no inspector-readable detail; supervisors retain its deletion history.
            return current.supervisor()||Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)>0 FROM device_management WHERE id=?",Boolean.class,device));
        }catch(SecurityException|NumberFormatException unavailable){return false;}
    }
    private void requireSupervisor(AgentActor actor){if(!users.current(actor.userId(),actor.username()).supervisor())throw new SecurityException("当前无人员设备管理权限");}
    public List<Snapshot> related(AgentActor actor,String domain,String action,String id,Object[] arguments,List<Snapshot> previous,boolean lock){
        requireSupervisor(actor);var references=new TreeMap<String,Mapping>();
        for(var item:previous)references.put(item.resourceType()+":"+item.resourceId(),mapping(item.resourceType()));
        if(id!=null&&"EMPLOYEE".equals(domain)&&"delete".equals(action))for(Long device:jdbc.queryForList("SELECT id FROM device_management WHERE employee_id=? ORDER BY id",Long.class,Long.parseLong(id)))references.put("DEVICE:"+device,DEVICE);
        if(id!=null&&"EMPLOYEE".equals(domain)&&"delete".equals(action))for(Long usage:jdbc.queryForList("SELECT id FROM device_usage WHERE employee_id=? ORDER BY id",Long.class,Long.parseLong(id)))references.put("DEVICE_USAGE:"+usage,USAGE);
        if(id!=null&&"DEVICE".equals(domain))for(Long usage:jdbc.queryForList("SELECT id FROM device_usage WHERE device_id=? ORDER BY id",Long.class,Long.parseLong(id)))references.put("DEVICE_USAGE:"+usage,USAGE);
        if(id!=null&&"DEVICE".equals(domain)&&"deleteDevice".equals(action))for(Long alert:jdbc.queryForList("SELECT id FROM device_alert WHERE device_id=? ORDER BY id",Long.class,Long.parseLong(id)))references.put("DEVICE_ALERT:"+alert,ALERT);
        if("DEVICE_USAGE".equals(domain)){
            if(id!=null)for(Long device:jdbc.queryForList("SELECT device_id FROM device_usage WHERE id=?",Long.class,Long.parseLong(id)))references.put("DEVICE:"+device,DEVICE);
            if(Set.of("createDeviceUsageRecord","updateDeviceUsageRecord","createRecord","updateRecord").contains(action)){
                Object device=JdbcMutationSnapshots.properties(arguments[0],"deviceId").get("deviceId");
                if(device!=null)references.put("DEVICE:"+device,DEVICE);
            }
        }
        if(references.size()>200)throw new IllegalArgumentException("关联资源超过单次操作上限，请分批处理");
        var result=new ArrayList<Snapshot>();for(var entry:references.entrySet()){String resource=entry.getKey().substring(entry.getKey().indexOf(':')+1);var snapshot=snapshots.capture(entry.getValue(),resource,lock);if(snapshot!=null)result.add(snapshot);}return result;
    }
}
