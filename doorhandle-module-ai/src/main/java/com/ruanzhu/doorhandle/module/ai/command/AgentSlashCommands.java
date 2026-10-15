package com.ruanzhu.doorhandle.module.ai.command;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.evolution.SkillDtos;
import com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;

/** 只解析本轮用户输入；目录和错误不交给模型猜测或执行。 */
public final class AgentSlashCommands {
    public record Plan(String reply,SkillDtos.LoadedSkill skill,String question) {}
    private final SkillEvolutionService evolution;
    public AgentSlashCommands(SkillEvolutionService evolution){this.evolution=evolution;}
    public Map<String,Object> catalog(AgentActor actor){return Map.of("commands",List.of(
            Map.of("value","/help","description","查看命令帮助"),
            Map.of("value","/skills","description","列出当前角色可用技能"),
            Map.of("value","/skills manage","description","查看技能管理入口"),
            Map.of("value","/skill ","description","选择技能名并填写问题")),
            "skills",evolution==null?List.of():evolution.availableSkills(actor),"externalInstallSupported",evolution!=null&&evolution.linksEnabled());}
    public Plan prepare(AgentActor actor,String input,AgentJournal.Run audit){
        if(input==null||!input.stripLeading().startsWith("/"))return null;
        String text=input.strip();String[] parts=text.split("\\s+",3);String command=parts[0];
        audit.event("COMMAND_RECEIVED",Map.of("command",Set.of("/help","/skills","/skill").contains(command)?command.substring(1):"skill-alias","policyVersion","skill-command-v1"));
        try{
            if("/help".equals(command))return reply(help());
            if("/skills".equals(command)){
                if(parts.length==1||parts.length==2&&"list".equals(parts[1]))return reply(list(actor));
                if(parts.length==2&&"manage".equals(parts[1]))return reply("技能管理入口：/#/agent/skills\n可管理业务经验草稿、评测、审核和已发布版本。");
                if(parts.length==3&&"info".equals(parts[1])&&!parts[2].contains(" ")&&!parts[2].contains("\n"))return reply(describe(skill(actor,parts[2],false,audit)));
                if(parts.length==3&&"install".equals(parts[1])){
                    if(evolution==null||!evolution.linksEnabled())return reply("链接安装尚未启用 请到技能页面核对配置");
                    com.ruanzhu.doorhandle.module.ai.evolution.SkillLinkService.validateUrl(parts[2]);
                    return reply("尚未下载或启用。请[打开本人技能页面确认下载](/#/agent/skills?installUrl="+java.net.URLEncoder.encode(parts[2],java.nio.charset.StandardCharsets.UTF_8)+")，完成规则 Eval 并提交独立审核。脚本和附件当前不执行。");
                }
                return reply("此 Skill 操作尚未接入。外部 Skill 安装、卸载不会通过聊天执行。\n"+help());
            }
            String selector,question;
            if("/skill".equals(command)){if(parts.length<2)return reply("请填写技能名，例如 /skill task-progress 查询任务进度\n用 /skills 查看可用技能。");selector=parts[1];question=parts.length==3?parts[2]:"";}
            else {selector=command.substring(1);question=text.substring(command.length()).strip();}
            var selected=skill(actor,selector,true,audit);
            audit.event("SKILL_COMMAND_LOADED",Map.of("skillId",selected.metadata().skillId(),"version",selected.metadata().version(),"sha256",selected.sha256(),"policyVersion","skill-command-v1"));
            if(question.isBlank())return reply("已加载 "+selected.metadata().name()+" · v"+selected.metadata().version()+"\n"+selected.instructions()+"\n\n需要结合业务问题使用时：/skill "+selected.metadata().skillId()+" 你的问题");
            return new Plan(null,selected,question);
        }catch(ResponseStatusException error){audit.event("COMMAND_REJECTED",Map.of("status",error.getStatusCode().value(),"policyVersion","skill-command-v1"));return reply(error.getReason()==null?"技能命令暂不可用 请刷新 /skills":error.getReason());}
    }
    private SkillDtos.LoadedSkill skill(AgentActor actor,String selector,boolean record,AgentJournal.Run audit){if(evolution==null)throw new ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"技能演化尚未启用");return evolution.commandSkill(actor,selector,record,audit.id(),"slash-"+UUID.randomUUID());}
    private Plan reply(String message){return new Plan(message,null,null);}
    private String list(AgentActor actor){if(evolution==null)return "技能演化尚未启用";var skills=evolution.availableSkills(actor);
        if(skills.isEmpty())return "当前角色没有可用的已发布技能。私人草稿、已停用版本及历史上传 Skill 不在可用列表中。\n技能管理入口：/#/agent/skills";
        StringBuilder result=new StringBuilder("当前角色可用技能\n");for(var s:skills.subList(0,Math.min(15,skills.size())))result.append("\n").append(s.name()).append(" · v").append(s.version()).append("\n").append(s.description()).append("\n/skill ").append(s.skillId()).append(" 你的问题\n");if(skills.size()>15)result.append("\n此处显示前 15 个，其余可通过输入框命令搜索或技能页面查看。");return result.toString();}
    private String describe(SkillDtos.LoadedSkill s){return s.metadata().name()+" · v"+s.metadata().version()+"\n"+s.metadata().description()+"\n适用工具："+String.join("、",s.metadata().tools())+"\n\n"+s.instructions();}
    private String help(){return "支持的技能命令\n/help 查看帮助\n/skills 或 /skills list 列出当前角色可用技能\n/skills info 技能名 查看已发布技能\n/skills manage 查看技能管理入口\n/skill 技能名或skill-id 你的问题 明确加载并使用技能\n/技能名 你的问题 也可直接调用；同名技能需用 skill-id\n\n技能只能指导已授权工具，不能增加权限或代替业务审批。"+(evolution!=null&&evolution.linksEnabled()?"/skills install 公开链接 打开页面确认下载，审批后可用；卸载在技能页面执行。":"外部 Skill 自动安装、卸载尚未接入。");}
}
