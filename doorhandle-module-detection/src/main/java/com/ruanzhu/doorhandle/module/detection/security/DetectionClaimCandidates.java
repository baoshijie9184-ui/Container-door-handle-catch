package com.ruanzhu.doorhandle.module.detection.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import java.util.*;

/** Bounded stable account IDs only. A candidate is never an assignee or a business writer. */
public final class DetectionClaimCandidates {
    private static final ObjectMapper JSON = new ObjectMapper();
    private DetectionClaimCandidates() { }
    public static List<String> canonical(List<String> input) {
        if(input==null || input.size()>16)throw new IllegalArgumentException("请选择至多 16 个检测账号");
        var ids=new TreeSet<Long>();
        for(String value:input){
            if(value==null || !value.matches("[1-9][0-9]{0,18}"))throw new IllegalArgumentException("候选账号 ID 无效");
            try{long id=Long.parseLong(value);if(!ids.add(id))throw new IllegalArgumentException("候选账号不能重复");}
            catch(NumberFormatException invalid){throw new IllegalArgumentException("候选账号 ID 超出范围");}
        }
        return ids.stream().map(Object::toString).toList();
    }
    public static List<String> read(String value) {
        if(value==null)return List.of();
        try{
            var tree=JSON.readTree(value);
            if(!tree.isArray())throw new IllegalArgumentException();
            var ids=new ArrayList<String>();for(var id:tree){if(!id.isTextual())throw new IllegalArgumentException();ids.add(id.textValue());}
            return canonical(ids);
        }catch(Exception invalid){throw new IllegalStateException("任务候选授权资料不可核对",invalid);}
    }
    public static String encode(List<String> ids) {
        var normalized=canonical(ids);if(normalized.isEmpty())return null;
        try{return JSON.writeValueAsString(normalized);}catch(Exception impossible){throw new IllegalStateException(impossible);}
    }
    public static boolean vacant(DetectionTask task) {
        return task!=null && (task.getAssignee()==null || task.getAssignee().isBlank())
                && Set.of("COMPLETED","PARTIAL_FAILED").contains(Objects.toString(task.getStatus(),""))
                && "PENDING_REVIEW".equals(task.getFlowStatus());
    }
    public static boolean includes(DetectionTask task,long userId) {
        if(!vacant(task))return false;
        try{return read(task.getClaimCandidateIds()).contains(Long.toString(userId));}catch(IllegalStateException invalid){return false;}
    }
    public static String predicate(String alias,String parameter) {
        if(alias==null||!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?"))throw new IllegalArgumentException("非法 SQL 别名");
        return "(("+alias+"assignee IS NULL OR TRIM("+alias+"assignee)='') AND "+alias+"status IN ('COMPLETED','PARTIAL_FAILED') AND "
                +alias+"flow_status='PENDING_REVIEW' AND JSON_CONTAINS("+alias+"claim_candidate_ids,JSON_QUOTE(CAST("+parameter+" AS CHAR))))";
    }
}
