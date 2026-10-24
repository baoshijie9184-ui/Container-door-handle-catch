package com.ruanzhu.doorhandle.module.system.service;

import java.lang.reflect.Method;
import java.util.*;

/** Reads only declared identifier/version metadata, never serializes a DTO or evaluates user expressions. */
final class AuditMetadata {
    static final String CORRELATION=AuditMetadata.class.getName()+".request";
    private static final Set<String> PROPERTIES=Set.of("id","taskId","modelId","userId","reportId","fileId","version","bindingVersion","requestId","revision","body");
    static Object select(String selector,Object[] args,Object result){
        if(selector==null||selector.isEmpty())return null;
        if(selector.startsWith("literal:"))return selector.substring(8);
        if(!selector.matches("(?:arg[0-9]+|result)(?:\\.[A-Za-z][A-Za-z0-9]*){0,3}"))throw new IllegalStateException("审计元数据选择器无效");
        String[] parts=selector.split("\\.");Object value;
        if(parts[0].equals("result"))value=result;else{int index=Integer.parseInt(parts[0].substring(3));if(index>=args.length)throw new IllegalStateException("审计参数位置无效");value=args[index];}
        for(int i=1;i<parts.length;i++)value=property(value,parts[i]);return value;
    }
    static String resource(String selector,Object[] args,Object result){
        Object value;
        if("auto".equals(selector)){
            value=args.length==0?null:identifier(args[0]);if(value==null)value=identifier(result);
        }else value=select(selector,args,result);
        if(value==null&&Boolean.FALSE.equals(result))return "not-created";
        if(!(value instanceof String||value instanceof Number))throw new IllegalStateException("业务审计缺少稳定资源编号");
        String text=value.toString();if(!text.matches("[A-Za-z0-9_:./-]{1,160}"))throw new IllegalStateException("业务审计资源编号格式无效");return text;
    }
    static Long version(String selector,Object[] args,Object result){Object value=select(selector,args,result);if(value==null)return null;if(!(value instanceof Number)||!value.toString().matches("[0-9]+"))throw new IllegalStateException("审计版本必须是实际非负整数");try{return Long.parseLong(value.toString());}catch(NumberFormatException invalid){throw new IllegalStateException("审计版本超出范围");}}
    static String request(Object preferred){
        if(preferred!=null&&!(preferred instanceof String))throw new IllegalArgumentException("业务请求编号无效");String chosen=(String)preferred;
        var attributes=org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes servlet){
            String header=servlet.getRequest().getHeader("X-Request-ID");if(header!=null){if(chosen!=null&&!chosen.equals(header))throw new IllegalArgumentException("请求编号与业务命令不一致");chosen=header;}
            if(chosen==null&&servlet.getRequest().getAttribute(CORRELATION) instanceof String existing)chosen=existing;
        }
        if(chosen==null)chosen=UUID.randomUUID().toString();if(!chosen.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("审计请求编号无效");
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes servlet){servlet.getRequest().setAttribute(CORRELATION,chosen);if(servlet.getResponse()!=null)servlet.getResponse().setHeader("X-Request-ID",chosen);}
        return chosen;
    }
    private static Object identifier(Object value){
        if(value instanceof String||value instanceof Number)return value;if(value==null||value instanceof Boolean)return null;
        for(String property:List.of("taskId","modelId","reportId","id","userId")){Object id=property(value,property,false);if(id instanceof String||id instanceof Number)return id;}return null;
    }
    private static Object property(Object value,String name){return property(value,name,true);}
    private static Object property(Object value,String name,boolean required){
        if(!PROPERTIES.contains(name))throw new IllegalStateException("禁止读取非审计元数据字段");if(value==null)return null;
        if(value instanceof Map<?,?> values)return values.get(name);
        try{
            Method method;
            if(value.getClass().isRecord())method=value.getClass().getMethod(name);
            else method=value.getClass().getMethod("get"+Character.toUpperCase(name.charAt(0))+name.substring(1));
            return method.invoke(value);
        }catch(NoSuchMethodException missing){if(!required)return null;throw new IllegalStateException("审计元数据字段不存在");}
        catch(ReflectiveOperationException unavailable){throw new IllegalStateException("审计元数据不可读取");}
    }
}
