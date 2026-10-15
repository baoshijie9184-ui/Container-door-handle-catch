package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import io.agentscope.core.tool.*;
import io.agentscope.core.message.ToolResultBlock;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.util.*;

/** 模型只能提议私人草稿；来源授权、评测、提交、发布和回退都不属于此工具。 */
public class SkillProposalTool implements AgentTool {
    private final SkillEvolutionService service;private final AgentActor actor;private final String runId;private final ObjectMapper json=new ObjectMapper();
    public SkillProposalTool(SkillEvolutionService service,AgentActor actor,String runId){this.service=service;this.actor=actor;this.runId=runId;}
    public String getName(){return SkillEvolutionService.PROPOSE;}
    public String getDescription(){return "仅用户明确要求提炼经验时，基于本人已经在技能页面授权的已完成 sourceRunId 生成私人技能草稿；不得复制实际账号、任务编号、密码、隐私正文或脚本。未授权来源会拒绝。草稿不执行、不发布，不接受聊天批准。请用户到技能演化页面评测和提交。";}
    public boolean isReadOnly(){return false;}
    public Map<String,Object> getParameters(){return Map.of("type","object","additionalProperties",false,"required",List.of("name","targetRole","description","instructions","tools","sourceRunId"),"properties",Map.of(
            "name",Map.of("type","string","pattern","^[a-z][a-z0-9-]{2,63}$"),"targetRole",Map.of("type","string","enum",actor.supervisor()?List.of("INSPECTOR","SUPERVISOR"):List.of("INSPECTOR")),
            "description",Map.of("type","string","minLength",4,"maxLength",300),"instructions",Map.of("type","string","minLength",40,"maxLength",6000),
            "tools",Map.of("type","array","minItems",1,"maxItems",12,"uniqueItems",true,"items",Map.of("type","string")),"sourceRunId",Map.of("type","string","pattern","^[A-Za-z0-9_-]{1,128}$")));}
    public Mono<ToolResultBlock> callAsync(ToolCallParam param){return Mono.fromCallable(()->{
        Map<String,Object> args=param.getInput();if(args==null||!args.keySet().equals(Set.of("name","targetRole","description","instructions","tools","sourceRunId"))||!(args.get("tools") instanceof List<?> values)||values.stream().anyMatch(v->!(v instanceof String)))throw new IllegalArgumentException();
        for(String key:List.of("name","targetRole","description","instructions","sourceRunId"))if(!(args.get(key) instanceof String))throw new IllegalArgumentException();
        if(runId==null)throw new SecurityException();String callId=param.getToolUseBlock()==null?null:param.getToolUseBlock().getId();
        String requestId=service.digest(Map.of("runId",runId,"arguments",args));
        var draft=new SkillDtos.Draft((String)args.get("name"),(String)args.get("targetRole"),(String)args.get("description"),(String)args.get("instructions"),values.stream().map(String.class::cast).toList(),(String)args.get("sourceRunId"),requestId);
        var saved=service.create(actor,draft,runId,callId);
        return ToolResultBlock.text(json.writeValueAsString(Map.of("status","DRAFT","skillId",saved.skillId(),"version",saved.latestVersion(),"message","私人技能草稿已保存 尚未评测、提交或发布 请到技能演化页面核对")));
    }).subscribeOn(Schedulers.boundedElastic()).onErrorResume(error->Mono.just(ToolResultBlock.error("技能草稿未保存 请核对来源授权、角色权限和参数 到技能演化页面查看")));}
}
